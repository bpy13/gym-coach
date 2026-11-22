from datetime import datetime

import pytest

from fakes import FakeClaude, tool_use
from gym_coach.llm import HK, Claude
from gym_coach.router import Router
from gym_coach.scheduler import Scheduler
from gym_coach.store import Store
from test_session_fixes import flat, turn

MONDAY = datetime(2026, 11, 16, 7, 0, tzinfo=HK)
DAY = "2026-11-16"


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def body(weight, waist=None, confirmed=False):
    data = {"weight_kg": weight, "confirmed": confirmed}
    if waist is not None:
        data["waist_cm"] = waist
    return turn(tool_use("log_body", data))


def make(store, replies):
    fake = FakeClaude(flat(replies))
    router = Router(store, Claude(fake, store, 5.0, now=lambda: MONDAY),
                    "claude-haiku-5-5", "claude-opus-5-5", now=lambda: MONDAY,
                    profile_path="examples/profile.md", equipment_path="examples/equipment.md")
    return router, fake


def test_monday_seven_sends_one_prompt(store):
    sent = []
    sched = Scheduler(store, sent.append, now=lambda: MONDAY)
    sched.tick()
    sched.tick()
    assert len(sent) == 1 and "body weight" in sent[0] and "81.6 kg" in sent[0] and "waist" not in sent[0]


def test_no_prompt_before_seven_or_on_other_days(store):
    sent = []
    Scheduler(store, sent.append, now=lambda: MONDAY.replace(hour=6, minute=59)).tick()
    Scheduler(store, sent.append, now=lambda: MONDAY.replace(day=17)).tick()
    assert sent == []


def test_weight_alone_stores_one_row(store):
    router, _ = make(store, [body(81.6), body(81.6, confirmed=True)])
    router.handle("81.6 kg")
    router.handle("yes")  # 81.6 is far from the example profile's 70 kg
    assert [(r["weight_kg"], r["waist_cm"]) for r in store.body_entries()] == [(81.6, None)]


def test_weight_and_waist_store_one_row(store):
    router, _ = make(store, [body(71.6, 91)])
    reply = router.handle("71.6 kg, waist 91")
    rows = store.body_entries()
    assert [(r["date"], r["weight_kg"], r["waist_cm"]) for r in rows] == [(DAY, 71.6, 91.0)]
    assert reply.startswith("Saved: 71.6 kg, waist 91 cm.")


def test_far_weight_is_questioned_before_storing(store):
    router, _ = make(store, [body(81.6, 91)])  # example profile is 70 kg
    reply = router.handle("81.6 kg, waist 91")
    assert "Not saved" in reply and "ask him" in reply
    assert store.body_entries() == []


def test_yes_stores_the_questioned_weight(store):
    router, _ = make(store, [body(81.6, 91), body(81.6, 91, confirmed=True)])
    router.handle("81.6 kg, waist 91")
    reply = router.handle("yes")
    assert [(r["weight_kg"], r["waist_cm"]) for r in store.body_entries()] == [(81.6, 91.0)]
    assert reply.startswith("Saved: 81.6 kg")


def test_other_message_drops_the_question(store):
    router, _ = make(store, [body(81.6), body(71.0)])
    router.handle("81.6")
    router.handle("sorry, 71")
    assert [r["weight_kg"] for r in store.body_entries()] == [71.0]


def test_jump_is_measured_from_the_last_stored_weight(store):
    store.add_body("2026-11-09", 80.0, None)
    router, _ = make(store, [body(81.6)])
    router.handle("81.6")
    assert [r["weight_kg"] for r in store.body_entries()] == [80.0, 81.6]


def test_missing_weight_is_refused(store):
    router, fake = make(store, [body(None, 90)])
    router.handle("waist 90")
    last = fake.calls[1]["messages"][-1]["content"][0]
    assert last["is_error"] and "weight_kg" in last["content"]
    assert store.body_entries() == []
