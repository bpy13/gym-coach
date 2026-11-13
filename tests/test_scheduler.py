from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from gym_coach.scheduler import Scheduler
from gym_coach.store import Store

HK = ZoneInfo("Asia/Hong_Kong")
EXERCISES = [
    {"name": "Chest press machine", "equipment": "chest press machine", "sets": 3,
     "rep_low": 8, "rep_high": 12, "weight_kg": 30},
    {"name": "Lat pulldown", "equipment": "lat pulldown", "sets": 3,
     "rep_low": 8, "rep_high": 12, "weight_kg": 40},
]


class Clock:
    def __init__(self, y, m, d, hh, mm):
        self.t = datetime(y, m, d, hh, mm, tzinfo=HK)

    def __call__(self):
        return self.t


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def make(store, clock):
    sent = []
    return Scheduler(store, sent.append, now=clock), sent


def test_sends_once_at_seven_naming_gym_and_exercises(store):
    store.add_plan_session("2026-11-17", "home", "strength", "approved", EXERCISES)  # Tuesday
    clock = Clock(2026, 11, 17, 6, 59)
    sch, sent = make(store, clock)
    sch.tick()
    assert sent == []
    clock.t = clock.t.replace(hour=7, minute=0)
    sch.tick()
    sch.tick()
    clock.t = clock.t.replace(hour=7, minute=1)
    sch.tick()
    assert len(sent) == 1
    assert sent[0].splitlines()[0] == "Home gym, Tue 17 Nov"
    assert "Chest press machine: 3 x 8-12 at 30 kg" in sent[0]
    assert "Lat pulldown: 3 x 8-12 at 40 kg" in sent[0]


def test_start_at_3pm_same_day_sends_once(store):
    store.add_plan_session("2026-11-17", "home", "strength", "approved", EXERCISES)
    sch, sent = make(store, Clock(2026, 11, 17, 15, 0))
    sch.tick()
    sch.tick()
    assert len(sent) == 1


def test_next_day_does_not_send_yesterdays(store):
    store.add_plan_session("2026-11-17", "home", "strength", "approved", EXERCISES)
    sch, sent = make(store, Clock(2026, 11, 18, 9, 0))
    sch.tick()
    assert sent == []


def test_cardio_day_sends_cardio_line(store):
    store.add_plan_session("2026-11-18", "home", "cardio", "approved", [])
    sch, sent = make(store, Clock(2026, 11, 18, 7, 0))
    sch.tick()
    assert len(sent) == 1
    assert "Cardio" in sent[0] and "130" in sent[0]


def test_rest_day_sends_nothing(store):
    sch, sent = make(store, Clock(2026, 11, 19, 8, 0))
    sch.tick()
    assert sent == []


def test_parents_gym_heading(store):
    store.add_plan_session("2026-11-22", "parents", "strength", "approved", EXERCISES)  # Sunday
    sch, sent = make(store, Clock(2026, 11, 22, 7, 5))
    sch.tick()
    assert sent[0].splitlines()[0] == "Parents' gym, Sun 22 Nov"


@pytest.mark.parametrize("status", ["proposed", "skipped", "done"])
def test_only_approved_sessions_are_sent(store, status):
    store.add_plan_session("2026-11-17", "home", "strength", status, EXERCISES)
    sch, sent = make(store, Clock(2026, 11, 17, 7, 0))
    sch.tick()
    assert sent == []


def test_marker_survives_restart(store):
    store.add_plan_session("2026-11-17", "home", "strength", "approved", EXERCISES)
    make(store, Clock(2026, 11, 17, 7, 0))[0].tick()
    sch2, sent2 = make(store, Clock(2026, 11, 17, 12, 0))
    sch2.tick()
    assert sent2 == []


def test_tick_in_second_thread_sends_session(tmp_path):
    import threading

    store = Store(tmp_path / "thread.db")  # created in this (main) thread
    try:
        store.add_plan_session("2026-11-17", "home", "strength", "approved", EXERCISES)
        sch, sent = make(store, Clock(2026, 11, 17, 7, 0))
        errors = []

        def work():
            try:
                sch.tick()
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        t = threading.Thread(target=work)
        t.start()
        t.join()
        assert errors == []
        assert len(sent) == 1
    finally:
        store.close()
