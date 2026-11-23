"""Cardio logging: the log_cardio tool saves the activity, minutes, distance and heart rate,
marks the day done, and the summary and the coach context show it. Made-up data."""

from datetime import datetime

import pytest

from fakes import tool_use
from gym_coach import reports
from gym_coach.coach import TOOLS
from gym_coach.llm import HK
from gym_coach.store import Store
from test_coach import make, results

MON = datetime(2026, 11, 30, 19, 0, tzinfo=HK)
DAY = "2026-11-30"


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    s.add_plan_session(DAY, "home", "cardio", "approved", [])
    s.set("chat_id", "5")
    yield s
    s.close()


@pytest.fixture
def equipment(tmp_path):
    path = tmp_path / "equipment.md"
    path.write_text("# Equipment\n\n## Home gym (weekdays)\n- Treadmill: seen\n", "utf-8")
    return path


def test_log_cardio_is_a_tool():
    assert "log_cardio" in {t["name"] for t in TOOLS}


def test_log_cardio_saves_and_marks_the_day_done(store, equipment):
    call = tool_use("log_cardio", {"activity": "jogging", "minutes": 53, "distance_km": 7.2,
                                   "avg_hr": 131})
    router, fake = make(store, equipment, [[call], "Nice steady jog."], clock=MON)
    reply = router.handle("53 min jog, 7.2 km, avg 131")
    assert reply == "Nice steady jog."
    rows = store.cardio_on(DAY)
    assert [(r["activity"], r["minutes"], r["distance_km"], r["avg_hr"]) for r in rows] == [
        ("jogging", 53, 7.2, 131)]
    assert rows[0]["saved_at"].startswith(DAY)
    assert store.plan_session(DAY)["status"] == "done"
    assert "Saved cardio: jogging 53 min, 7.2 km, avg 131 bpm." in results(
        fake.calls[1])[0]["content"]


def test_log_cardio_without_distance_or_heart_rate(store, equipment):
    call = tool_use("log_cardio", {"activity": "jogging", "minutes": 30})
    router, _ = make(store, equipment, [[call], "Done."], clock=MON)
    router.handle("30 min jog")
    assert reports.format_log(store, DAY) == "Logged:\nCardio: jogging 30 min"


@pytest.mark.parametrize("data", [{"activity": "jogging", "minutes": 0},
                                  {"activity": "", "minutes": 20},
                                  {"activity": "jogging", "minutes": 20, "avg_hr": -5}])
def test_bad_cardio_is_refused_and_nothing_saved(store, equipment, data):
    router, fake = make(store, equipment, [[tool_use("log_cardio", data)], "How long?"],
                        clock=MON)
    router.handle("jogged")
    assert store.cardio_on(DAY) == []
    assert store.plan_session(DAY)["status"] == "approved"
    assert results(fake.calls[1])[0]["is_error"] is True


def test_finish_after_cardio_shows_it_in_the_summary(store, equipment):
    store.add_cardio(DAY, "jogging", 45)
    router, _ = make(store, equipment, [[tool_use("finish_workout", {})], "Well done."],
                     clock=MON)
    reply = router.handle("done")
    assert "Workout finished. Summary:\nCardio: jogging 45 min" in reply
    assert store.plan_session(DAY)["status"] == "done"


def test_the_coach_sees_todays_cardio(store, equipment):
    store.add_cardio(DAY, "cycling", 40, avg_hr=128)
    router, _ = make(store, equipment, [], clock=MON)
    assert "Cardio: cycling 40 min, avg 128 bpm" in router.context(DAY)


def test_evening_check_closes_a_cardio_day(store):
    store.add_cardio(DAY, "jogging", 20)
    assert reports.mark_done(store, DAY) is True
    assert store.plan_session(DAY)["status"] == "done"


def test_fix_cardio_adds_the_distance_to_the_saved_entry(store, equipment):
    store.add_cardio(DAY, "jogging", 53)
    call = tool_use("fix_cardio", {"distance_km": 6.5})
    router, fake = make(store, equipment, [[call], "6.5 km added."], clock=MON)
    router.handle("about 6.5 km")
    rows = store.cardio_on(DAY)
    assert [(r["minutes"], r["distance_km"], r["avg_hr"]) for r in rows] == [(53, 6.5, None)]
    assert "Cardio now: jogging 53 min, 6.5 km." in results(fake.calls[1])[0]["content"]


def test_fix_cardio_changes_only_the_last_entry(store, equipment):
    store.add_cardio(DAY, "jogging", 20, avg_hr=125)
    store.add_cardio(DAY, "cycling", 30, avg_hr=120)
    router, _ = make(store, equipment, [[tool_use("fix_cardio", {"minutes": 35})], "Ok."],
                     clock=MON)
    router.handle("cycling was 35 min")
    assert [(r["activity"], r["minutes"], r["avg_hr"]) for r in store.cardio_on(DAY)] == [
        ("jogging", 20, 125), ("cycling", 35, 120)]


@pytest.mark.parametrize("data, saved", [({"distance_km": 5}, False), ({}, True),
                                         ({"minutes": -1}, True)])
def test_fix_cardio_is_refused_without_an_entry_or_numbers(store, equipment, data, saved):
    if saved:
        store.add_cardio(DAY, "jogging", 30)
    router, fake = make(store, equipment, [[tool_use("fix_cardio", data)], "Hm."], clock=MON)
    router.handle("fix it")
    assert results(fake.calls[1])[0]["is_error"] is True
    assert [r["minutes"] for r in store.cardio_on(DAY)] == ([30] if saved else [])
