import json
from datetime import datetime

import pytest

from fakes import FakeClaude
from gym_coach.llm import HK, Claude
from gym_coach.router import Router
from gym_coach.scheduler import Scheduler
from gym_coach.store import Store

MONDAY = datetime(2026, 11, 16, 7, 0, tzinfo=HK)
DAY = "2026-11-16"


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def body(weight, waist=None):
    return json.dumps({"intent": "body", "weight_kg": weight, "waist_cm": waist})


def make(store, replies):
    fake = FakeClaude(replies)
    router = Router(store, Claude(fake, store, 5.0, now=lambda: MONDAY),
                    "claude-haiku-5-5", "claude-opus-5-5", now=lambda: MONDAY,
                    profile_path="examples/profile.md", equipment_path="examples/equipment.md")
    return router, fake


def test_monday_seven_sends_one_prompt(store):
    sent = []
    sched = Scheduler(store, sent.append, now=lambda: MONDAY)
    sched.tick()
    sched.tick()
    assert len(sent) == 1 and "weight" in sent[0] and "waist" in sent[0]


def test_no_prompt_before_seven_or_on_other_days(store):
    sent = []
    Scheduler(store, sent.append, now=lambda: MONDAY.replace(hour=6, minute=59)).tick()
    Scheduler(store, sent.append, now=lambda: MONDAY.replace(day=17)).tick()
    assert sent == []


def test_weight_and_waist_store_one_row(store):
    router, _ = make(store, [body(71.6, 91)])
    reply = router.handle("71.6 kg, waist 91")
    rows = store.body_entries()
    assert [(r["date"], r["weight_kg"], r["waist_cm"]) for r in rows] == [(DAY, 71.6, 91.0)]
    assert reply.startswith("Saved: 71.6 kg, waist 91 cm.")


def test_far_weight_is_questioned_before_storing(store):
    router, _ = make(store, [body(81.6, 91)])  # example profile is 70 kg
    reply = router.handle("81.6 kg, waist 91")
    assert "Is that right?" in reply
    assert store.body_entries() == []


def test_yes_stores_the_questioned_weight(store):
    router, fake = make(store, [body(81.6, 91)])
    router.handle("81.6 kg, waist 91")
    reply = router.handle("yes")
    assert len(fake.calls) == 1  # "yes" needs no model call
    assert [(r["weight_kg"], r["waist_cm"]) for r in store.body_entries()] == [(81.6, 91.0)]
    assert reply.startswith("Saved: 81.6 kg")


def test_other_message_drops_the_question(store):
    router, _ = make(store, [body(81.6), body(71.0), json.dumps({"intent": "question"}), "ok"])
    router.handle("81.6")
    router.handle("sorry, 71")
    assert [r["weight_kg"] for r in store.body_entries()] == [71.0]


def test_jump_is_measured_from_the_last_stored_weight(store):
    store.add_body("2026-11-09", 80.0, None)
    router, _ = make(store, [body(81.6)])
    router.handle("81.6")
    assert [r["weight_kg"] for r in store.body_entries()] == [80.0, 81.6]


def test_missing_weight_asks_again(store):
    router, _ = make(store, [body(None, 90)])
    assert "did not catch" in router.handle("waist 90")
    assert store.body_entries() == []
