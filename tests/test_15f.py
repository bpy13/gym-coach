"""Task 15f: fixes from the end-of-run review of Task 15 (the coach chat). Made-up data."""

import pytest

from fakes import tool_use
from gym_coach.llm import MAX_TOOL_ROUNDS
from gym_coach.store import Store
from test_coach import DAY, EQUIPMENT, EXS, SUN, log, make, saved


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    s.add_plan_session(DAY, "parents", "strength", "approved", EXS)
    s.set(f"flow:{DAY}", "0")
    s.set("chat_id", "5")
    yield s
    s.close()


@pytest.fixture
def equipment(tmp_path):
    path = tmp_path / "equipment.md"
    path.write_text(EQUIPMENT, encoding="utf-8")
    return path


# finding 1: a failure after a tool already changed the records

def _no_retry(reply):
    assert "try again" not in reply.lower()


def test_llm_error_after_a_logged_set_replies_with_what_was_saved(store, equipment):
    rounds = [[log("Low row", (35, 12), (35, 12), (35, 12))]] + [
        [tool_use("show_exercise", {"exercise": "Chest press"})]] * (MAX_TOOL_ROUNDS - 1)
    router, _ = make(store, equipment, rounds)
    reply = router.handle("low row 35 12 12 12")
    _no_retry(reply)
    assert "Low row: 35 kg x 12, 12, 12" in reply and "saved" in reply.lower()
    assert saved(store) == [("Low row", n, 35, 12) for n in (1, 2, 3)]
    assert "LLMError" in router.error


def test_sdk_error_after_a_logged_set_replies_with_what_was_saved(store, equipment):
    router, _ = make(store, equipment, [[log("Low row", (35, 12))],
                                        RuntimeError("overloaded")])
    reply = router.handle("low row 35 12")
    _no_retry(reply)
    assert "Low row: 35 kg x 12" in reply
    assert "RuntimeError: overloaded" in router.error


def test_ceiling_after_a_logged_set_replies_with_what_was_saved(store, equipment):
    # one fake round costs US$0.0002, so the second round finds the US$5 ceiling reached
    store.add_api_call(SUN.isoformat(), "claude-opus-5-5", 1, 1, 4.9999)
    router, fake = make(store, equipment, [[log("Low row", (35, 12))], "Logged."])
    reply = router.handle("low row 35 12")
    _no_retry(reply)
    assert "Low row: 35 kg x 12" in reply and len(fake.calls) == 1
    assert router.error == "monthly ceiling reached"


def test_sdk_error_before_any_tool_says_sorry_and_records_it(store, equipment):
    router, _ = make(store, equipment, [ConnectionError("network down")])
    reply = router.handle("low row 35 12")
    assert reply.startswith("Sorry")
    assert "ConnectionError: network down" in router.error
    assert saved(store) == []


def test_a_card_left_from_an_earlier_message_is_not_sent_with_the_next_reply(store, equipment):
    router, _ = make(store, equipment, ["Hi.", "Nice lunch."])
    router.exercise_to_send = (store.plan_session(DAY), 2)
    router.handle("hello")
    assert router.pop_exercise() is None
    router.exercise_to_send = (store.plan_session(DAY), 2)
    router.handle_photo(b"not a jpeg", "what is this")
    assert router.pop_exercise() is None
