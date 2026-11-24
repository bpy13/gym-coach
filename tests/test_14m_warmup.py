"""Task 14m, first part (live bug 24 Nov): "warm up is gone". He asked for the day in free
text, the workout never opened, and the coach made up a warm-up. Now the coach always sees the
fixed routine and its state, and a tool starts the workout exactly as "start" does.
Made-up data only."""

import pytest

from fakes import tool_use
from gym_coach.coach import SYSTEM, TOOLS
from gym_coach.messages import warm_up_message
from gym_coach.store import Store
from test_session_fixes import DAY, EXS, build, turn

START = turn(tool_use("start_workout", {}), text="Here is the warm-up.")


@pytest.fixture
def store(tmp_path):
    """A strength day whose 07:00 message never went out: no flow, no warm-up key."""
    s = Store(tmp_path / "t.db")
    s.add_plan_session(DAY, "home", "strength", "approved", EXS)
    s.set("chat_id", "5")
    yield s
    s.close()


def test_warm_up_question_gets_the_fixed_routine_and_starts_the_workout(store):
    router = build(store, [START])[1]
    reply = router.handle("Warm up?")
    assert warm_up_message() in reply
    assert store.get(f"warmup:{DAY}") == "1"
    assert store.get(f"flow:{DAY}") == "0"
    assert (store.get(f"workout:{DAY}") or "").startswith("open|")


def test_the_tool_does_what_start_does(store, tmp_path):
    other = Store(tmp_path / "o.db")
    other.add_plan_session(DAY, "home", "strength", "approved", EXS)
    other.set("chat_id", "5")
    build(other, [])[1].handle("start")
    build(store, [START])[1].handle("what's today's schedule?")
    for k in ("warmup:", "flow:"):
        assert store.get(k + DAY) == other.get(k + DAY)
    assert store.get(f"workout:{DAY}")[:5] == other.get(f"workout:{DAY}")[:5] == "open|"
    other.close()


def test_coach_context_carries_the_routine_and_its_state(store):
    router = build(store, [])[1]
    ctx = router.context(DAY)
    assert warm_up_message().splitlines()[1] in ctx  # the routine itself
    assert "Warm-up: not sent yet" in ctx
    store.set(f"flow:{DAY}", "0")
    store.set(f"warmup:{DAY}", "1")
    assert "Warm-up: sent, not done yet" in router.context(DAY)
    store.set(f"warmup:{DAY}", "")
    assert "Warm-up: done" in router.context(DAY)


def test_system_says_never_invent_a_warm_up_and_names_the_tool():
    assert "start_workout" in [t["name"] for t in TOOLS]
    assert "never make up another warm-up" in SYSTEM.lower()
    assert "start_workout" in SYSTEM


def test_today_list_before_the_warm_up_says_it_comes_first(store):
    router = build(store, [])[1]
    assert "Warm-up first" in router.handle("/today")
    store.set(f"flow:{DAY}", "0")
    store.set(f"warmup:{DAY}", "1")
    assert "Warm-up first" in router.handle("/today")
    store.set(f"warmup:{DAY}", "")
    assert "Warm-up first" not in router.handle("/today")
