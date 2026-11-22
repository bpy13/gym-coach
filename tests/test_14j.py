"""Task 14j: a warm-up before the first exercise, stretching after the last, and a "Finish
session" button that closes the workout. Made-up data only."""

import json
from datetime import datetime

import httpx
import pytest

from fakes import FakeTelegram, tool_use
from gym_coach import reports
from gym_coach.llm import HK
from gym_coach.messages import WARM_UP, stretch_message, warm_up_message
from gym_coach.scheduler import Scheduler
from gym_coach.store import Store
from gym_coach.telegram import TelegramClient
from test_session_fixes import DAY, EXS, build, report, say, turn

NEXT = turn(tool_use("show_exercise", {"exercise": "next"}))
FINISH = {"keyboard": [[{"text": "Finish session"}]], "resize_keyboard": True}
REMOVE = {"remove_keyboard": True}


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    s.add_plan_session(DAY, "home", "strength", "approved", EXS)
    s.set("chat_id", "5")
    yield s
    s.close()


def morning(store):
    sent = []
    Scheduler(store, lambda t: sent.append(("text", t)),
              now=lambda: datetime(2026, 11, 17, 7, 0, tzinfo=HK)).tick()
    return sent


def all_but_last_set(store):
    reports.log_report(store, DAY, [{"exercise": n, "weight_kg": 20, "reps": 10}
                                    for n in ("Press", "Pulldown", "Leg ext") for _ in (1, 2)]
                       + [{"exercise": "Shoulder", "weight_kg": 20, "reps": 10}])
    store.set(f"flow:{DAY}", "3")


# (1) the warm-up comes after the list and before the first exercise

def test_morning_sends_the_list_then_the_warm_up_and_no_exercise(store):
    sent = morning(store)
    assert [kind for kind, _ in sent] == ["text", "text"]
    warm = sent[1][1]
    assert warm == warm_up_message()
    for name in ("Bear crawl", "Jumping jacks", "High knees", "Arm circles", "squats"):
        assert name in warm
    assert "8 minutes" in warm and "no equipment" in warm
    assert store.get(f"flow:{DAY}") == "0"


def test_warm_up_is_one_list_in_the_code():
    assert all(name in warm_up_message() for name, _ in WARM_UP)


def test_done_after_the_warm_up_sends_the_first_exercise(store):
    morning(store)
    router = build(store, [NEXT, NEXT])[1]
    reply = router.handle("done")
    assert reply.startswith("Warm-up over. First exercise: Press")
    assert router.pop_exercise()[1] == 0
    assert store.get(f"flow:{DAY}") == "0" and store.logged_sets(DAY) == []
    assert (store.get(f"workout:{DAY}") or "").startswith("open|")
    assert router.handle("done").startswith("Moved on from Press")  # only once


def test_a_first_set_during_the_warm_up_ends_it_and_shows_the_exercise(store):
    morning(store)
    router = build(store, [report("Press", 10)])[1]
    reply = router.handle("press 10")
    assert "Press: 20 kg x 10" in reply and router.pop_exercise()[1] == 0
    router2 = build(store, [NEXT])[1]
    router2.handle("done")  # now an ordinary "done": Press moves on
    assert store.get(f"flow:{DAY}") == "1"


def test_start_without_the_morning_message_shows_the_warm_up(store):
    router = build(store, [NEXT])[1]
    reply = router.handle("start")
    assert warm_up_message() in reply and router.pop_exercise() is None
    router.handle("done")
    assert router.pop_exercise()[1] == 0


# (2) stretching after the last exercise, then the "Finish session" button

def test_last_exercise_done_reminds_to_stretch_with_the_button(store):
    all_but_last_set(store)
    tg = FakeTelegram()
    app = build(store, [report("Shoulder", 10)], tg)[0]
    say(app, "shoulder 10")
    text = tg.sent[-1][1]
    assert "Session done" in text and "Stretch" in text
    assert "shoulder" in text.lower() and "quad" in text.lower()
    assert tg.markups[-1] == FINISH
    assert (store.get(f"workout:{DAY}") or "").startswith("open|")


def test_stretch_list_follows_the_muscles_of_the_day():
    legs = {"exercises": [{"name": "Lying leg curl"}, {"name": "Leg press"}]}
    text = stretch_message(legs)
    assert "hamstring" in text.lower() and "quad" in text.lower()
    assert "chest" not in text.lower() and "about 4 minutes" in text


@pytest.mark.parametrize("word", ["Finish session", "finish", "end"])
def test_finish_closes_the_workout_sends_the_summary_and_removes_the_button(store, word):
    all_but_last_set(store)
    tg = FakeTelegram()
    finish = [] if word == "Finish session" else [turn(tool_use("finish_workout", {}))]
    app = build(store, [report("Shoulder", 10), *finish], tg)[0]
    say(app, "shoulder 10", 1)
    say(app, word, 2)
    text = tg.sent[-1][1]
    assert "Summary:" in text and "Press: 20 kg x 10, 10" in text
    assert tg.markups[-1] == REMOVE
    assert (store.get(f"workout:{DAY}") or "").startswith("closed|")


def test_the_2100_close_still_closes_a_workout_never_finished(store):
    all_but_last_set(store)
    router = build(store, [report("Shoulder", 10)])[1]
    router.handle("shoulder 10")
    Scheduler(store, lambda t: None, now=lambda: datetime(2026, 11, 17, 21, 0, tzinfo=HK)).tick()
    assert (store.get(f"workout:{DAY}") or "").startswith("closed|")


def test_ordinary_replies_carry_no_keyboard(store):
    tg = FakeTelegram()
    store.set(f"flow:{DAY}", "0")
    app = build(store, [report("Press", 10)], tg)[0]
    say(app, "press 10")
    assert tg.markups == [None]


def test_client_sends_the_reply_markup_with_the_text():
    seen = []

    def handler(req):
        seen.append(json.loads(req.read()))
        return httpx.Response(200, json={"ok": True, "result": {}})
    tg = TelegramClient("1:X", 42, client=httpx.Client(transport=httpx.MockTransport(handler)))
    tg.send_message(42, "Stretch now", reply_markup=FINISH)
    tg.send_message(42, "plain")
    assert seen == [{"chat_id": 42, "text": "Stretch now", "reply_markup": FINISH},
                    {"chat_id": 42, "text": "plain"}]
