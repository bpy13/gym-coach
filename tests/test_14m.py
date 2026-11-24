"""Task 14m: read the trend across his sets (struggling, steady, too easy) and recommend the
weight by it. The three examples are the ones the plan quotes from his log; the rest is made
up."""

import json
from datetime import date, datetime

import pytest

from fakes import FakeClaude
from gym_coach import reports, weights
from gym_coach.albums import exercise_parts
from gym_coach.llm import HK, Claude
from gym_coach.planner import propose
from gym_coach.router import Router
from gym_coach.store import Store
from test_14l import CABLE, EQ, MODEL, PROFILE, RACK, did, ex

DAY = "2026-11-24"  # Tuesday, home
NOW = datetime(2026, 11, 24, 7, 30, tzinfo=HK)


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def sets(*pairs):
    return [{"weight_kg": w, "reps": r} for w, r in pairs]


def weight(store, exercise, gym="home", day=DAY):
    return weights.History(store, day).weight_for(exercise, gym)


def router_for(store):
    return Router(store, Claude(FakeClaude([]), store, 5.0, now=lambda: NOW),
                  "claude-haiku-5-5", MODEL, now=lambda: NOW, profile_path=PROFILE,
                  equipment_path=EQ)


# (1) the label, from the three examples

def test_lying_leg_curl_reps_falling_is_struggling():
    label, why, at = weights.read_sets(sets((21, 15), (21, 12), (21, 10)), (10, 15))
    assert (label, why, at) == ("struggling", "reps fell", 21)


def test_machine_chest_fly_raised_and_still_at_the_top_is_too_easy():
    label, _, _ = weights.read_sets(sets((21, 15), (28, 15), (35, 15)), (10, 15))
    assert label == "too easy"
    assert weights.read_sets(sets((21, 15), (28, 15), (35, 15)), (8, 12))[0] == "too easy"


def test_dumbbell_bench_lowered_weight_is_struggling():
    label, why, at = weights.read_sets(sets((12, 12), (10, 15), (10, 15)), (8, 12))
    assert (label, why, at) == ("struggling", "you lowered the weight", 12)


def test_last_set_at_the_top_weight_reaching_the_top_wins_over_a_fall():
    # 17 Nov lying leg curl (made-up range 8-12): 21 x 15, 12, then 28 x 12
    assert weights.read_sets(sets((21, 15), (21, 12), (28, 12)), (8, 12))[0] == "too easy"
    assert weights.read_sets(sets((21, 15), (21, 12), (21, 12)), (8, 12))[0] == "too easy"
    # the last set under the top, or not at the top weight: struggling as before
    assert weights.read_sets(sets((12.5, 15), (12.5, 12), (12.5, 10)), (8, 12))[0] == "struggling"
    assert weights.read_sets(sets((12, 12), (10, 15)), (8, 12))[0] == "struggling"


def test_the_other_rules():
    assert weights.read_sets(sets((30, 12), (30, 11), (30, 10)), (8, 12))[0] == "steady"  # 2
    assert weights.read_sets(sets((30, 10), (30, 7)), (8, 12))[:2] == ("struggling",
                                                                    "reps fell")
    assert weights.read_sets(sets((30, 9), (30, 7)), (8, 12))[:2] == ("struggling",
                                                                   "a set under 8 reps")
    assert weights.read_sets(sets((30, 12), (30, 12)), (8, 12))[0] == "too easy"
    assert weights.read_sets(sets((20, 10), (25, 10)), (8, 12))[0] == "steady"  # raised, mid
    assert weights.read_sets(sets((30, 10), (30, 10)), None)[0] == "steady"


# (2) the recommendation follows the label

def test_too_easy_goes_one_step_up_from_the_last_top(store):
    did(store, "2026-11-22", "parents", [("Machine chest fly", "chest fly",
                                          [(21, 15), (28, 15), (35, 15)])])
    got = weight(store, ex("Machine chest fly", 21, "chest fly"), gym="parents")
    assert got["label"] == "too easy" and got["weight_kg"] == 42
    assert got["note"] == "last time 35 kg felt easy: 21 kg x 15; 28 kg x 15; 35 kg x 15 on 22 Nov"


def test_struggling_stays_at_the_weight_where_reps_fell(store):
    did(store, "2026-11-22", "parents", [("Lying leg curl", "lying leg curl",
                                          [(21, 15), (21, 12), (21, 10)])])
    got = weight(store, ex("Lying leg curl", 28, "lying leg curl"), gym="parents")
    assert got["label"] == "struggling" and got["weight_kg"] == 21
    assert got["note"] == "again, reps fell last time: 21 kg x 15, 12, 10 on 22 Nov"


def test_lowered_weight_stays_at_the_weight_he_lowered_from(store):
    did(store, "2026-11-19", "home", [("Dumbbell bench press", RACK,
                                       [(12, 12), (10, 15), (10, 15)])])
    got = weight(store, ex("Dumbbell bench press", 14, RACK))
    assert got["weight_kg"] == 12
    assert got["note"].startswith("again, you lowered the weight last time: ")


def test_struggling_twice_at_the_same_weight_goes_one_step_under(store):
    did(store, "2026-11-12", "home", [("Lat pulldown", "lat pulldown", [(35, 12), (35, 8)])])
    did(store, "2026-11-17", "home", [("Lat pulldown", "lat pulldown", [(35, 12), (35, 9)])])
    did(store, "2026-11-10", "home", [("Machine chest press", "chest press",
                                       [(21, 10), (28, 10)])])  # the home machine step: 7
    got = weight(store, ex("Lat pulldown", 30, "lat pulldown"))
    assert got["weight_kg"] == 28
    assert got["note"].startswith("one step down, reps fell twice in a row: ")


def test_steady_keeps_the_top_and_aims_for_one_more_rep(store):
    did(store, "2026-11-17", "home", [("Lat pulldown", "lat pulldown",
                                       [(35, 10), (35, 10), (35, 9)])])
    got = weight(store, ex("Lat pulldown", 25, "lat pulldown"))
    assert got == {"weight_kg": 35, "label": "steady",
                   "note": "again, aim for one more rep: 35 kg x 10, 10, 9 on 17 Nov"}


def test_list_card_and_proposal_show_the_weight_with_its_reason(store):
    did(store, "2026-11-17", "home", [
        ("Lat pulldown", "lat pulldown", [(35, 15), (35, 15), (35, 15)]),
        ("Seated cable row", CABLE, [(25, 15), (25, 12), (25, 10)]),
    ])
    store.add_plan_session(DAY, "home", "strength", "approved", [
        ex("Lat pulldown", 25, "lat pulldown"), ex("Seated cable row", 20, CABLE)])
    router = router_for(store)
    today = router.handle("/today")
    assert ("Lat pulldown: 3 x 8-12 at 37.5 kg (last time 35 kg felt easy: "
            "35 kg x 15, 15, 15 on 17 Nov)") in today
    assert ("Seated cable row: 3 x 8-12 at 25 kg (again, reps fell last time: "
            "25 kg x 15, 12, 10 on 17 Nov)") in today
    caption, _ = exercise_parts(router.plan(DAY), 1, equipment_path=EQ, photos_dir="no-photos")
    assert caption.startswith("Seated cable row: 3 x 8-12 at 25 kg (again, reps fell")
    ctx = router.context(DAY)
    assert ("(plan 8-12 reps at 25 kg, again, reps fell last time) | last: 17 Nov, 3 sets: "
            "set 1 25 kg x 15") in ctx

    store.delete_plan_session(DAY)
    plan = [ex("Lat pulldown", 30, "Lat pulldown"), ex("Seated cable row", 99, "Dual adjustable cable machine")]
    week = {"message": "Here is your week.",
            "sessions": [{"date": d, "kind": "strength", "exercises": plan}
                         for d in (DAY, "2026-11-26")]
            + [{"date": "2026-11-29", "kind": "strength",
                "exercises": [ex("Seated leg press", 40, "Seated leg press")]},
               {"date": "2026-11-23", "kind": "cardio", "exercises": []}]}
    msg = propose(Claude(FakeClaude([json.dumps(week)]), store, 5.0), store, MODEL,
                  date(2026, 11, 23), profile_path=PROFILE, equipment_path=EQ)
    assert "Lat pulldown: 37.5 kg (last time 35 kg felt easy: 35 kg x 15, 15, 15" in msg
    assert "Seated cable row: 25 kg (again, reps fell last time" in msg
    assert [e["weight_kg"] for e in store.plan_session(DAY)["exercises"]] == [37.5, 25]


# (3) during the workout the coach sees today's sets read the same way

def test_coach_context_labels_todays_sets_as_they_come_in(store):
    store.add_plan_session(DAY, "home", "strength", "approved", [
        ex("Lying leg curl", 21, "lying leg curl", low=10, high=15),
        ex("Machine chest fly", 21, "chest fly", low=10, high=15),
        ex("Leg extension", 28, "leg extension")])
    store.set(f"flow:{DAY}", "0")
    router = router_for(store)
    for name, rows in (("Lying leg curl", [(21, 15), (21, 12), (21, 10)]),
                       ("Machine chest fly", [(21, 15), (28, 15)]),
                       ("Leg extension", [(28, 10)])):
        reports.log_report(store, DAY, [{"exercise": name, "weight_kg": w, "reps": r}
                                        for w, r in rows])
    ctx = router.context(DAY)
    assert ("today so far: struggling (reps fell): hold, or drop one step, for the next set"
            in ctx)
    assert "today so far: too easy: go up one step for the next set" in ctx
    assert "today so far: steady: hold the weight" in ctx


# (4) stored sets are never changed

def test_stored_sets_stay_as_logged(store):
    did(store, "2026-11-17", "home", [("Lat pulldown", "lat pulldown", [(35, 12), (35, 8)])])
    store.add_plan_session(DAY, "home", "strength", "approved",
                           [ex("Lat pulldown", 25, "lat pulldown")])
    before = store.logged_sets("2026-11-17")
    router = router_for(store)
    router.handle("/today")
    router.context(DAY)
    assert store.logged_sets("2026-11-17") == before
