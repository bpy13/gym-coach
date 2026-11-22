"""A whole strength session, one exercise at a time, through the scheduler, router and App."""

from datetime import datetime

import pytest

from fakes import FakeClaude, FakeTelegram, tool_use
from gym_coach.app import App
from gym_coach.llm import HK, Claude
from gym_coach.router import Router
from gym_coach.scheduler import Scheduler
from gym_coach.store import Store
from gym_coach.telegram import Incoming
from test_session_fixes import flat, tool_results, turn

DAY = "2026-11-17"
NOW = datetime(2026, 11, 17, 7, 0, tzinfo=HK)
EXS = [{"name": n, "equipment": n, "sets": 2, "rep_low": 8, "rep_high": 12, "weight_kg": 20}
       for n in ("Press", "Row", "Curl")]


def report(name, *reps):
    return turn(tool_use("log_sets", {"sets": [
        {"exercise": name, "weight_kg": 20, "reps": r} for r in reps]}))


NEXT = turn(tool_use("show_exercise", {"exercise": "next"}))


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    s.add_plan_session(DAY, "home", "strength", "approved", EXS)
    yield s
    s.close()


def build(store, replies, tg=None):
    tg = tg or FakeTelegram()
    router = Router(store, Claude(FakeClaude(flat(replies)), store, 5.0, now=lambda: NOW),
                    "claude-haiku-5-5", "claude-opus-5-5", now=lambda: NOW, profile_path="examples/profile.md",
                    equipment_path="examples/equipment.md")
    app = App(tg, router, store)
    sched = Scheduler(store, app.send_to_owner, now=lambda: NOW)
    return app, sched, tg


def say(app, text, n):
    app.handle(Incoming(n, 5, text=text))


def test_whole_session_one_exercise_per_completing_reply(store):
    app, sched, tg = build(store, [NEXT, report("Press", 10, 10), report("Row", 10)])
    app.chat_id = 5
    sched.tick()
    texts = [t for _, t in tg.sent]
    assert len(texts) == 2 and "Send start" not in texts[0]
    assert texts[0].splitlines()[0] == "Home gym, Tue 17 Nov" and "Row: 2 x 8-12" in texts[0]
    assert texts[1].startswith("Warm-up")  # the warm-up right after the list (Task 14j)

    say(app, "done", 0)  # warm-up done -> the first exercise arrives
    assert tg.sent[-1][1].startswith("Press: 2 x 8-12")

    say(app, "press 10 10", 1)  # completes Press -> Row arrives
    assert tg.sent[-2][1].startswith("Press: 20 kg x 10, 10")
    assert tg.sent[-1][1].startswith("Row: 2 x 8-12")

    n = len(tg.sent)
    say(app, "row 10", 2)  # one set of two: short line, nothing new shown
    assert len(tg.sent) == n + 1 and "1 set left" in tg.sent[-1][1]

    app2, _, _ = build(store, [NEXT, report("Curl", 12, 12)], tg)  # restart in the middle
    say(app2, "skip", 3)  # skip Row -> Curl arrives
    assert "Moved on from Row: 20 kg x 10" in tg.sent[-2][1]
    assert tg.sent[-1][1].startswith("Curl: 2 x 8-12")

    n = len(tg.sent)
    say(app2, "curl 12 12", 4)  # last: stretching and the Finish button, no further exercise
    assert len(tg.sent) == n + 1
    assert "Session done" in tg.sent[-1][1] and "Stretch" in tg.sent[-1][1]
    say(app2, "Finish session", 5)  # the summary
    assert "Press: 20 kg x 10, 10" in tg.sent[-1][1]
    say(app2, "next", 6)  # nothing open: the model answers (scripted "ok")
    assert tg.sent[-1][1] == "ok"


def test_next_with_sets_logged_moves_on(store):
    app, sched, tg = build(store, [report("Press", 10), NEXT])
    app.chat_id = 5
    sched.tick()
    say(app, "press 10", 1)
    say(app, "done", 2)
    assert "Press: 20 kg x 10" in tg.sent[-2][1]
    assert tg.sent[-1][1].startswith("Row: 2 x 8-12")


def test_a_name_not_in_the_session_is_refused_and_the_model_logs_the_shown_one(store):
    bad_round = report("bench thing", 10, 10)[0]  # the tool round alone; the model goes on
    app, sched, _ = build(store, [bad_round, report("Press", 10, 10)])
    app.chat_id = 5
    sched.tick()
    say(app, "10 10", 1)
    fake = app.router.claude.client
    [res] = tool_results(fake.calls[1])
    assert res["is_error"] and "Press, Row, Curl" in res["content"]
    assert {r["exercise"] for r in store.logged_sets(DAY)} == {"Press"}


def test_new_day_starts_fresh(store):
    store.set("flow:2026-11-16", "2")
    app, sched, _ = build(store, [])
    app.chat_id = 5
    sched.tick()
    assert store.get(f"flow:{DAY}") == "0"
