from datetime import datetime

import pytest

from fakes import FakeClaude, tool_use
from gym_coach.llm import HK, CeilingReached, Claude, LLMError, cost_usd
from gym_coach.store import Store

HAIKU, OPUS = "claude-haiku-5-5", "claude-opus-5-5"


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def make(store, fake, now=datetime(2026, 11, 13, 12, 0, tzinfo=HK), ceiling=5.0):
    return Claude(fake, store, ceiling, now=lambda: now)


def test_price_table():
    assert cost_usd(HAIKU, 100_000, 100_000) == pytest.approx(0.06)
    assert cost_usd(OPUS, 1_000_000, 1_000_000) == pytest.approx(24.0)
    assert cost_usd(HAIKU, 100_001, 1_000_000) == pytest.approx(0.05 + 2.5)
    assert cost_usd(HAIKU, 100_001, 0) == pytest.approx(100_001 * 0.50 / 1e6)


def test_call_writes_one_row_with_cost(store):
    fake = FakeClaude(["hello"], input_tokens=2000, output_tokens=500)
    claude = make(store, fake)
    assert claude.text(OPUS, "hi") == "hello"
    assert claude.month_cost() == pytest.approx((2000 * 4 + 500 * 20) / 1e6)
    rows = store._rows("SELECT * FROM api_calls")
    assert len(rows) == 1 and rows[0]["model"] == OPUS
    assert (rows[0]["input_tokens"], rows[0]["output_tokens"]) == (2000, 500)


def test_ceiling_blocks_call(store):
    store.add_api_call("2026-11-02T10:00:00+08:00", OPUS, 1, 1, 5.0)
    fake = FakeClaude(["x"])
    with pytest.raises(CeilingReached):
        make(store, fake).text(HAIKU, "hi")
    assert fake.calls == []


def test_new_month_starts_from_zero_in_hong_kong_time(store):
    store.add_api_call("2026-11-30T23:59:00+08:00", OPUS, 1, 1, 5.0)
    fake = FakeClaude(["x"])
    with pytest.raises(CeilingReached):
        make(store, fake, now=datetime(2026, 11, 30, 23, 59, 30, tzinfo=HK)).text(HAIKU, "hi")
    # 16:01 UTC on 30 Nov is already 1 Dec 00:01 in Hong Kong.
    utc = datetime.fromisoformat("2026-11-30T16:01:00+00:00")
    claude = make(store, fake, now=utc)
    assert claude.month_cost() == 0
    assert claude.text(HAIKU, "hi") == "x"


def test_december_rolls_into_january(store):
    store.add_api_call("2026-12-05T10:00:00+08:00", OPUS, 1, 1, 2.0)
    claude = make(store, FakeClaude(), now=datetime(2026, 12, 20, tzinfo=HK))
    assert claude.month_cost() == pytest.approx(2.0)


def test_image_is_sent_as_base64_jpeg(store):
    fake = FakeClaude(["meal"])
    make(store, fake).text_with_image(HAIKU, "what is this?", b"\xff\xd8jpg")
    block = fake.calls[0]["messages"][0]["content"][0]
    assert block["type"] == "image" and block["source"]["media_type"] == "image/jpeg"


def test_json_parses_fenced_reply(store):
    fake = FakeClaude(['```json\n{"a": 1}\n```'])
    assert make(store, fake).json(HAIKU, "q") == {"a": 1}


def test_json_retries_once_then_succeeds(store):
    fake = FakeClaude(["not json", '{"a": 2}'])
    assert make(store, fake).json(HAIKU, "q") == {"a": 2}
    assert len(fake.calls) == 2


def test_json_raises_after_second_failure(store):
    fake = FakeClaude(["nope", "still nope"])
    with pytest.raises(LLMError):
        make(store, fake).json(HAIKU, "q")
    assert len(fake.calls) == 2


# --- converse: the tool loop (Task 15b) ---

TOOLS = [{"name": "log_sets", "description": "Log sets.",
          "input_schema": {"type": "object", "properties": {}}}]


def user(text):
    return [{"role": "user", "content": [{"type": "text", "text": text}]}]


def test_converse_without_tools_returns_text(store):
    fake = FakeClaude(["Nice set."])
    ran = []
    reply = make(store, fake).converse(HAIKU, "coach", user("hi"), TOOLS,
                                       lambda n, i: ran.append(n) or "")
    assert reply == "Nice set." and ran == []
    call = fake.calls[0]
    assert call["tools"] == TOOLS and call["system"] == "coach"
    assert call["messages"] == user("hi")


def test_converse_runs_tools_and_sends_results_back(store):
    fake = FakeClaude([
        ["Logging.", tool_use("log_sets", {"reps": 12}, id="a"),
         tool_use("fix_set", {"set_no": 3}, id="b")],
        [tool_use("log_sets", {"reps": 10}, id="c")],
        ["Logged 35 kg x 12.", " Next: rear delt."],
    ])
    ran = []

    def run_tool(name, input):
        ran.append((name, input))
        return f"done {name}"

    messages = user("35kg x12")
    reply = make(store, fake).converse(HAIKU, "coach", messages, TOOLS, run_tool)
    assert reply == "Logged 35 kg x 12. Next: rear delt."
    assert ran == [("log_sets", {"reps": 12}), ("fix_set", {"set_no": 3}),
                   ("log_sets", {"reps": 10})]
    assert messages == user("35kg x12")  # the caller's list is left alone
    second = fake.calls[1]["messages"]
    assert len(second) == 3
    assert second[1] == {"role": "assistant", "content": [
        {"type": "text", "text": "Logging."},
        {"type": "tool_use", "id": "a", "name": "log_sets", "input": {"reps": 12}},
        {"type": "tool_use", "id": "b", "name": "fix_set", "input": {"set_no": 3}},
    ]}
    assert second[2] == {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "a", "content": "done log_sets"},
        {"type": "tool_result", "tool_use_id": "b", "content": "done fix_set"},
    ]}
    assert len(fake.calls[2]["messages"]) == 5


def test_converse_tool_error_becomes_is_error_result(store):
    fake = FakeClaude([[tool_use("swap", {}, id="x")], "Which machine?"])

    def run_tool(name, input):
        raise ValueError("No lying curl at this gym. Choose: leg curl, cable")

    reply = make(store, fake).converse(HAIKU, "", user("swap"), TOOLS, run_tool)
    assert reply == "Which machine?"
    result = fake.calls[1]["messages"][2]["content"][0]
    assert result == {"type": "tool_result", "tool_use_id": "x", "is_error": True,
                      "content": "No lying curl at this gym. Choose: leg curl, cable"}
    assert "system" not in fake.calls[0]


def test_converse_records_cost_and_trace_for_every_round(store):
    fake = FakeClaude([[tool_use("log_sets", {})], [tool_use("fix_set", {}),
                       tool_use("log_sets", {})], "ok"], input_tokens=2000, output_tokens=500)
    claude = make(store, fake)
    claude.trace = []
    claude.converse(HAIKU, "", user("x"), TOOLS, lambda n, i: "")
    assert len(store._rows("SELECT * FROM api_calls")) == 3
    assert claude.month_cost() == pytest.approx(3 * cost_usd(HAIKU, 2000, 500))
    assert [t["tools"] for t in claude.trace] == [["log_sets"], ["fix_set", "log_sets"], []]
    assert claude.trace[2]["reply"] == "ok"
    assert all(t["model"] == HAIKU and t["input_tokens"] == 2000 for t in claude.trace)


def test_converse_ceiling_checked_before_every_round(store):
    store.add_api_call("2026-11-02T10:00:00+08:00", OPUS, 1, 1, 4.99)
    fake = FakeClaude([[tool_use("log_sets", {})], "ok"], input_tokens=100_000,
                      output_tokens=0)  # the first round costs US$0.01
    ran = []
    with pytest.raises(CeilingReached):
        make(store, fake).converse(HAIKU, "", user("x"), TOOLS,
                                   lambda n, i: ran.append(n) or "")
    assert len(fake.calls) == 1 and ran == ["log_sets"]


def test_converse_ceiling_blocks_first_call(store):
    store.add_api_call("2026-11-02T10:00:00+08:00", OPUS, 1, 1, 5.0)
    fake = FakeClaude(["ok"])
    with pytest.raises(CeilingReached):
        make(store, fake).converse(HAIKU, "", user("x"), TOOLS, lambda n, i: "")
    assert fake.calls == []


def test_converse_stops_after_six_rounds(store):
    fake = FakeClaude([[tool_use("log_sets", {})] for _ in range(10)])
    ran = []
    with pytest.raises(LLMError):
        make(store, fake).converse(HAIKU, "", user("x"), TOOLS,
                                   lambda n, i: ran.append(n) or "")
    assert len(fake.calls) == 6
    assert len(store._rows("SELECT * FROM api_calls")) == 6


def test_converse_puts_jpeg_first_in_first_user_message(store):
    fake = FakeClaude(["a bowl of rice"])
    messages = user("lunch")
    make(store, fake).converse(HAIKU, "", messages, TOOLS, lambda n, i: "", jpeg=b"\xff\xd8j")
    content = fake.calls[0]["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[0]["source"]["media_type"] == "image/jpeg"
    assert content[1] == {"type": "text", "text": "lunch"}
    assert messages == user("lunch")


def test_converse_accepts_string_content(store):
    fake = FakeClaude(["ok"])
    make(store, fake).converse(HAIKU, "", [{"role": "user", "content": "hi"}], TOOLS,
                               lambda n, i: "", jpeg=b"\xff\xd8j")
    content = fake.calls[0]["messages"][0]["content"]
    assert [b["type"] for b in content] == ["image", "text"]


def test_converse_error_from_client_is_traced(store):
    class Boom:
        def __init__(self):
            self.messages = self

        def create(self, **kwargs):
            raise RuntimeError("overloaded")

    claude = make(store, Boom())
    claude.trace = []
    with pytest.raises(RuntimeError):
        claude.converse(HAIKU, "", user("x"), TOOLS, lambda n, i: "")
    assert "overloaded" in claude.trace[0]["error"]
