import json
from datetime import date

import pytest

from fakes import FakeClaude
from gym_coach.llm import Claude
from gym_coach.planner import PlanError, approve, propose
from gym_coach.prompts import CARDIO_SENTENCE
from gym_coach.store import Store

MODEL = "claude-opus-5-5"
WEEK = date(2026, 11, 16)  # Monday
EQ = "examples/equipment.md"
PROFILE = "examples/profile.md"
WEEKDAYS = ("2026-11-16", "2026-11-18", "2026-11-20")


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def ex(equipment):
    return {"name": "Press", "equipment": equipment, "sets": 3,
            "rep_low": 8, "rep_high": 12, "weight_kg": 20}


def plan(strength=WEEKDAYS, equipment="Chest press", message="Here is your week."):
    sessions = [{"date": d, "kind": "strength", "exercises": [ex(equipment)]} for d in strength]
    sessions.append({"date": "2026-11-17", "kind": "cardio", "exercises": []})
    return json.dumps({"message": message, "sessions": sessions})


def run(store, replies, **kw):
    fake = FakeClaude(replies)
    claude = Claude(fake, store, 5.0)
    msg = propose(claude, store, MODEL, WEEK, profile_path=PROFILE, equipment_path=EQ, **kw)
    return fake, msg


def prompt_of(fake, i):
    return fake.calls[i]["messages"][0]["content"][0]["text"]


def week(store):
    return store.plan_sessions("2026-11-16", "2026-11-22")


def test_valid_plan_is_stored_proposed(store):
    fake, msg = run(store, [plan()])
    rows = week(store)
    assert [r["status"] for r in rows] == ["proposed"] * 4
    assert rows[0]["gym"] == "home" and rows[0]["exercises"][0]["equipment"] == "Chest press"
    assert CARDIO_SENTENCE in msg
    assert len(fake.calls) == 1


def test_missing_equipment_is_regenerated_once(store):
    fake, _ = run(store, [plan(equipment="Leg press"), plan()])  # no leg press at home
    assert len(fake.calls) == 2
    assert "Leg press" in prompt_of(fake, 1)
    assert len(week(store)) == 4


def test_equipment_checked_against_that_days_gym(store):
    def with_sunday(equipment):
        data = json.loads(plan())
        data["sessions"][2] = {"date": "2026-11-22", "kind": "strength",
                               "exercises": [ex(equipment)]}
        return json.dumps(data)

    run(store, [with_sunday("Seated leg press")])  # the parents' gym has it
    with pytest.raises(PlanError):  # the home gym does not, and Sunday is not home
        run(store, [with_sunday("Leg extension")] * 2)


def test_second_rejection_fails_loudly_and_stores_nothing(store):
    with pytest.raises(PlanError):
        run(store, [plan(equipment="Leg press")] * 2)
    assert week(store) == []


def test_saturday_strength_rejected(store):
    with pytest.raises(PlanError):
        run(store, [plan(strength=("2026-11-16", "2026-11-18", "2026-11-21"))] * 2)


def test_cardio_sentence_added_if_model_omits_it(store):
    _, msg = run(store, [plan(message="Hi")])
    assert msg.startswith("Hi") and CARDIO_SENTENCE in msg


def test_approve(store):
    run(store, [plan()])
    assert approve(store, WEEK) == 4
    assert {r["status"] for r in week(store)} == {"approved"}


def test_change_request_makes_new_proposal(store):
    run(store, [plan()])
    moved = plan(strength=("2026-11-16", "2026-11-18", "2026-11-19"))
    fake, _ = run(store, [moved], change="move Friday to Thursday")
    assert "move Friday to Thursday" in prompt_of(fake, 0) and "2026-11-20" in prompt_of(fake, 0)
    dates = [r["date"] for r in week(store)]
    assert "2026-11-19" in dates and "2026-11-20" not in dates
