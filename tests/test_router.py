import json
from datetime import datetime

import pytest

from fakes import FakeClaude
from gym_coach.llm import HK, Claude
from gym_coach.router import Router
from gym_coach.store import Store

TUE = datetime(2026, 11, 17, 18, 0, tzinfo=HK)
DAY = "2026-11-17"
EX = {"name": "Press", "equipment": "Chest press", "sets": 3, "rep_low": 8, "rep_high": 12,
      "weight_kg": 20}


def intent(name, **extra):
    return json.dumps({"intent": name, **extra})


def sets(name, weight, *reps):
    return [{"exercise": name, "weight_kg": weight, "reps": r} for r in reps]


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def make(store, replies, ceiling=5.0):
    fake = FakeClaude(replies)
    router = Router(store, Claude(fake, store, ceiling, now=lambda: TUE),
                    "claude-haiku-5-5", "claude-opus-5-5", now=lambda: TUE,
                    profile_path="examples/profile.md", equipment_path="examples/equipment.md")
    return router, fake


def test_report_logs_six_sets_and_replies_logged(store):
    reply_sets = sets("Chest press", 35, 10, 10, 8) + sets("Lat pulldown", 40, 10, 10, 10)
    router, _ = make(store, [intent("report", sets=reply_sets)])
    reply = router.handle("chest press 35kg 10 10 8, lat pulldown 40 3x10")
    assert reply.startswith("Logged:")
    assert "Chest press: 35 kg x 10, 10, 8" in reply
    assert "Lat pulldown: 40 kg x 10, 10, 10" in reply
    assert len(store.logged_sets(DAY)) == 6


def test_correction_replaces_sets(store):
    router, _ = make(store, [
        intent("report", sets=sets("Chest press", 35, 10, 10, 8)),
        intent("correction", sets=sets("Chest press", 30, 10, 10, 8)),
    ])
    router.handle("chest press 35 kg 10 10 8")
    reply = router.handle("no, chest press was 30 kg")
    assert reply.startswith("Corrected:") and "30 kg x 10, 10, 8" in reply
    assert [r["weight_kg"] for r in store.logged_sets(DAY)] == [30, 30, 30]


def test_approve_approves_proposed_plan(store):
    store.add_plan_session(DAY, "home", "strength", "proposed", [EX])
    router, _ = make(store, [intent("approve")])
    assert router.handle("approve").startswith("Approved")
    assert store.plan_session(DAY)["status"] == "approved"


def test_approve_with_nothing_proposed(store):
    router, _ = make(store, [intent("approve")])
    assert "no proposed plan" in router.handle("ok go")


def test_skip_today(store):
    store.add_plan_session(DAY, "home", "strength", "approved", [EX])
    router, _ = make(store, [intent("skip")])
    router.handle("skip today")
    assert store.plan_session(DAY)["status"] == "skipped"


def test_commands_skip_the_model(store):
    store.add_plan_session(DAY, "home", "strength", "approved", [EX])
    router, fake = make(store, [])
    assert "Press: 3 x 8-12 at 20 kg" in router.handle("/today")
    assert "US$0.00 of US$5" in router.handle("/cost")
    assert "gym coach" in router.handle("/start")
    assert "coming soon" in router.handle("/progress")
    assert fake.calls == []


def test_ceiling_reached_reply(store):
    store.add_api_call(TUE.isoformat(), "claude-opus-5-5", 1, 1, 5.0)
    router, fake = make(store, [])
    reply = router.handle("chest press 35 kg 10")
    assert "US$5 limit" in reply and fake.calls == []
    assert "US$5.00 of US$5" in router.handle("/cost")


def test_question_gets_model_answer(store):
    router, fake = make(store, [intent("question"), "Rest 90 seconds."])
    assert router.handle("how long should I rest?") == "Rest 90 seconds."
    assert len(fake.calls) == 2


def test_unusable_report_asks_again(store):
    router, _ = make(store, [intent("report", sets=[])])
    assert "could not find any sets" in router.handle("did some stuff")
