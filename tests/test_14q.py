"""Task 14q: a shared running-app (Strava) summary picture is logged as the day's jog, with
pace; a second picture of the same run updates it; the jog reminder has an "Open Strava"
button. Made-up data."""

import json
from datetime import datetime

import pytest

from fakes import tool_use
from gym_coach import reports
from gym_coach.coach import SYSTEM
from gym_coach.llm import HK
from gym_coach.meals import ESTIMATE_SYSTEM
from gym_coach.scheduler import STRAVA_BUTTON, Scheduler
from gym_coach.store import Store
from test_coach import make, prompt, results

WED = datetime(2026, 11, 25, 19, 0, tzinfo=HK)
DAY = "2026-11-25"
TUE = datetime(2026, 11, 24, 19, 0, tzinfo=HK)
STRENGTH_DAY = "2026-11-24"
JPEG = b"\xff\xd8not really a jpeg"
EX = {"name": "Press", "equipment": "Chest press", "sets": 3, "rep_low": 8, "rep_high": 12,
      "weight_kg": 20}
RUN = {"activity": "run", "minutes": 31.8, "distance_km": 5.12}


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    s.add_plan_session(DAY, "home", "cardio", "approved", [])
    s.add_plan_session(STRENGTH_DAY, "home", "strength", "approved", [EX])
    s.set("chat_id", "5")
    yield s
    s.close()


@pytest.fixture
def equipment(tmp_path):
    path = tmp_path / "equipment.md"
    path.write_text("# Equipment\n\n## Home gym (weekdays)\n- Chest press: seen\n", "utf-8")
    return path


# pace from distance and minutes

@pytest.mark.parametrize("minutes,km,text", [(31.8, 5.12, "6:13 /km"), (30, 5, "6:00 /km"),
                                             (25.5, 5, "5:06 /km"), (59.99, 10, "6:00 /km")])
def test_pace_from_minutes_and_distance(minutes, km, text):
    assert reports.pace_text(minutes, km) == text


def test_no_pace_without_distance():
    assert reports.pace_text(30, None) is None and reports.pace_text(30, 0) is None


def test_cardio_text_shows_moving_time_and_pace():
    row = {"activity": "run", "minutes": 31.8, "distance_km": 5.12, "avg_hr": 131}
    assert reports.cardio_text(row) == "run 31:48 min, 5.12 km, 6:13 /km, avg 131 bpm"
    assert reports.cardio_text({"activity": "jog", "minutes": 53, "distance_km": None,
                                "avg_hr": None}) == "jog 53 min"


def test_day_summary_shows_pace(store):
    store.add_cardio(DAY, "run", 31.8, 5.12)
    assert reports.format_log(store, DAY) == "Logged:\nCardio: run 31:48 min, 5.12 km, 6:13 /km"


# a caption-less run picture goes to the run path; a meal picture still to meals

def test_estimate_prompt_knows_running_app_pictures():
    assert '"run": true' in ESTIMATE_SYSTEM and "Strava" in ESTIMATE_SYSTEM


def test_caption_less_run_picture_is_logged_as_the_jog(store, equipment):
    router, fake = make(store, equipment, [
        json.dumps({"meal": False, "run": True, "what": "a Strava run summary"}),
        [tool_use("log_cardio", RUN)], "Nice run."], clock=WED)
    reply = router.handle_photo(JPEG, None)
    assert reply == "Nice run."
    assert store.meals_on(DAY) == []
    rows = store.cardio_on(DAY)
    assert [(r["minutes"], r["distance_km"]) for r in rows] == [(31.8, 5.12)]
    assert store.plan_session(DAY)["status"] == "done"
    # the coach call got the image and was told it is a running-app summary
    assert "running-app" in prompt(fake.calls[1]) and fake.calls[1]["tools"]
    assert "6:13 /km" in results(fake.calls[2])[0]["content"]


def test_caption_less_meal_picture_still_goes_to_meals(store, equipment):
    router, fake = make(store, equipment, [json.dumps(
        {"meal": True, "what": "rice", "description": "rice", "kcal": 600, "protein_g": 30})],
        clock=WED)
    reply = router.handle_photo(JPEG, None)
    assert reply.startswith("About 600 kcal") and len(fake.calls) == 1
    assert len(store.meals_on(DAY)) == 1 and store.cardio_on(DAY) == []


def test_coach_prompt_reads_moving_time_from_run_pictures():
    low = SYSTEM.lower()
    assert "moving time" in low and "running-app" in low


# a second picture of the same run updates instead of duplicating

def test_second_picture_of_the_same_run_updates(store, equipment):
    store.add_cardio(DAY, "run", 31.8, 5.12)
    router, fake = make(store, equipment, [
        [tool_use("log_cardio", {"activity": "run", "minutes": 31.8, "distance_km": 5.1,
                                 "avg_hr": 131})], "Same run, heart rate added."], clock=WED)
    router.handle_photo(JPEG, "today's jog")
    rows = store.cardio_on(DAY)
    assert len(rows) == 1
    assert (rows[0]["minutes"], rows[0]["distance_km"], rows[0]["avg_hr"]) == (31.8, 5.1, 131)
    assert "same run" in results(fake.calls[1])[0]["content"].lower()


def test_a_different_run_the_same_day_is_a_new_entry(store, equipment):
    store.add_cardio(DAY, "run", 31.8, 5.12)
    router, _ = make(store, equipment, [
        [tool_use("log_cardio", {"activity": "run", "minutes": 15, "distance_km": 2.4})],
        "Second run saved."], clock=WED)
    router.handle("did another 15 min, 2.4 km")
    assert len(store.cardio_on(DAY)) == 2


# a jog on a strength day does not close the strength session

def test_jog_on_a_strength_day_leaves_the_session_open(store, equipment):
    router, _ = make(store, equipment, [[tool_use("log_cardio", RUN)], "Saved."], clock=TUE)
    router.handle_photo(JPEG, "today's jog")
    assert len(store.cardio_on(STRENGTH_DAY)) == 1
    assert store.plan_session(STRENGTH_DAY)["status"] == "approved"


def test_strength_day_with_sets_is_still_closed(store):
    store.add_cardio(STRENGTH_DAY, "run", 30)
    assert reports.mark_done(store, STRENGTH_DAY) is False
    store.add_logged_set(STRENGTH_DAY, "Press", 1, 20, 10)
    assert reports.mark_done(store, STRENGTH_DAY) is True


# the jog reminder carries an "Open Strava" button

def test_jog_reminder_has_the_strava_button(store):
    sent = []
    Scheduler(store, lambda t: sent.append((t, None)),
              now=lambda: datetime(2026, 11, 25, 7, 0, tzinfo=HK),
              send_button=lambda t, m: sent.append((t, m))).tick()
    assert len(sent) == 1 and "Jog today" in sent[0][0]
    assert sent[0][1] == STRAVA_BUTTON
    button = STRAVA_BUTTON["inline_keyboard"][0][0]
    assert button["text"] == "Open Strava"
    assert button["url"] == "https://www.strava.com/dashboard"


def test_strength_reminder_has_no_strava_button(store):
    sent = []
    Scheduler(store, lambda t: sent.append((t, None)),
              now=lambda: datetime(2026, 11, 24, 7, 0, tzinfo=HK),
              send_button=lambda t, m: sent.append((t, m))).tick()
    assert sent and all(m is None for _, m in sent)


def test_app_sends_the_button_with_the_reminder(tmp_path):
    from fakes import FakeTelegram
    from gym_coach.app import App

    s = Store(tmp_path / "a.db")
    s.set("chat_id", "5")
    telegram = FakeTelegram()
    app = App(telegram, router=None, store=s, chat_id=5)
    app.send_to_owner("Jog today", reply_markup=STRAVA_BUTTON)
    assert telegram.sent == [(5, "Jog today")] and telegram.markups == [STRAVA_BUTTON]
    s.close()


# the moving time as shown on the picture, read by the code (no rounding by the model)

@pytest.mark.parametrize("shown,minutes,text", [("26:07", 26 + 7 / 60, "26:07 min"),
                                                ("1:02:15", 62.25, "62:15 min")])
def test_moving_time_as_shown_is_saved_to_the_second(store, equipment, shown, minutes, text):
    call = tool_use("log_cardio", {"activity": "run", "moving_time": shown, "distance_km": 4.03})
    router, fake = make(store, equipment, [[call], "Saved."], clock=WED)
    router.handle_photo(JPEG, "today's jog")
    row = store.cardio_on(DAY)[0]
    assert row["minutes"] == pytest.approx(minutes)
    assert text in results(fake.calls[1])[0]["content"]


@pytest.mark.parametrize("bad", ["31.48", "31:75", "abc", "0:00"])
def test_bad_moving_time_is_refused(store, equipment, bad):
    call = tool_use("log_cardio", {"activity": "run", "moving_time": bad})
    router, fake = make(store, equipment, [[call], "Which time?"], clock=WED)
    router.handle_photo(JPEG, "today's jog")
    assert store.cardio_on(DAY) == []
    assert results(fake.calls[1])[0]["is_error"] is True


def test_run_on_a_strength_day_says_the_session_stays_open(store, equipment):
    router, fake = make(store, equipment, [[tool_use("log_cardio", RUN)], "Saved."], clock=TUE)
    router.handle_photo(JPEG, "jog")
    assert "stays open" in results(fake.calls[1])[0]["content"]
