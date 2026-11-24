import json
from datetime import datetime

import pytest

from fakes import FakeClaude, tool_use
from gym_coach.llm import HK, Claude
from gym_coach.router import Router
from gym_coach.store import Store
from test_session_fixes import flat, tool_results, turn

TUE = datetime(2026, 11, 17, 18, 0, tzinfo=HK)
DAY = "2026-11-17"
EX = {"name": "Press", "equipment": "Chest press", "sets": 3, "rep_low": 8, "rep_high": 12,
      "weight_kg": 20}


def sets(name, weight, *reps):
    return [{"exercise": name, "weight_kg": weight, "reps": r} for r in reps]


def log(*sets_):
    return turn(tool_use("log_sets", {"sets": [s for group in sets_ for s in group]}))


def call(name, **data):
    return turn(tool_use(name, data))


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def make(store, replies, ceiling=5.0):
    fake = FakeClaude(flat(replies))
    router = Router(store, Claude(fake, store, ceiling, now=lambda: TUE),
                    "claude-haiku-5-5", "claude-opus-5-5", now=lambda: TUE,
                    profile_path="examples/profile.md", equipment_path="examples/equipment.md")
    return router, fake


def test_report_without_a_session_logs_six_sets(store):
    router, _ = make(store, [log(sets("Chest press", 35, 10, 10, 8),
                                 sets("Lat pulldown", 40, 10, 10, 10))])
    reply = router.handle("chest press 35kg 10 10 8, lat pulldown 40 3x10")
    assert "Chest press: 35 kg x 10, 10, 8 (saved now: sets 1, 2, 3)" in reply
    assert "Lat pulldown: 40 kg x 10, 10, 10" in reply
    assert len(store.logged_sets(DAY)) == 6


def test_correction_fixes_each_set(store):
    router, _ = make(store, [
        log(sets("Chest press", 35, 10, 10, 8)),
        turn(*(tool_use("fix_set", {"exercise": "Chest press", "set_no": n, "weight_kg": 30})
               for n in (1, 2, 3)), text="Fixed all three to 30 kg."),
    ])
    router.handle("chest press 35 kg 10 10 8")
    assert router.handle("no, chest press was 30 kg") == "Fixed all three to 30 kg."
    assert [r["weight_kg"] for r in store.logged_sets(DAY)] == [30, 30, 30]


def test_approve_approves_proposed_plan(store):
    store.add_plan_session(DAY, "home", "strength", "proposed", [EX])
    router, _ = make(store, [call("approve_plan")])
    assert router.handle("approve").startswith("Approved")
    assert store.plan_session(DAY)["status"] == "approved"


def test_approve_with_nothing_proposed(store):
    router, _ = make(store, [call("approve_plan")])
    assert "no proposed plan" in router.handle("ok go")


def test_skip_today(store):
    store.add_plan_session(DAY, "home", "strength", "approved", [EX])
    router, _ = make(store, [call("skip_today")])
    router.handle("skip today")
    assert store.plan_session(DAY)["status"] == "skipped"


def test_commands_skip_the_model(store):
    store.add_plan_session(DAY, "home", "strength", "approved", [EX])
    router, fake = make(store, [])
    assert "Press: 3 x 8-12 (no earlier record)" in router.handle("/today")
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
    router, fake = make(store, ["Rest 90 seconds."])
    assert router.handle("how long should I rest?") == "Rest 90 seconds."
    assert len(fake.calls) == 1 and "general fitness guidance" in fake.calls[0]["system"]


def test_an_empty_report_is_refused(store):
    router, fake = make(store, [log([])])
    router.handle("did some stuff")
    [res] = tool_results(fake.calls[1])
    assert res["is_error"] and store.logged_sets(DAY) == []


def test_propose_command_stores_proposed_week(store):
    days = ("2026-11-24", "2026-11-26", "2026-11-29")
    sessions = [{"date": d, "kind": "strength", "exercises": [{**EX, "equipment": "Chest press"}]}
                for d in days]
    sessions.append({"date": "2026-11-25", "kind": "cardio", "exercises": []})
    router, fake = make(store, [json.dumps({"message": "Here is your week.",
                                            "sessions": sessions})])
    reply = router.handle("/propose")
    assert "Here is your week." in reply
    rows = store.plan_sessions("2026-11-23", "2026-11-29")
    assert len(rows) == 4 and {r["status"] for r in rows} == {"proposed"}
    assert len(fake.calls) == 1 and fake.calls[0]["model"] == "claude-opus-5-5"
