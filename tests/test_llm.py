from datetime import datetime

import pytest

from fakes import FakeClaude
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
