"""Task 14l: the day's weights follow his last session, also for a week planned earlier; the
same machine under another name is the same exercise. The 24 Nov case uses the weights the
plan file quotes; everything else is made up."""

import json
from datetime import date, datetime

import pytest

from fakes import FakeClaude
from gym_coach import reports, weights
from gym_coach.albums import exercise_parts
from gym_coach.llm import HK, Claude
from gym_coach.messages import list_message
from gym_coach.planner import propose
from gym_coach.router import Router
from gym_coach.scheduler import Scheduler
from gym_coach.store import Store

MODEL = "claude-opus-5-5"
EQ = "examples/equipment.md"
PROFILE = "examples/profile.md"
CABLE = "dual adjustable cable machine"
RACK = "dumbbells on a rack"
LAST = "2026-11-17"  # Tuesday, home
DAY = "2026-11-24"  # Tuesday, home


def ex(name, weight, equipment, low=8, high=12, **more):
    return {"name": name, "equipment": equipment, "sets": 3, "rep_low": low,
            "rep_high": high, "weight_kg": weight, **more}


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def did(store, day, gym, rows):
    """rows: (name, equipment, [(kg, reps), ...]); the day's plan names the equipment."""
    store.add_plan_session(day, gym, "strength", "done",
                           [ex(n, sets[0][0], gear) for n, gear, sets in rows])
    for name, _, sets in rows:
        for kg, reps in sets:
            reports.log_report(store, day, [{"exercise": name, "weight_kg": kg, "reps": reps}])


@pytest.fixture
def nov17(store):
    """The 24 Nov case: the home sets of 17 Nov the plan file quotes."""
    did(store, LAST, "home", [
        ("Machine chest press", "chest press", [(21, 12), (28, 12), (28, 12)]),
        ("Lat pulldown", "lat pulldown", [(35, 12), (35, 12), (35, 12)]),
        ("Seated cable row", CABLE, [(20, 15), (22.5, 15), (25, 15)]),
        ("Machine shoulder press", "shoulder press", [(21, 15), (21, 12), (21, 12)]),
    ])
    store.add_plan_session(DAY, "home", "strength", "approved", [
        ex("Chest press", 20, "chest press"),
        ex("Lat pulldown", 25, "lat pulldown"),
        ex("Seated cable row", 20, CABLE),
        ex("Shoulder press", 15, "shoulder press"),
        ex("Leg extension", 20, "leg extension"),  # never logged
    ])
    return store


def weight(store, exercise, gym="home", day=DAY):
    return weights.History(store, day).weight_for(exercise, gym)


# (1) one function gives the weight by the rule

def test_lat_pulldown_all_sets_at_the_top_goes_one_machine_step_up(nov17):
    got = weight(nov17, ex("Lat pulldown", 25, "lat pulldown"))
    # no gap of its own: the home machines move in 7 kg (chest press 21 -> 28)
    assert got == {"weight_kg": 42, "note": "up from 35 kg x 12, 12, 12 on 17 Nov"}


def test_seated_cable_row_goes_above_25(nov17):
    got = weight(nov17, ex("Seated cable row", 20, CABLE))
    assert got["weight_kg"] > 25 and got["weight_kg"] == 27.5
    assert got["note"].startswith("up from 20 kg x 15; 22.5 kg x 15; 25 kg x 15")


def test_reps_inside_the_range_keep_the_weight(store):
    did(store, LAST, "home", [("Lat pulldown", "lat pulldown", [(35, 10), (35, 10), (35, 9)])])
    got = weight(store, ex("Lat pulldown", 25, "lat pulldown"))
    assert got == {"weight_kg": 35, "note": "last time 35 kg x 10, 10, 9 on 17 Nov"}


def test_a_set_below_the_range_lowers_one_step(store):
    did(store, LAST, "home", [("Leg extension", "leg extension", [(21, 10), (28, 7), (28, 6)])])
    got = weight(store, ex("Leg extension", 30, "leg extension"))
    assert got["weight_kg"] == 21 and got["note"].startswith("down from 21 kg x 10; 28 kg x 7, 6")


def test_the_range_is_the_one_planned_that_day(store):
    store.add_plan_session(LAST, "home", "strength", "done",
                           [ex("Lat pulldown", 30, "lat pulldown", low=12, high=15)])
    reports.log_report(store, LAST, [{"exercise": "Lat pulldown", "weight_kg": 30, "reps": 12}])
    # 12 reps is the top of today's 8-12 but not of that day's 12-15: kept
    assert weight(store, ex("Lat pulldown", 25, "lat pulldown"))["weight_kg"] == 30


def test_steps_without_a_gap_of_its_own(store):
    did(store, LAST, "home", [
        ("Split squat with dumbbells", RACK, [(6, 12), (6, 12), (6, 12)]),
        ("Triceps pushdown", CABLE, [(12.5, 12), (12.5, 12), (12.5, 12)]),
    ])
    assert weight(store, ex("Split squat with dumbbells", 6, RACK))["weight_kg"] == 8
    assert weight(store, ex("Triceps pushdown", 10, CABLE))["weight_kg"] == 15  # 2.5 kg


def test_the_last_day_is_the_newest(store):
    did(store, "2026-11-10", "home", [("Lat pulldown", "lat pulldown", [(28, 12), (28, 12)])])
    did(store, LAST, "home", [("Lat pulldown", "lat pulldown", [(35, 9), (35, 9)])])
    assert weight(store, ex("Lat pulldown", 25, "lat pulldown"))["weight_kg"] == 35


# (3) the same machine is the same exercise; the other gym's machine is a note

def test_chest_press_finds_the_machine_chest_press_sets(nov17):
    got = weight(nov17, ex("Chest press", 20, "chest press"))
    assert got["weight_kg"] == 35  # 21, 28, 28 x 12: one 7 kg step up from 28
    assert got["note"] == ("up from 21 kg x 12; 28 kg x 12, 12 on 17 Nov "
                           "(Machine chest press)")
    assert weight(nov17, ex("Shoulder press", 15, "shoulder press"))["weight_kg"] == 28


def test_a_shared_machine_needs_a_shared_name_word(store):
    did(store, LAST, "home", [
        ("Seated cable row", CABLE, [(25, 12)]),
        ("Triceps pushdown with rope", CABLE, [(12.5, 12)]),
    ])
    assert weight(store, ex("Cable biceps curl", 10, CABLE)) is None
    assert weight(store, ex("Cable row", 10, CABLE))["note"].endswith("(Seated cable row)")
    assert weight(store, ex("Cable rope pushdown", 10, CABLE))["weight_kg"] == 15


def test_free_weights_match_by_name_only(store):
    did(store, LAST, "home", [("Dumbbell bench press", RACK, [(12, 12), (12, 12)])])
    assert weight(store, ex("Incline dumbbell press", 10, RACK)) is None


def test_the_same_machine_at_the_other_gym_is_not_matched_by_equipment(store):
    did(store, "2026-11-22", "parents", [("Machine chest press", "chest press", [(40, 12)])])
    assert weight(store, ex("Chest press", 20, "chest press"), gym="home") is None


def test_the_other_gyms_machine_is_a_note_only(store):
    did(store, "2026-11-22", "parents", [("Lying leg curl", "lying leg curl",
                                          [(21, 15), (21, 12), (21, 10)])])
    got = weight(store, ex("Lying leg curl", 15, "lying leg curl"), day="2026-11-24")
    assert got == {"weight_kg": None, "note": "parents gym: 21 kg x 15, 12, 10 on 22 Nov"}
    did(store, LAST, "home", [("Lying leg curl", "lying leg curl", [(28, 10), (28, 10)])])
    got = weight(store, ex("Lying leg curl", 15, "lying leg curl"), day="2026-11-24")
    assert got["weight_kg"] == 28
    assert got["note"] == ("last time 28 kg x 10, 10 on 17 Nov; "
                           "parents gym: 21 kg x 15, 12, 10 on 22 Nov")


def test_dumbbells_weigh_the_same_at_either_gym(store):
    did(store, "2026-11-22", "parents", [("Dumbbell lunges", RACK, [(8, 12), (8, 12)])])
    got = weight(store, ex("Dumbbell lunges", 6, RACK), day="2026-11-24")
    assert got == {"weight_kg": 10, "note": "up from 8 kg x 12, 12 on 22 Nov"}


# (2) a session not started shows and uses that weight

NOW = datetime(2026, 11, 24, 7, 30, tzinfo=HK)


def router_for(store):
    fake = FakeClaude([])
    return Router(store, Claude(fake, store, 5.0, now=lambda: NOW), "claude-haiku-5-5",
                  MODEL, now=lambda: NOW, profile_path=PROFILE, equipment_path=EQ)


def test_the_days_list_card_and_context_use_the_history_weight(nov17):
    router = router_for(nov17)
    today = router.handle("/today")
    assert "Lat pulldown: 3 x 8-12 at 42 kg (up from 35 kg x 12, 12, 12 on 17 Nov)" in today
    assert "Chest press: 3 x 8-12 at 35 kg (up from 21 kg x 12; 28 kg x 12, 12 on 17 Nov " \
           "(Machine chest press))" in today
    assert "Leg extension: 3 x 8-12 at 20 kg" in today  # no history: the stored weight
    assert "Leg extension: 3 x 8-12 at 20 kg (" not in today
    session = router.plan(DAY)
    caption, _ = exercise_parts(session, 1, equipment_path=EQ, photos_dir="no-photos")
    assert caption.startswith("Lat pulldown: 3 x 8-12 at 42 kg (up from 35 kg x 12, 12, 12")
    context = router.context(DAY)
    assert ("- Chest press: 0 of 3 sets logged (plan 8-12 reps at 35 kg, one step up from "
            "last time) | last: 21 kg x 12; 28 kg x 12, 12 on 17 Nov as Machine chest press"
            ) in context


def test_the_morning_list_uses_the_history_weight(nov17):
    sent = []
    Scheduler(nov17, sent.append, now=lambda: NOW).tick()
    assert "Lat pulldown: 3 x 8-12 at 42 kg (up from" in sent[0]


def test_a_proposed_week_planned_earlier_shows_it_too(nov17):
    nov17.add_plan_session("2026-11-26", "home", "strength", "proposed",
                           [ex("Lat pulldown", 25, "lat pulldown")])
    router = router_for(nov17)
    assert router.plan("2026-11-26")["exercises"][0]["weight_kg"] == 42
    # a later day is shown, not stored: a session he logs before it can still move it
    assert nov17.plan_session("2026-11-26")["exercises"][0]["weight_kg"] == 25


def test_todays_weights_are_kept_once_shown(nov17):
    router = router_for(nov17)
    assert router.plan(DAY)["exercises"][1]["weight_kg"] == 42
    stored = nov17.plan_session(DAY)["exercises"][1]
    assert stored["weight_kg"] == 42 and stored["weight_note"].startswith("up from")
    # a weight he sets before his first set stays
    stored_session = nov17.plan_session(DAY)
    stored_session["exercises"][1]["weight_kg"] = 38
    nov17.add_plan_session(DAY, "home", "strength", "approved", stored_session["exercises"])
    assert router.plan(DAY)["exercises"][1]["weight_kg"] == 38


def test_a_started_session_is_left_alone(store):
    did(store, LAST, "home", [("Lat pulldown", "lat pulldown", [(35, 12), (35, 12)])])
    store.add_plan_session(DAY, "home", "strength", "approved",
                           [ex("Lat pulldown", 25, "lat pulldown")])
    reports.log_report(store, DAY, [{"exercise": "Lat pulldown", "weight_kg": 30, "reps": 10}])
    assert weights.session(store, DAY, DAY)["exercises"][0]["weight_kg"] == 25


def test_a_past_day_is_left_alone(nov17):
    assert weights.session(nov17, DAY, "2026-11-25")["exercises"][1]["weight_kg"] == 25


# (4) the week proposal uses the same function

def test_a_new_proposal_and_the_days_list_agree(nov17):
    nov17.delete_plan_session(DAY)
    plan = [ex("Lat pulldown", 30, "Lat pulldown"), ex("Chest press", 99, "Chest press"),
            ex("Leg extension", 20, "Leg extension")]
    sessions = [{"date": d, "kind": "strength", "exercises": plan}
                for d in ("2026-11-24", "2026-11-26")]
    sessions.append({"date": "2026-11-29", "kind": "strength",
                     "exercises": [ex("Seated leg press", 40, "Seated leg press")]})
    sessions.append({"date": "2026-11-23", "kind": "cardio", "exercises": []})
    fake = FakeClaude([json.dumps({"message": "Here is your week.", "sessions": sessions})])
    msg = propose(Claude(fake, nov17, 5.0), nov17, MODEL, date(2026, 11, 23),
                  profile_path=PROFILE, equipment_path=EQ)
    stored = nov17.plan_session(DAY)["exercises"]
    assert [e["weight_kg"] for e in stored] == [42, 35, 20]  # the model's 30 and 99 overruled
    assert "Lat pulldown: 42 kg (up from 35 kg x 12, 12, 12 on 17 Nov)" in msg
    shown = router_for(nov17).plan(DAY)["exercises"]
    assert [e["weight_kg"] for e in shown] == [42, 35, 20]
    assert "at 42 kg" in list_message(router_for(nov17).plan(DAY))


# (5) stored sets are never changed

def test_stored_sets_stay_as_logged(nov17):
    before = nov17.logged_sets(LAST)
    router = router_for(nov17)
    router.handle("/today")
    router.context(DAY)
    weights.session(nov17, "2026-11-26", DAY)
    assert nov17.logged_sets(LAST) == before
