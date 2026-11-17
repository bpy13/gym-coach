"""Task 14i: the whole workout in view. A workout opens and closes, every model call sees its
whole chat, traces name the current exercise, photos in a workout are never meals, weeks are
asked about only after this week's last session, "typing" repeats, and a missing-sets message
is checked against the chat. Made-up data only."""

import importlib.util
import json
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest

from fakes import FakeClaude
from gym_coach import app as app_module
from gym_coach import reports
from gym_coach.llm import HK
from gym_coach.router import CLASSIFY_SYSTEM
from gym_coach.scheduler import Scheduler
from gym_coach.store import Store
from test_14h import JPEG, ActionTelegram, change_plan, has_image, prompt_of
from test_session_fixes import DAY, EXS, build, report, say


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    s.add_plan_session(DAY, "home", "strength", "approved", EXS)
    s.set(f"flow:{DAY}", "0")
    s.set("chat_id", "5")
    yield s
    s.close()


def workout(store) -> str:
    return store.get(f"workout:{DAY}") or ""


def question(**extra):
    return json.dumps({"intent": "question", **extra})


# (1) a workout opens on "start" or when a message shows it has begun

def test_start_opens_the_workout_and_names_the_exercise(store):
    router, fake = build(store, [])[1:]
    reply = router.handle("start")
    assert workout(store).startswith("open|") and "Press" in reply
    assert fake.calls == []


def test_start_without_the_morning_message_starts_the_flow(store):
    store._run("DELETE FROM kv WHERE key=?", (f"flow:{DAY}",))
    router = build(store, [])[1]
    router.handle("start")  # the warm-up first (Task 14j), then the first exercise
    assert store.get(f"flow:{DAY}") == "0" and router.pop_exercise() is None
    router.handle("done")
    assert router.pop_exercise()[1] == 0


def test_a_set_opens_the_workout_by_itself(store):
    router = build(store, [report("Press", 10)])[1]
    router.handle("press 10")
    assert workout(store).startswith("open|")


def test_a_question_about_todays_exercise_opens_it(store):
    router = build(store, [question(workout=True), "Keep your back flat."])[1]
    router.handle("how do I do the pulldown?")
    assert workout(store).startswith("open|")


def test_an_unrelated_question_does_not_open_it(store):
    router = build(store, [question(), "Sleep 8 hours."])[1]
    router.handle("how much should I sleep?")
    assert workout(store) == ""


# (2) while it is open, every model call sees the whole workout chat

def test_open_workout_shows_every_chat_line_since_it_opened(store):
    store.add_chat("2026-11-17T09:00:00+08:00", "in", "before the workout")
    router, fake = build(store, [question(), "Fine."])[1:]
    router.handle("start")
    for i in range(20):
        store.add_chat("2026-11-17T17:00:00+08:00", "in", f"line {i}")
    router.handle("how is it going?")
    prompt = prompt_of(fake.calls[0])
    assert "line 0" in prompt and "line 19" in prompt and "before the workout" not in prompt
    assert "line 0" in prompt_of(fake.calls[1])  # the answer sees it too


def test_without_a_workout_only_the_last_12_lines(store):
    for i in range(20):
        store.add_chat("2026-11-17T09:00:00+08:00", "in", f"line {i:02d}")
    router, fake = build(store, [question(), "Fine."])[1:]
    router.handle("hello")
    prompt = prompt_of(fake.calls[0])
    assert "line 07" not in prompt and "line 08" in prompt and "line 19" in prompt


# (3) it closes when nothing is left, on "end", or at 21:00

def test_closes_when_no_exercise_has_sets_left(store):
    reports.log_report(store, DAY, [{"exercise": n, "weight_kg": 20, "reps": 10}
                                    for n in ("Press", "Pulldown", "Leg ext") for _ in (1, 2)]
                       + [{"exercise": "Shoulder", "weight_kg": 20, "reps": 10}])
    store.set(f"flow:{DAY}", "3")
    router = build(store, [report("Shoulder", 10)])[1]
    router.handle("start")
    assert "Session done" in router.handle("shoulder 10")
    # Task 14j: it stays open for stretching until "Finish session"
    assert workout(store).startswith("open|")
    router.handle("Finish session")
    assert workout(store).startswith("closed|")


def test_end_closes_it_with_the_summary(store):
    reports.log_report(store, DAY, [{"exercise": "Press", "weight_kg": 20, "reps": 10}])
    router, fake = build(store, [])[1:]
    router.handle("start")
    reply = router.handle("end")
    assert workout(store).startswith("closed|") and fake.calls == []
    assert "Press: 20 kg x 10" in reply and "Missing: Press (1 of 2)" in reply
    assert store.plan_session(DAY)["status"] == "done"


def test_the_2100_close_closes_an_open_workout(store):
    router = build(store, [])[1]
    router.handle("start")
    Scheduler(store, lambda t: None, now=lambda: datetime(2026, 11, 17, 21, 0, tzinfo=HK)).tick()
    assert workout(store).startswith("closed|")


def test_a_closed_workout_is_not_reopened_by_a_set(store):
    router = build(store, [report("Press", 10)])[1]
    router.handle("start")
    router.handle("end")
    router.handle("press 10")
    assert workout(store).startswith("closed|")


# (4) each trace names the current exercise after the message

def test_trace_records_the_current_exercise(store, tmp_path):
    app = build(store, [report("Pulldown", 10)])[0]
    say(app, "pulldown 10")
    [t] = store._rows("SELECT * FROM trace")
    assert t["exercise"] == "1: Pulldown"
    spec = importlib.util.spec_from_file_location(
        "show_chat", Path(__file__).resolve().parent.parent / "scripts" / "show_chat.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert "now shown: 1: Pulldown" in mod.render(tmp_path / "t.db", DAY)


def test_trace_table_gets_the_column_and_keeps_its_rows(tmp_path):
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE trace (id INTEGER PRIMARY KEY AUTOINCREMENT, chat_row INTEGER,"
               " timestamp TEXT NOT NULL, understood TEXT, calls TEXT NOT NULL DEFAULT '[]',"
               " seconds REAL, error TEXT)")
    db.execute("INSERT INTO trace (timestamp, understood) VALUES ('2026-11-17T10:00:00', 'kept')")
    db.commit()
    db.close()
    s = Store(path)
    [row] = s._rows("SELECT * FROM trace")
    assert row["understood"] == "kept" and row["exercise"] is None
    s.close()
    Store(path).close()


# (5) a photo in an open workout is never a meal

def test_photo_without_caption_in_a_workout_is_a_question(store):
    router, fake = build(store, ["That is a cable machine."])[1:]
    router.handle("start")
    reply = router.handle_photo(JPEG, None)
    assert reply == "That is a cable machine." and has_image(fake.calls[0])
    assert store.meals_on(DAY) == [] and "workout" in prompt_of(fake.calls[0]).lower()


def test_photo_with_a_meal_caption_in_a_workout_is_not_a_meal(store):
    router, fake = build(store, [json.dumps({"intent": "meal"}), "Looks like a plate."])[1:]
    router.handle("start")
    reply = router.handle_photo(JPEG, "this one")
    assert reply == "Looks like a plate." and store.meals_on(DAY) == []
    assert has_image(fake.calls[1])


# (6) the bot asks about next week only once this week's last session is done

def test_change_waits_while_a_later_session_this_week_is_planned(store):
    store.set_plan_status(DAY, "done")
    store.add_plan_session("2026-11-19", "home", "strength", "approved", EXS)
    store.add_plan_session("2026-11-24", "home", "strength", "proposed", EXS)
    router = build(store, [change_plan()])[1]
    reply = router.handle("less leg work next week")
    assert "Reply yes" not in reply and "less leg work" in store.get("pending:plan_change")


def test_change_asks_when_the_last_session_day_has_passed(store):
    store.add_plan_session("2026-11-16", "home", "strength", "approved", EXS)
    store.delete_plan_session(DAY)
    store.add_plan_session("2026-11-24", "home", "strength", "proposed", EXS)
    router = build(store, [change_plan()])[1]
    assert router.handle("less leg work next week").endswith("Reply yes.")


def test_closing_the_last_session_of_the_week_asks_about_the_note(store):
    store.set("pending:plan_change", "less leg work")
    reports.log_report(store, DAY, [{"exercise": "Press", "weight_kg": 20, "reps": 10}])
    router, fake = build(store, ["not json", "not json"])[1:]
    router.handle("start")
    reply = router.handle("end")
    assert "Plan next week (23 Nov to 29 Nov) with: less leg work? Reply yes." in reply
    router.handle("yes")
    assert fake.calls[0]["model"] == "claude-opus-5-5"


def test_propose_still_works_during_the_week(store):
    router, fake = build(store, ["not json", "not json"])[1:]
    router.handle("/propose")
    assert fake.calls and fake.calls[0]["model"] == "claude-opus-5-5"


# (7) "typing" repeats until the reply is sent

class SlowClaude(FakeClaude):
    def create(self, **kwargs):
        time.sleep(0.3)
        return super().create(**kwargs)


def test_typing_repeats_until_the_reply(store, monkeypatch):
    monkeypatch.setattr(app_module, "TYPING_EVERY_S", 0.05)
    tg = ActionTelegram()
    app, router, _ = build(store, [], tg)
    router.claude._client = SlowClaude([report("Press", 10)])
    say(app, "press 10")
    count = len(tg.actions)
    assert count >= 3 and tg.sent
    time.sleep(0.2)
    assert len(tg.actions) == count
    assert not [t for t in threading.enumerate() if t.name == "typing"]


# (8) "X and Y now missing" is checked against the chat

def check(**fields):
    return json.dumps(fields)


def test_sets_in_the_chat_that_were_never_saved_are_added(store):
    store.add_chat("2026-11-17T16:50:00+08:00", "in", "leg ext 20 10 10")
    store.add_chat("2026-11-17T16:50:05+08:00", "out", "Leg ext: 20 kg x 10, 10", delivered=False)
    router, fake = build(store, [json.dumps({"intent": "log_check"}), check(
        verdict="fix", add=[{"exercise": "Leg ext", "weight_kg": 20, "reps": 10}] * 2)])[1:]
    reply = router.handle("leg ext now missing")
    assert [r["exercise"] for r in store.logged_sets(DAY)] == ["Leg ext", "Leg ext"]
    assert "Added: Leg ext 20 kg x 10, 10" in reply
    assert "leg ext 20 10 10" in prompt_of(fake.calls[1]) and len(fake.calls) == 2


def test_a_set_saved_wrong_is_fixed_and_the_reply_says_how(store):
    reports.log_report(store, DAY, [{"exercise": "Press", "weight_kg": 20, "reps": 10},
                                    {"exercise": "Press", "weight_kg": 20, "reps": 8}])
    router = build(store, [json.dumps({"intent": "log_check"}), check(
        verdict="fix", fix=[{"exercise": "Press", "set_no": 2, "weight_kg": 20, "reps": 10}])])[1]
    reply = router.handle("press set 2 is wrong")
    assert [r["reps"] for r in store.logged_sets(DAY)] == [10, 10]
    assert "Fixed: Press set 2 from 20 kg x 8 to 20 kg x 10" in reply


def test_saved_as_reported_asks_whether_he_misread(store):
    reports.log_report(store, DAY, [{"exercise": "Press", "weight_kg": 20, "reps": 10}] * 2)
    store.add_plan_session("2026-11-24", "home", "strength", "proposed", EXS)
    before = store.plan_sessions("2026-11-01", "2026-12-31")
    router = build(store, [json.dumps({"intent": "log_check"}), check(verdict="misread")])[1]
    reply = router.handle("press now missing")
    assert "Press: 20 kg x 10, 10" in reply and "misread" in reply and "?" in reply
    assert len(store.logged_sets(DAY)) == 2
    assert store.plan_sessions("2026-11-01", "2026-12-31") == before


def test_the_check_never_deletes_and_skips_unknown_exercises(store):
    reports.log_report(store, DAY, [{"exercise": "Press", "weight_kg": 20, "reps": 10}] * 2)
    router = build(store, [json.dumps({"intent": "log_check"}), check(
        verdict="fix", add=[{"exercise": "Zercher squat", "weight_kg": 40, "reps": 5}],
        delete=[{"exercise": "Press", "set_no": 1}],
        fix=[{"exercise": "Press", "set_no": 9, "weight_kg": 20, "reps": 1}])])[1]
    reply = router.handle("my log is wrong")
    assert [(r["exercise"], r["reps"]) for r in store.logged_sets(DAY)] == [("Press", 10)] * 2
    assert "Zercher" not in reply and "misread" in reply


def test_a_fix_that_completes_the_shown_exercise_moves_on(store):
    reports.log_report(store, DAY, [{"exercise": "Press", "weight_kg": 20, "reps": 10}])
    router = build(store, [json.dumps({"intent": "log_check"}), check(
        verdict="fix", add=[{"exercise": "Press", "weight_kg": 20, "reps": 9}])])[1]
    router.handle("press set 2 missing")
    assert store.get(f"flow:{DAY}") == "1" and router.pop_exercise()[1] == 1


# (9) the sorting JSON leaves out empty fields

def test_sorting_prompt_asks_to_leave_out_empty_fields():
    assert "leave out" in CLASSIFY_SYSTEM.lower()


def test_short_json_without_optional_fields_is_read(store):
    router = build(store, [json.dumps({"intent": "report",
                                       "sets": [{"exercise": "Press", "reps": 10}]}),
                           json.dumps({"intent": "change_plan"})])[1]
    assert router.handle("press 10").startswith("Press: x 10")
    assert "more rows" in router.handle("more rows next week")
