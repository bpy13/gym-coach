"""Task 14g: what the 17 Nov session showed. Late replies, changes to today's session, the
pointer following reports, `done` only at the end, and messages read with the chat in view."""

import json
from datetime import datetime

import pytest

from fakes import FakeClaude, FakeTelegram
from gym_coach import reports
from gym_coach.app import App
from gym_coach.llm import HK, Claude
from gym_coach.router import Router
from gym_coach.scheduler import Scheduler
from gym_coach.store import Store
from gym_coach.telegram import Incoming, TelegramError

DAY = "2026-11-17"
NOW = datetime(2026, 11, 17, 17, 0, tzinfo=HK)
EXS = [{"name": n, "equipment": e, "sets": 2, "rep_low": 8, "rep_high": 12, "weight_kg": 20}
       for n, e in (("Press", "Chest press"), ("Pulldown", "Lat pulldown"),
                    ("Leg ext", "Leg extension"), ("Shoulder", "Shoulder press"))]


def report(name, *reps, weight=20):
    return json.dumps({"intent": "report", "sets": [
        {"exercise": name, "weight_kg": weight, "reps": r} for r in reps]})


class Clock:
    def __init__(self, when=NOW):
        self.when = when

    def __call__(self):
        return self.when


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    s.add_plan_session(DAY, "home", "strength", "approved", EXS)
    s.set(f"flow:{DAY}", "0")  # the 07:00 message went out
    s.set("chat_id", "5")
    yield s
    s.close()


def build(store, replies, tg=None, clock=None):
    clock = clock or Clock()
    fake = FakeClaude(replies)
    router = Router(store, Claude(fake, store, 5.0, now=clock), "claude-haiku-5-5",
                    "claude-opus-5-5", now=clock, profile_path="examples/profile.md",
                    equipment_path="examples/equipment.md")
    app = App(tg or FakeTelegram(), router, store)
    return app, router, fake


def say(app, text, n=1):
    app.handle(Incoming(n, 5, text=text))


class FlakyTelegram(FakeTelegram):
    """Fails the next `fail` text sends (after Task 14f's own tries), then works."""

    def __init__(self, fail=0):
        super().__init__()
        self.fail = fail

    def send_message(self, chat_id, text):
        if self.fail:
            self.fail -= 1
            raise TelegramError("sendMessage failed: ConnectError")
        super().send_message(chat_id, text)


# (1) the chat is kept

def test_both_directions_are_kept_with_delivery(store):
    tg = FlakyTelegram(fail=1)
    app, _, _ = build(store, [report("Press", 10)], tg)
    say(app, "press 10")
    rows = store.chat_lines(DAY)
    assert [(r["direction"], r["delivered"]) for r in rows] == [("in", 1), ("out", 0)]
    assert rows[0]["text"] == "press 10" and rows[1]["text"].startswith("Press: 20 kg x 10")


# (2) a reply that could not be delivered goes out first, marked (late)

def test_undelivered_reply_is_sent_first_when_sending_works(store):
    tg = FlakyTelegram(fail=1)
    app, _, _ = build(store, [report("Press", 10), report("Press", 9)], tg)
    say(app, "press 10", 1)
    assert tg.sent == []
    say(app, "press 9", 2)
    assert tg.sent[0][1].startswith("(late) Press: 20 kg x 10.")
    assert "Press: 20 kg x 10, 9" in tg.sent[1][1]
    outs = [r for r in store.chat_lines(DAY) if r["direction"] == "out"]
    assert outs[0]["delivered"] == 1 and outs[0]["late"] == 1


def test_scheduler_message_also_flushes_late_reply(store):
    tg = FlakyTelegram(fail=1)
    app, _, _ = build(store, [report("Press", 10)], tg)
    say(app, "press 10")
    app.send_to_owner("Weekly check-in")
    assert tg.sent[0][1].startswith("(late) ")
    assert tg.sent[-1][1] == "Weekly check-in"


def test_late_reply_from_a_previous_day_is_not_sent(store):
    store.add_chat("2026-11-16T17:00:00+08:00", "out", "yesterday", delivered=False)
    tg = FakeTelegram()
    app, _, _ = build(store, ["{}", "fine"], tg)
    say(app, "hello")
    assert all("yesterday" not in t for _, t in tg.sent)


# (3) a change during the session changes today only

def change_today(action, exercise, **extra):
    return json.dumps({"intent": "change_today",
                       "today": {"action": action, "exercise": exercise, **extra}})


def test_swap_shown_exercise_keeps_logged_sets_and_shows_the_new_one(store):
    store.set(f"flow:{DAY}", "1")
    reports.log_report(store, DAY, [{"exercise": "Pulldown", "weight_kg": 20, "reps": 10}])
    router, fake = build(store, [change_today("swap", "Pulldown", new_exercise="Cable row",
                                              equipment="Dual adjustable cable machine",
                                              weight_kg=15)])[1:]
    reply = router.handle("pulldown is taken, can I do cable row")
    session = store.plan_session(DAY)
    names = [e["name"] for e in session["exercises"]]
    assert names == ["Press", "Pulldown", "Cable row", "Leg ext", "Shoulder"]
    assert session["exercises"][1]["sets"] == 1  # the one set he did
    assert session["exercises"][2]["sets"] == 1 and session["exercises"][2]["weight_kg"] == 15
    assert len(store.logged_sets(DAY)) == 1
    assert router.pop_exercise()[1] == 2 and store.get(f"flow:{DAY}") == "2"
    assert "Cable row" in reply
    assert len(fake.calls) == 1 and fake.calls[0]["model"] == "claude-haiku-5-5"
    assert store.plan_sessions("2026-11-23", "2026-11-29") == []


def test_swap_to_equipment_not_at_todays_gym_asks_and_changes_nothing(store):
    router = build(store, [change_today("swap", "Pulldown", new_exercise="Leg press",
                                        equipment="Seated leg press")])[1]
    reply = router.handle("can I do leg press instead of pulldown")
    assert "?" in reply
    assert [e["name"] for e in store.plan_session(DAY)["exercises"]][1] == "Pulldown"


def test_drop_shown_exercise_shows_the_next(store):
    router = build(store, [change_today("drop", "Press")])[1]
    router.handle("drop the press, my shoulder hurts")
    assert [e["name"] for e in store.plan_session(DAY)["exercises"]] == [
        "Pulldown", "Leg ext", "Shoulder"]
    assert router.pop_exercise()[1] == 0 and store.get(f"flow:{DAY}") == "0"


def test_weight_change_for_today(store):
    router = build(store, [change_today("weight", "Leg ext", weight_kg=15)])[1]
    router.handle("leg ext 15 kg today")
    assert store.plan_session(DAY)["exercises"][2]["weight_kg"] == 15


def test_change_plan_without_a_proposed_week_is_a_note_not_a_new_week(store):
    router, fake = build(store, [json.dumps({"intent": "change_plan",
                                             "change": "less leg work"})])[1:]
    reply = router.handle("less leg work next week")
    assert "/propose" in reply
    assert store.plan_sessions("2026-11-18", "2026-12-31") == []
    assert len(fake.calls) == 1  # the sorting call only, no coach call
    assert "less leg work" in store.get("pending:plan_change")


# (4) the pointer follows what he reports

def test_set_for_a_later_exercise_moves_the_pointer(store):
    router = build(store, [report("Leg ext", 10)])[1]
    reply = router.handle("leg ext 20 10")
    assert store.get(f"flow:{DAY}") == "2"
    assert "1 set left" in reply


def test_advance_passes_over_an_exercise_already_complete(store):
    reports.log_report(store, DAY, [{"exercise": "Pulldown", "weight_kg": 20, "reps": 10}] * 2)
    router = build(store, [report("Press", 10, 10)])[1]
    router.handle("press 10 10")
    assert store.get(f"flow:{DAY}") == "2" and router.pop_exercise()[1] == 2


# (5) done at the end, not at the first set

def test_first_set_leaves_the_day_approved(store):
    router = build(store, [report("Press", 10)])[1]
    router.handle("press 10")
    assert store.plan_session(DAY)["status"] == "approved"


def test_flow_close_marks_done(store):
    store.set(f"flow:{DAY}", "3")
    for name in ("Press", "Pulldown", "Leg ext"):  # the session closes when none has sets left
        reports.log_report(store, DAY, [{"exercise": name, "weight_kg": 20, "reps": 10}] * 2)
    router = build(store, [report("Shoulder", 10, 10)])[1]
    router.handle("shoulder 10 10")
    assert store.plan_session(DAY)["status"] == "done"


def test_evening_job_marks_a_day_with_sets_done_silently(store):
    reports.log_report(store, DAY, [{"exercise": "Press", "weight_kg": 20, "reps": 10}])
    store.set(f"sent:session:{DAY}", "1")
    sent = []
    sched = Scheduler(store, sent.append, now=Clock(datetime(2026, 11, 17, 20, 59, tzinfo=HK)))
    sched.tick()
    assert store.plan_session(DAY)["status"] == "approved"
    sched._now = Clock(datetime(2026, 11, 17, 21, 0, tzinfo=HK))
    sched.tick()
    assert store.plan_session(DAY)["status"] == "done" and sent == []


def test_evening_job_leaves_a_day_without_sets(store):
    store.set(f"sent:session:{DAY}", "1")
    Scheduler(store, [].append, now=Clock(datetime(2026, 11, 17, 21, 30, tzinfo=HK))).tick()
    assert store.plan_session(DAY)["status"] == "approved"


# (7) the message is read with the chat and the session in view

def test_sorting_call_sees_chat_lines_and_session_state(store):
    reports.log_report(store, DAY, [{"exercise": "Press", "weight_kg": 20, "reps": 10}])
    store.add_chat("2026-11-17T16:58:00+08:00", "in", "press 10")
    store.add_chat("2026-11-17T16:58:02+08:00", "out", "Press: 20 kg x 10. 1 set left.",
                   delivered=False)
    router, fake = build(store, [json.dumps({"intent": "question"}), "Sure."])[1:]
    router.handle("did you get that?")
    for call in fake.calls:
        prompt = call["messages"][0]["content"]
        prompt = prompt if isinstance(prompt, str) else json.dumps(prompt)
        assert "Bot (NOT delivered): Press: 20 kg x 10. 1 set left." in prompt
        assert "Brian: press 10" in prompt
        assert "Press: 1 of 2 sets logged (20 kg x 10) <- shown now" in prompt


def test_repeated_report_after_undelivered_reply_logs_once(store):
    tg = FlakyTelegram(fail=1)
    app, _, _ = build(store, [report("Press", 10), report("Press", 10)], tg)
    say(app, "press 10", 1)
    say(app, "press 10", 2)
    assert len(store.logged_sets(DAY)) == 1
    assert tg.sent[0][1].startswith("(late) ")
    assert "already logged" in tg.sent[1][1].lower()


def test_repeat_intent_logs_nothing(store):
    reports.log_report(store, DAY, [{"exercise": "Press", "weight_kg": 20, "reps": 10}])
    router = build(store, [json.dumps({"intent": "repeat"})])[1]
    reply = router.handle("I already told you, press 10")
    assert len(store.logged_sets(DAY)) == 1 and "Press: 20 kg x 10" in reply


def test_same_again_logs_the_last_set_again_without_a_call(store):
    reports.log_report(store, DAY, [{"exercise": "Press", "weight_kg": 22.5, "reps": 9}])
    router, fake = build(store, [])[1:]
    reply = router.handle("same again")
    rows = store.logged_sets(DAY)
    assert [(r["exercise"], r["weight_kg"], r["reps"]) for r in rows] == [
        ("Press", 22.5, 9), ("Press", 22.5, 9)]
    assert fake.calls == [] and "Session" not in reply


def test_unplaced_message_gets_one_question_and_no_change(store):
    router = build(store, [json.dumps({"intent": "unclear",
                                       "question": "Which exercise was that for?"})])[1]
    assert router.handle("the other one") == "Which exercise was that for?"
    assert store.logged_sets(DAY) == []


def test_propose_uses_the_kept_note(store):
    store.set("pending:plan_change", "less leg work")
    router, fake = build(store, ["not json", "not json"])[1:]
    router.handle("/propose")  # the model's answer is rejected; only the prompt matters here
    assert "less leg work" in json.dumps(fake.calls[0]["messages"])
    assert store.get("pending:plan_change") in ("", "less leg work")


def test_same_again_keeps_an_exercise_outside_the_plan(store):
    reports.log_report(store, DAY, [{"exercise": "Plank", "weight_kg": None, "reps": 60}])
    build(store, [])[1].handle("same again")
    assert [r["exercise"] for r in store.logged_sets(DAY)] == ["Plank", "Plank"]
