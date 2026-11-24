"""Task 14o: each exercise shows what he did last time, every set; no suggested weight, no
target reps, no "up from" or "aim for" unless he asks. Made-up data in the shape of the
24 Nov case the plan quotes."""

import json
import re
from datetime import datetime

import pytest

from fakes import FakeClaude
from gym_coach import coach, reports, weights
from gym_coach.albums import exercise_parts
from gym_coach.llm import HK, Claude
from gym_coach.prompts import PLAN_SYSTEM
from gym_coach.router import Router
from gym_coach.scheduler import Scheduler
from gym_coach.store import Store

MODEL = "claude-opus-5-5"
EQ = "examples/equipment.md"
PROFILE = "examples/profile.md"
CABLE = "dual adjustable cable machine"
LAST = "2026-11-17"  # Tuesday, home
DAY = "2026-11-24"  # Tuesday, home
NOW = datetime(2026, 11, 24, 7, 30, tzinfo=HK)
SUGGESTING = ("up from", "aim", "go up", "felt easy", "one more rep")
NOV17 = {  # name in the log, equipment, sets
    "Machine chest press": ("chest press", [(21, 15), (28, 12), (28, 15)]),
    "Lat pulldown": ("lat pulldown", [(35, 12), (35, 12), (35, 12)]),
    "Seated cable row": (CABLE, [(20, 15), (22.5, 15), (25, 15)]),
}


def ex(name, weight, equipment, low=8, high=12):
    return {"name": name, "equipment": equipment, "sets": 3, "rep_low": low,
            "rep_high": high, "weight_kg": weight}


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def did(store, day, gym, rows):
    store.add_plan_session(day, gym, "strength", "done",
                           [ex(n, sets[0][0], gear) for n, (gear, sets) in rows.items()])
    for name, (_, sets) in rows.items():
        for kg, reps in sets:
            reports.log_report(store, day, [{"exercise": name, "weight_kg": kg, "reps": reps}])


@pytest.fixture
def nov24(store):
    did(store, LAST, "home", NOV17)
    store.add_plan_session(DAY, "home", "strength", "approved", [
        ex("Chest press", 20, "chest press"),
        ex("Lat pulldown", 25, "lat pulldown"),
        ex("Seated cable row", 20, CABLE),
        ex("Leg extension", 20, "leg extension"),  # never logged
    ])
    return store


def router_for(store, replies=()):
    return Router(store, Claude(FakeClaude(list(replies)), store, 5.0, now=lambda: NOW),
                  "claude-haiku-5-5", MODEL, now=lambda: NOW, profile_path=PROFILE,
                  equipment_path=EQ)


RECORD = {float(kg) for _, sets in NOV17.values() for kg, _ in sets}


def assert_shows_only_the_record(text):
    low = text.lower()
    for word in SUGGESTING:
        assert word not in low, (word, text)
    assert not re.search(r" at \d", text), text  # "at 42 kg"
    shown = {float(w) for w in re.findall(r"(\d+(?:\.\d+)?) kg", text)}
    assert shown <= RECORD, shown - RECORD


# (1) list, card and morning list: last time's sets, every set, nothing suggested

def test_the_24_nov_list_shows_last_times_sets_and_nothing_else(nov24):
    today = router_for(nov24).handle("/today")
    assert ("Chest press: 3 x 8-12 (last time, 17 Nov: 21 kg x 15, 28 kg x 12, 28 kg x 15)"
            in today)
    assert ("Lat pulldown: 3 x 8-12 (last time, 17 Nov: 35 kg x 12, 35 kg x 12, 35 kg x 12)"
            in today)
    assert ("Seated cable row: 3 x 8-12 (last time, 17 Nov: 20 kg x 15, 22.5 kg x 15, "
            "25 kg x 15)") in today
    assert_shows_only_the_record(today)


def test_the_card_and_the_morning_list_show_it_too(nov24):
    router = router_for(nov24)
    caption, _ = exercise_parts(router.plan(DAY), 1, equipment_path=EQ, photos_dir="no-photos")
    assert caption.startswith(
        "Lat pulldown: 3 x 8-12 (last time, 17 Nov: 35 kg x 12, 35 kg x 12, 35 kg x 12)")
    assert_shows_only_the_record(caption)
    sent = []
    Scheduler(nov24, sent.append, now=lambda: NOW).tick()
    assert "Chest press: 3 x 8-12 (last time, 17 Nov: 21 kg x 15, 28 kg x 12, 28 kg x 15)" \
        in sent[0]
    assert_shows_only_the_record(sent[0])


def test_the_card_still_shows_last_time_once_he_started(nov24):
    reports.log_report(nov24, DAY, [{"exercise": "Chest press", "weight_kg": 28, "reps": 12}])
    caption, _ = exercise_parts(router_for(nov24).plan(DAY), 1, equipment_path=EQ,
                                photos_dir="no-photos")
    assert "(last time, 17 Nov: 35 kg x 12, 35 kg x 12, 35 kg x 12)" in caption


def test_his_effort_word_shows_with_the_set(store):
    did(store, LAST, "home", {"Lat pulldown": ("lat pulldown", [(35, 12), (42, 8)])})
    store.set_effort(store.logged_sets(LAST)[1]["id"], "barely")
    store.add_plan_session(DAY, "home", "strength", "approved",
                           [ex("Lat pulldown", 25, "lat pulldown")])
    assert ("(last time, 17 Nov: 35 kg x 12, 42 kg x 8 (barely))"
            in router_for(store).handle("/today"))


def test_a_machine_done_only_at_the_other_gym_names_that_gym(store):
    did(store, "2026-11-22", "parents", {"Lat pulldown": ("lat pulldown", [(30, 10)])})
    store.add_plan_session(DAY, "home", "strength", "approved",
                           [ex("Lat pulldown", 25, "lat pulldown")])
    assert ("Lat pulldown: 3 x 8-12 (last time (parents gym), 22 Nov: 30 kg x 10)"
            in router_for(store).handle("/today"))


# (2) no history: "no earlier record"; sets and rep range stay

def test_no_history_shows_no_earlier_record(nov24):
    today = router_for(nov24).handle("/today")
    assert "Leg extension: 3 x 8-12 (no earlier record)" in today.splitlines()


# (3) the labels and the weight stay for when he asks, marked so

def test_the_coach_sees_last_time_and_the_advice_only_for_when_he_asks(nov24):
    router = router_for(nov24)
    ctx = router.context(DAY)
    assert ("- Lat pulldown: 0 of 3 sets logged (plan 8-12 reps) | if he asks what to lift: "
            "42 kg, last time 35 kg felt easy | last: 17 Nov, 3 sets:") in ctx
    assert "- Leg extension: 0 of 3 sets logged (plan 8-12 reps) | last: no earlier record" \
        in ctx
    assert "reps at" not in ctx
    nov24.set(f"flow:{DAY}", "0")
    reports.log_report(nov24, DAY, [{"exercise": "Chest press", "weight_kg": 28, "reps": w}
                                    for w in (12, 10, 8)])
    ctx = router.context(DAY)
    assert "| if he asks for advice, today so far: struggling (reps fell)" in ctx


def test_the_weight_function_still_works(nov24):
    got = weights.History(nov24, DAY).weight_for(ex("Lat pulldown", 25, "lat pulldown"), "home")
    assert got["weight_kg"] == 42 and got["label"] == weights.TOO_EASY


def test_last_time_is_never_stored(nov24):
    router = router_for(nov24)
    router.plan(DAY)
    assert all("last_time" not in e for e in nov24.plan_session(DAY)["exercises"])


# (4) the week proposal: last time's sets, no weight lines

def test_the_week_proposal_lists_last_times_sets_without_weights(nov24):
    plan = [ex("Lat pulldown", 30, "Lat pulldown"), ex("Leg extension", 20, "Leg extension")]
    week = {"message": "Here is your week. How hard did each set feel? General fitness "
                       "guidance, not medical advice.",
            "sessions": [{"date": d, "kind": "strength", "exercises": plan}
                         for d in ("2026-12-01", "2026-12-03")]
            + [{"date": "2026-12-06", "kind": "strength",
                "exercises": [ex("Seated leg press", 40, "Seated leg press")]},
               {"date": "2026-11-30", "kind": "cardio", "exercises": []}]}
    msg = router_for(nov24, [json.dumps(week)])._propose()
    assert ("Lat pulldown: 3 x 8-12 (last time, 17 Nov: 35 kg x 12, 35 kg x 12, 35 kg x 12)"
            in msg)
    assert "Leg extension: 3 x 8-12 (no earlier record)" in msg
    assert "Weights from what you last lifted" not in msg
    assert_shows_only_the_record(msg)


# (5) the coach's system text says it plainly

def test_the_system_texts_say_it():
    assert "Nothing more" in coach.SYSTEM
    assert "unless he asks for advice" in coach.SYSTEM
    assert "Never offer these unasked" in coach.SYSTEM
    assert "say briefly whether to go up" not in coach.SYSTEM
    assert "names no weight and no rep count" in PLAN_SYSTEM


def test_a_fixed_effort_word_returns_the_reading_only_for_advice(store):
    store.add_plan_session(DAY, "home", "strength", "approved",
                           [ex("Lat pulldown", 25, "lat pulldown")])
    store.set(f"flow:{DAY}", "0")
    reports.log_report(store, DAY, [{"exercise": "Lat pulldown", "weight_kg": 35, "reps": 12}])
    c = coach.Coach(router_for(store), DAY)
    out = c.t_fix_set({"exercise": "Lat pulldown", "set_no": 1, "effort": "barely"})
    assert "If he asks for advice, it reads as" in out
