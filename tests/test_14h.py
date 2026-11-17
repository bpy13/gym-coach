"""Task 14h: traces per message, photos that are not meals, his own exercises, no surprise
weeks, sets for another exercise, typo checks and faster replies. Made-up data only."""

import importlib.util
import io
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from PIL import Image

from fakes import FakeTelegram
from gym_coach import reports
from gym_coach.store import Store
from gym_coach.telegram import TelegramClient, TelegramError
from test_session_fixes import DAY, EXS, build, report, say

JPEG = b"\xff\xd8fake-image-bytes"
MEAL = json.dumps({"meal": True, "what": "rice", "description": "chicken rice", "kcal": 650,
                   "protein_g": 35})


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    s.add_plan_session(DAY, "home", "strength", "approved", EXS)
    s.set(f"flow:{DAY}", "0")
    s.set("chat_id", "5")
    yield s
    s.close()


def traces(store):
    return store._rows("SELECT * FROM trace ORDER BY id")


def prompt_of(call) -> str:
    return json.dumps(call["messages"][0]["content"])


def has_image(call) -> bool:
    content = call["messages"][0]["content"]
    return any(b.get("type") == "image" for b in content)


# (1) the chat is kept for good

def test_old_chat_is_kept(store):
    store.add_chat("2026-09-01T10:00:00+08:00", "in", "old")
    app = build(store, ["{}", "fine"])[0]
    say(app, "hello")
    assert "old" in [r["text"] for r in store._rows("SELECT text FROM chat")]


# (2) a trace per incoming message

def test_model_message_gets_a_trace_with_its_call(store):
    app = build(store, [report("Press", 10)])[0]
    say(app, "press 10")
    [t] = traces(store)
    chat_in = next(r for r in store.chat_lines(DAY) if r["direction"] == "in")
    assert t["chat_row"] == chat_in["id"]
    assert json.loads(t["understood"])["intent"] == "report"
    [call] = json.loads(t["calls"])
    assert call["model"] == "claude-haiku-5-5" and call["seconds"] >= 0
    assert "report" in call["reply"]
    assert t["seconds"] >= 0 and t["error"] is None


def test_command_trace_says_local(store):
    app = build(store, [])[0]
    say(app, "/today")
    [t] = traces(store)
    assert t["understood"] == "local" and json.loads(t["calls"]) == []


def test_model_error_is_traced(store):
    app = build(store, ["not json", "not json"])[0]
    say(app, "what now")
    [t] = traces(store)
    assert "valid JSON" in t["error"]


def test_trace_failure_never_stops_the_reply(store, monkeypatch):
    tg = FakeTelegram()
    app = build(store, [report("Press", 10)], tg)[0]

    def boom(*a, **k):
        raise sqlite3.OperationalError("disk")
    monkeypatch.setattr(store, "add_trace", boom)
    say(app, "press 10")
    assert tg.sent and tg.sent[0][1].startswith("Press: 20 kg x 10")


def test_existing_database_is_migrated_and_keeps_its_rows(tmp_path):
    path = tmp_path / "old.db"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE chat (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,"
               " direction TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'text', text TEXT NOT NULL,"
               " delivered INTEGER NOT NULL DEFAULT 1, late INTEGER NOT NULL DEFAULT 0)")
    db.execute("INSERT INTO chat (timestamp, direction, text) VALUES ('2026-11-17T10:00:00', 'in',"
               " 'kept')")
    db.execute("CREATE TABLE logged_sets (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT NOT NULL,"
               " exercise TEXT NOT NULL, set_no INTEGER NOT NULL, weight_kg REAL, reps INTEGER,"
               " effort TEXT)")
    db.execute("INSERT INTO logged_sets (date, exercise, set_no, weight_kg, reps) VALUES"
               " ('2026-11-17', 'Press', 1, 20, 10)")
    db.commit()
    db.close()
    s = Store(path)
    assert [r["text"] for r in s.chat_lines("2026-11-17")] == ["kept"]
    assert s._rows("SELECT * FROM trace") == []
    [old] = s.logged_sets("2026-11-17")
    assert old["reps"] == 10 and old["saved_at"] is None
    s.close()
    Store(path).close()  # a second start finds the column there and changes nothing


# a save time on each logged set (Brian, 2026-11-17)

def test_each_set_gets_a_save_time_that_later_reports_keep(store):
    store.add_logged_set(DAY, "Press", 1, 20, 10)  # from before the save time
    router = build(store, [report("Press", 9)])[1]
    router.handle("press 9")
    old, new = store.logged_sets(DAY)
    assert old["saved_at"] is None and datetime.fromisoformat(new["saved_at"]).tzinfo
    first = new["saved_at"]
    reports.log_report(store, DAY, [{"exercise": "Pulldown", "weight_kg": 20, "reps": 8}])
    rows = store.logged_sets(DAY)
    assert [r["saved_at"] for r in rows[:2]] == [None, first] and rows[2]["saved_at"]


def test_show_chat_prints_the_chat_with_its_traces_and_set_times(store, tmp_path):
    store.add_logged_set(DAY, "Leg ext", 1, 20, 12)  # from before the save time
    app = build(store, [report("Press", 10)])[0]
    say(app, "presss 10")
    spec = importlib.util.spec_from_file_location(
        "show_chat", Path(__file__).resolve().parent.parent / "scripts" / "show_chat.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = mod.render(tmp_path / "t.db", DAY)
    assert "presss 10" in out and '"intent": "report"' in out
    assert "claude-haiku-5-5" in out and "Press: 20 kg x 10" in out
    assert "(no save time) Set saved: Leg ext set 1: 20 kg x 12" in out
    assert "Set saved: Press set 1: 20 kg x 10" in out


# (3) a photo is not always a meal

def test_caption_is_sorted_like_a_text_and_a_question_is_answered(store):
    router, fake = build(store, [json.dumps({"intent": "question"}), "Yes, hold it at chest."])[1:]
    reply = router.handle_photo(JPEG, "can I use this plate for halos?")
    assert reply == "Yes, hold it at chest."
    assert "photo" in prompt_of(fake.calls[0]).lower() and not has_image(fake.calls[0])
    assert has_image(fake.calls[1])
    assert store.meals_on(DAY) == []


def test_caption_with_meal_intent_sends_the_image_to_the_estimate(store):
    router, fake = build(store, [json.dumps({"intent": "meal"}), MEAL])[1:]
    reply = router.handle_photo(JPEG, "lunch")
    assert has_image(fake.calls[1]) and reply.startswith("About 650 kcal")
    assert len(store.meals_on(DAY)) == 1


def test_photo_without_caption_that_is_not_a_meal_is_not_stored(store):
    router = build(store, [json.dumps({"meal": False, "what": "a weight plate"})])[1]
    reply = router.handle_photo(JPEG, None)
    assert store.meals_on(DAY) == []
    assert "weight plate" in reply and "?" in reply


def test_photo_is_shrunk_before_the_image_call(store):
    img = io.BytesIO()
    Image.new("RGB", (2000, 1500), "blue").save(img, "JPEG")
    router, fake = build(store, [MEAL])[1:]
    router.handle_photo(img.getvalue(), None)
    import base64
    data = fake.calls[0]["messages"][0]["content"][0]["source"]["data"]
    assert max(Image.open(io.BytesIO(base64.b64decode(data))).size) == 1024


# (4) his own exercises

def test_own_exercise_is_logged_under_its_name_and_added_to_today(store):
    router = build(store, [json.dumps({"intent": "report", "sets": [
        {"exercise": "Plate halo", "weight_kg": 10, "reps": 10, "own": True}]})])[1]
    reply = router.handle("plate halo 10kg 10")
    assert [r["exercise"] for r in store.logged_sets(DAY)] == ["Plate halo"]
    added = store.plan_session(DAY)["exercises"][-1]
    assert added["name"] == "Plate halo" and added["own"] is True
    assert store.get(f"flow:{DAY}") == "0"
    assert "Plate halo: 10 kg x 10" in reply and reply.endswith("Now: Press.")


def test_unknown_name_without_own_is_logged_as_the_shown_exercise(store):
    router = build(store, [report("press machine", 10)])[1]
    router.handle("10")
    assert [r["exercise"] for r in store.logged_sets(DAY)] == ["Press"]


# (5) "X and Y now missing" is never a plan change (Task 14i adds the check against the chat)

def test_missing_sets_message_shows_the_log_and_changes_nothing(store):
    reports.log_report(store, DAY, [{"exercise": "Press", "weight_kg": 20, "reps": 10}] * 2)
    store.add_plan_session("2026-11-24", "home", "strength", "proposed", EXS)
    router, fake = build(store, [json.dumps({"intent": "log_check"}),
                                 json.dumps({"verdict": "misread"})])[1:]
    before = store.plan_sessions("2026-11-01", "2026-12-31")
    reply = router.handle("leg ext and shoulder now missing")
    assert "Press: 20 kg x 10, 10" in reply
    assert "Missing: Pulldown (0 of 2), Leg ext (0 of 2), Shoulder (0 of 2)" in reply
    assert len(store.logged_sets(DAY)) == 2 and len(fake.calls) == 2
    assert all(c["model"] == "claude-haiku-5-5" for c in fake.calls)
    assert store.plan_sessions("2026-11-01", "2026-12-31") == before


# (6) no surprise weeks

def change_plan(change="less leg work"):
    return json.dumps({"intent": "change_plan", "change": change})


def test_change_with_a_proposed_week_asks_first(store):
    store.set_plan_status(DAY, "done")
    store.add_plan_session("2026-11-24", "home", "strength", "proposed", EXS)
    router, fake = build(store, [change_plan(), "not json", "not json"])[1:]
    reply = router.handle("less leg work next week")
    assert reply == "Revise the proposed week 23 Nov to 29 Nov with: less leg work? Reply yes."
    assert len(fake.calls) == 1
    router.handle("yes")
    assert fake.calls[1]["model"] == "claude-opus-5-5"
    assert "less leg work" in json.dumps(fake.calls[1]["messages"])


def test_no_to_the_revise_question_writes_nothing(store):
    store.set_plan_status(DAY, "done")
    store.add_plan_session("2026-11-24", "home", "strength", "proposed", EXS)
    router, fake = build(store, [change_plan(), json.dumps({"intent": "question"}), "Ok."])[1:]
    router.handle("less leg work next week")
    router.handle("no")
    assert all(c["model"] != "claude-opus-5-5" for c in fake.calls)
    assert not store.get("pending:revise")


def test_change_during_an_open_session_is_only_a_note(store):
    store.add_plan_session("2026-11-24", "home", "strength", "proposed", EXS)
    router, fake = build(store, [change_plan()])[1:]
    reply = router.handle("less leg work next week")
    assert "/propose" in reply and "Reply yes" not in reply
    assert len(fake.calls) == 1 and "less leg work" in store.get("pending:plan_change")


# (7) a set for an exercise other than the one shown

def test_set_for_an_earlier_exercise_names_it_then_the_shown_one(store):
    store.set(f"flow:{DAY}", "1")
    router = build(store, [report("Press", 10)])[1]
    reply = router.handle("press 10")
    assert "Press: 20 kg x 10" in reply and reply.endswith("Now: Pulldown.")
    assert store.get(f"flow:{DAY}") == "1"


def test_session_goes_back_to_exercises_with_sets_left_before_closing(store):
    store.set(f"flow:{DAY}", "3")
    reports.log_report(store, DAY, [{"exercise": "Press", "weight_kg": 20, "reps": 10}] * 2)
    router = build(store, [report("Shoulder", 10, 10)])[1]
    reply = router.handle("shoulder 10 10")
    assert "Session done" not in reply
    assert store.get(f"flow:{DAY}") == "1" and router.pop_exercise()[1] == 1
    router.handle("skip")
    assert store.get(f"flow:{DAY}") == "2"
    done = router.handle("skip")
    assert "Session done" in done and "Missing: Pulldown (0 of 2), Leg ext (0 of 2)" in done


# (8) typos

def test_weight_far_from_the_plan_asks_about_a_typo(store):
    router = build(store, [report("Press", 10, weight=200)])[1]
    reply = router.handle("press 200 10")
    assert "Press: 200 kg x 10" in reply and "Typo?" in reply
    assert "Reply with the right number." in reply


def test_weight_far_below_the_last_set_asks_about_a_typo(store):
    reports.log_report(store, DAY, [{"exercise": "Press", "weight_kg": 30, "reps": 10}])
    router = build(store, [report("Press", 10, weight=14)])[1]
    assert "Typo?" in router.handle("press 14 10")


def test_normal_weight_has_no_typo_question(store):
    router = build(store, [report("Press", 10, weight=25)])[1]
    assert "Typo?" not in router.handle("press 25 10")


# (9) faster replies

@pytest.mark.parametrize("text", ["35 12", "35kg 12, 10", "35"])
def test_number_only_reports_go_to_the_model(store, text):
    # Brian, 2026-11-17: reading "35 12" without the model is "quite risky, no need"
    router, fake = build(store, [json.dumps({"intent": "unclear", "question": "Which?"})])[1:]
    router.handle(text)
    assert len(fake.calls) == 1


class ActionTelegram(FakeTelegram):
    def __init__(self, fail=False):
        super().__init__()
        self.actions, self.fail = [], fail

    def send_chat_action(self, chat_id, action="typing"):
        if self.fail:
            raise TelegramError("sendChatAction failed: ConnectError")
        self.actions.append((chat_id, action))


def test_typing_goes_out_on_receipt(store):
    tg = ActionTelegram()
    app = build(store, [], tg)[0]
    say(app, "20 10")
    assert tg.actions == [(5, "typing")] and tg.sent


def test_failing_typing_action_is_ignored(store):
    tg = ActionTelegram(fail=True)
    app = build(store, [], tg)[0]
    say(app, "20 10")
    assert tg.sent


def test_client_sends_the_typing_action():
    seen = []

    def handler(req):
        seen.append((req.url.path, json.loads(req.read())))
        return httpx.Response(200, json={"ok": True, "result": True})
    tg = TelegramClient("1:X", 42, client=httpx.Client(transport=httpx.MockTransport(handler)))
    tg.send_chat_action(42)
    assert seen == [("/bot1:X/sendChatAction", {"chat_id": 42, "action": "typing"})]
