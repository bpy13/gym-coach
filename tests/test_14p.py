"""Task 14p: no approval step; the week is fixed (strength Tue/Thu/Sun, a jog Mon/Wed/Fri)."""

import json
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from fakes import FakeClaude
from gym_coach.llm import Claude
from gym_coach.messages import proposal_message, session_message
from gym_coach.planner import PlanError, propose
from gym_coach.prompts import PLAN_SYSTEM, WEEK_SENTENCE
from gym_coach.scheduler import Scheduler
from gym_coach.store import Store

HK = ZoneInfo("Asia/Hong_Kong")
MODEL = "claude-opus-5-5"
WEEK = date(2026, 11, 16)  # Monday
EQ = "examples/equipment.md"
PROFILE = "examples/profile.md"
STRENGTH = ("2026-11-17", "2026-11-19", "2026-11-22")  # Tue, Thu, Sun
JOG = ("2026-11-16", "2026-11-18", "2026-11-20")  # Mon, Wed, Fri
EX = {"name": "Press", "equipment": "Chest press", "sets": 3, "rep_low": 8, "rep_high": 12,
      "weight_kg": 20}


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def at(day, hh=7, mm=0):
    return lambda: datetime.fromisoformat(day).replace(hour=hh, minute=mm, tzinfo=HK)


@pytest.mark.parametrize("kind,exs", [("strength", [EX]), ("cardio", [])])
def test_proposed_session_gets_its_reminder(store, kind, exs):
    store.add_plan_session("2026-11-25", "home", kind, "proposed", exs)
    sent = []
    Scheduler(store, sent.append, now=at("2026-11-25")).tick()
    assert sent, "a proposed session needs no approval to be reminded"


def test_proposed_strength_starts_the_morning_flow(store):
    store.add_plan_session("2026-11-26", "home", "strength", "proposed", [EX])
    sent = []
    Scheduler(store, sent.append, now=at("2026-11-26")).tick()
    assert sent[1].startswith("Warm-up") and store.get("flow:2026-11-26") == "0"


def test_before_seven_nothing_and_skipped_still_silent(store):
    store.add_plan_session("2026-11-26", "home", "strength", "proposed", [EX])
    store.add_plan_session("2026-11-27", "home", "cardio", "skipped", [])
    sent = []
    Scheduler(store, sent.append, now=at("2026-11-26", 6, 59)).tick()
    Scheduler(store, sent.append, now=at("2026-11-27", 8)).tick()
    assert sent == []


def run(store, sessions, message="Here is your week."):
    reply = json.dumps({"message": message, "sessions": sessions})
    claude = Claude(FakeClaude([reply, reply]), store, 5.0)
    return propose(claude, store, MODEL, WEEK, profile_path=PROFILE, equipment_path=EQ)


def strength(days=STRENGTH):
    return [{"date": d, "kind": "strength", "exercises": [dict(EX)]} for d in days]


def test_week_always_has_strength_tue_thu_sun_and_jog_mon_wed_fri(store):
    run(store, strength() + [{"date": "2026-11-18", "kind": "cardio", "exercises": []}])
    rows = {r["date"]: r["kind"] for r in store.plan_sessions("2026-11-16", "2026-11-22")}
    assert rows == {**{d: "strength" for d in STRENGTH}, **{d: "cardio" for d in JOG}}
    assert "2026-11-21" not in rows  # Saturday has no session


def test_jog_days_filled_by_code_when_model_leaves_them_out(store):
    run(store, strength())
    jogs = [r["date"] for r in store.plan_sessions("2026-11-16", "2026-11-22")
            if r["kind"] == "cardio"]
    assert jogs == list(JOG)


@pytest.mark.parametrize("days", [
    ("2026-11-16", "2026-11-19", "2026-11-22"),  # Monday strength
    ("2026-11-17", "2026-11-19", "2026-11-21"),  # Saturday strength
    ("2026-11-17", "2026-11-19"),  # only two
])
def test_strength_off_the_fixed_days_rejected(store, days):
    with pytest.raises(PlanError):
        run(store, strength(days))


def test_sunday_is_at_parents(store):
    run(store, strength())
    assert store.plan_session("2026-11-22")["gym"] == "parents"


def test_proposal_is_information_not_a_question(store):
    msg = run(store, strength(), message="Here is your week.")
    assert WEEK_SENTENCE in msg and "?" not in msg and "No need to approve" in msg
    assert "never ask him to approve" in PLAN_SYSTEM


def test_cardio_is_called_jog():
    s = {"date": "2026-11-18", "gym": "home", "kind": "cardio", "exercises": []}
    assert session_message(s).splitlines()[1].startswith("Jog")
    assert "jog" in proposal_message("Week.", [s]).lower()
