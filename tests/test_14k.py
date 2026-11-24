"""Task 14k: planned weights come from what he last lifted, and past reps are in view (the
week proposal's prompt, its message, the workout coach's context and a past_sets tool).
Made-up data only."""

import json
from datetime import date, datetime

import pytest

from fakes import FakeClaude, tool_use
from gym_coach import reports
from gym_coach.coach import TOOLS
from gym_coach.llm import HK, Claude
from gym_coach.planner import PlanError, propose
from gym_coach.router import Router
from gym_coach.store import Store

MODEL = "claude-opus-5-5"
WEEK = date(2026, 11, 16)  # Monday
EQ = "examples/equipment.md"
PROFILE = "examples/profile.md"
STRENGTH = ("2026-11-17", "2026-11-19", "2026-11-22")


def ex(name, weight, equipment="Chest press", low=8, high=12):
    return {"name": name, "equipment": equipment, "sets": 3, "rep_low": low,
            "rep_high": high, "weight_kg": weight}


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def log(store, day, name, weight, *reps, plan=True):
    if plan:
        store.add_plan_session(day, "home", "strength", "done", [ex(name, weight)])
    for r in reps:
        reports.log_report(store, day, [{"exercise": name, "weight_kg": weight, "reps": r}])


def plan(exercises):
    sessions = [{"date": d, "kind": "strength", "exercises": exercises} for d in STRENGTH]
    sessions.append({"date": "2026-11-18", "kind": "cardio", "exercises": []})
    return json.dumps({"message": "Here is your week.", "sessions": sessions})


def run(store, exercises):
    fake = FakeClaude([plan(exercises)])
    msg = propose(Claude(fake, store, 5.0), store, MODEL, WEEK, profile_path=PROFILE,
                  equipment_path=EQ)
    return fake, msg


def prompt_of(fake, i=0):
    return fake.calls[i]["messages"][0]["content"][0]["text"]


# (1) the store reader

def test_recent_sets_gives_the_last_three_days_per_exercise_newest_first(store):
    for day, w in (("2026-11-03", 15), ("2026-11-05", 17.5), ("2026-11-10", 20),
                   ("2026-11-12", 22.5)):
        log(store, day, "Press", w, 10, 9)
    log(store, "2026-11-16", "Press", 25, 8)  # on or after `before`: left out
    reports.log_report(store, "2026-11-12", [{"exercise": " PRESS ", "weight_kg": 22.5,
                                              "reps": 7}])
    past = store.recent_sets("2026-11-16")
    assert list(past) == ["press"]
    days = past["press"]
    assert [d["date"] for d in days] == ["2026-11-12", "2026-11-10", "2026-11-05"]
    assert [(r["weight_kg"], r["reps"]) for r in days[0]["sets"]] == [
        (22.5, 10), (22.5, 9), (22.5, 7)]
    assert len(store.recent_sets("2026-11-16", since="2026-11-11")["press"]) == 1


# (2) the week proposal

def test_prompt_holds_the_history_and_the_rules(store):
    log(store, "2026-11-10", "Press", 20, 12, 11, 10)
    log(store, "2026-11-12", "Press", 20, 12, 12, 12)
    fake, _ = run(store, [ex("Press", 22.5), ex("Row", 30)])
    prompt = prompt_of(fake)
    assert ("- Press: 20 kg x 12, 12, 12 on 12 Nov (plan 8-12 reps); "
            "20 kg x 12, 11, 10 on 10 Nov (plan 8-12 reps)") in prompt
    assert "Row:" not in prompt.split("What he lifted before")[1]
    system = fake.calls[0]["system"]
    system = system if isinstance(system, str) else json.dumps(system)
    assert "start from his last logged weight" in system


def test_no_history_means_no_history_block(store):
    fake, _ = run(store, [ex("Press", 20)])
    assert "What he lifted before" not in prompt_of(fake)


def test_history_older_than_eight_weeks_is_left_out(store):
    log(store, "2026-09-15", "Press", 20, 12)  # 9 weeks before
    fake, _ = run(store, [ex("Press", 20)])
    assert "What he lifted before" not in prompt_of(fake)


def test_message_says_why_each_changed_weight_moved(store):
    log(store, "2026-11-12", "Press", 20, 12, 12, 12)
    log(store, "2026-11-13", "Pulldown", 30, 10, 7, 6)
    log(store, "2026-11-14", "Curl", 10, 10, 9, 9)
    _, msg = run(store, [ex("Press", 22.5), ex("Pulldown", 27.5), ex("Curl", 10)])
    assert "Weights from what you last lifted:" in msg
    assert ("Press: 20 → 22.5 kg (you reached 12 reps on every set: 20 kg x 12, 12, 12 "
            "on 12 Nov)") in msg
    assert "Pulldown: 30 → 27.5 kg (a set fell below 8 reps" in msg
    assert "Curl:" not in msg  # kept: no line
    assert msg.count("Press: 20 →") == 1  # once, though it is in three sessions


def test_no_change_lines_without_history(store):
    _, msg = run(store, [ex("Press", 20)])
    assert "Weights from what you last lifted" not in msg


# (4) nothing stored is changed; an approved week stays

def test_logged_sets_are_not_changed_by_a_proposal(store):
    log(store, "2026-11-12", "Press", 20, 12, 12, 12)
    before = store.logged_sets("2026-11-12")
    run(store, [ex("Press", 22.5)])
    assert store.logged_sets("2026-11-12") == before


def test_an_approved_week_is_not_rewritten(store):
    store.add_plan_session("2026-11-17", "home", "strength", "approved", [ex("Press", 20)])
    fake = FakeClaude([plan([ex("Press", 99)])])
    with pytest.raises(PlanError, match="already approved"):
        propose(Claude(fake, store, 5.0), store, MODEL, WEEK, profile_path=PROFILE,
                equipment_path=EQ)
    assert fake.calls == []
    assert store.plan_session("2026-11-17")["exercises"][0]["weight_kg"] == 20


# (3) during a workout

DAY = "2026-11-19"
NOW = datetime(2026, 11, 19, 17, 0, tzinfo=HK)


def router_for(store, replies=()):
    fake = FakeClaude(list(replies))
    router = Router(store, Claude(fake, store, 5.0, now=lambda: NOW), "claude-haiku-5-5",
                    MODEL, now=lambda: NOW, profile_path=PROFILE, equipment_path=EQ)
    return router, fake


@pytest.fixture
def workout(store):
    log(store, "2026-11-12", "Press", 32.5, 10, 10, plan=False)
    log(store, "2026-11-17", "Press", 35, 10, 10, 8)
    store.add_plan_session(DAY, "home", "strength", "approved",
                           [ex("Press", 35), ex("Row", 30, "Lat pulldown")])
    store.set(f"flow:{DAY}", "0")
    store.set("chat_id", "5")
    return store


def test_context_shows_what_he_did_last_time(workout):
    router, _ = router_for(workout)
    text = router.context(DAY)
    assert "- Press: 0 of 3 sets logged (plan 8-12 reps at 35 kg) | last: 35 kg x 10, 10, 8 " \
           "on 17 Nov" in text
    row = next(ln for ln in text.splitlines() if ln.startswith("- Row:"))
    assert "last:" not in row


def test_todays_sets_are_not_last_time(workout):
    reports.log_report(workout, DAY, [{"exercise": "Press", "weight_kg": 37.5, "reps": 9}])
    router, _ = router_for(workout)
    assert "last: 35 kg x 10, 10, 8 on 17 Nov" in router.context(DAY)


def test_past_sets_tool_gives_earlier_days(workout):
    assert any(t["name"] == "past_sets" for t in TOOLS)
    router, fake = router_for(workout, [
        [tool_use("past_sets", {"exercise": "press"})], "You did 35 kg x 10, 10, 8."])
    reply = router.handle("what did I press before?")
    assert reply == "You did 35 kg x 10, 10, 8."
    result = fake.calls[-1]["messages"][-1]["content"][0]["content"]
    assert "Press: 35 kg x 10, 10, 8 on 17 Nov; 32.5 kg x 10, 10 on 12 Nov." in str(result)
    assert workout.logged_sets(DAY) == []


def test_past_sets_tool_names_what_is_logged_when_nothing_matches(workout):
    router, fake = router_for(workout, [
        [tool_use("past_sets", {"exercise": "Squat"})], "No squats yet."])
    router.handle("what did I squat?")
    result = str(fake.calls[-1]["messages"][-1]["content"][0]["content"])
    assert 'Nothing of "Squat" is logged before today' in result and "Press" in result
