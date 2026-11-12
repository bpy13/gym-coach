import pytest

from gym_coach import reports
from gym_coach.store import Store

DAY = "2026-11-17"


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def s(name, w, reps):
    return {"exercise": name, "weight_kg": w, "reps": reps}


def test_log_numbers_sets_and_marks_session_done(store):
    store.add_plan_session(DAY, "home", "strength", "approved", [])
    reports.log_report(store, DAY, [s("Chest press", 35, 10), s("Chest press", 35, 8)])
    assert [r["set_no"] for r in store.logged_sets(DAY)] == [1, 2]
    assert store.plan_session(DAY)["status"] == "done"
    assert reports.format_log(store, DAY) == "Logged:\nChest press: 35 kg x 10, 8"


def test_second_report_continues_set_numbers(store):
    reports.log_report(store, DAY, [s("Row", 30, 10)])
    reports.log_report(store, DAY, [s("row", 30, 9)])
    assert [r["set_no"] for r in store.logged_sets(DAY)] == [1, 2]


def test_malformed_sets_are_dropped(store):
    got = reports.log_report(store, DAY, [{"exercise": "Row"}, s("", 1, 1), s("Row", "x", 1)])
    assert got == [] and store.logged_sets(DAY) == []


def test_correct_replaces_only_named_exercise(store):
    reports.log_report(store, DAY, [s("Chest press", 35, 10), s("Lat pulldown", 40, 10)])
    reports.correct(store, DAY, [s("chest press", 30, 10)])
    rows = {r["exercise"]: r["weight_kg"] for r in store.logged_sets(DAY)}
    assert rows == {"Lat pulldown": 40, "chest press": 30}


def test_format_groups_weights_and_handles_empty(store):
    assert reports.format_log(store, DAY) == "Nothing logged yet today."
    reports.log_report(store, DAY, [s("Curl", 10, 12), s("Curl", 12, 8), s("Plank", None, 60)])
    assert reports.format_log(store, DAY) == "Logged:\nCurl: 10 kg x 12; 12 kg x 8\nPlank: x 60"
