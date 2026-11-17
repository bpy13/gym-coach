import pytest

from fakes import FakeTelegram
from gym_coach import __main__ as entry
from gym_coach.app import AlreadyRunning, App, InstanceLock, run_forever
from gym_coach.store import Store
from gym_coach.telegram import Incoming, TelegramError


class StubRouter:
    def __init__(self):
        self.seen = []

    def handle(self, text):
        self.seen.append(text)
        return f"re:{text}"

    def pop_album_session(self):
        return None

    def pop_exercise(self):
        return None

    def _today(self):
        from datetime import date
        return date(2026, 11, 16)


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def test_start_without_plan_runs_proposal(store):
    tg, router = FakeTelegram(), StubRouter()
    App(tg, router, store).handle(Incoming(1, 5, text="/start"))
    assert router.seen == ["/start", "/propose"]
    assert tg.sent[0][0] == 5


def test_start_with_plan_does_not_propose(store):
    store.add_plan_session("2026-11-17", "home", "strength", "approved", [])
    tg, router = FakeTelegram(), StubRouter()
    App(tg, router, store).handle(Incoming(1, 5, text="/start"))
    assert router.seen == ["/start"]


def test_poll_once_survives_handler_error_and_send_to_owner(store):
    class Boom(StubRouter):
        def handle(self, text):
            raise RuntimeError("x")
    tg = FakeTelegram([Incoming(1, 5, text="hi")])
    app = App(tg, Boom(), store)
    app.poll_once()  # no raise
    app.send_to_owner("session")
    assert tg.sent == [(5, "session")]


def test_second_instance_refused(tmp_path):
    a, b = InstanceLock(tmp_path / "l"), InstanceLock(tmp_path / "l")
    a.acquire()
    with pytest.raises(AlreadyRunning):
        b.acquire()
    a.release()
    b.acquire()
    b.release()


def test_run_forever_pauses_after_error(store):
    calls, pauses = [], []

    class Flaky:
        def poll_once(self):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("boom")

    class NoSched:
        def run(self, should_stop):
            pass

    run_forever(Flaky(), NoSched(), should_stop=lambda: len(calls) >= 2, sleep=pauses.append)
    assert pauses == [30.0] and len(calls) == 2


def test_check_names_missing_key(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    for k in ("TELEGRAM_BOT_TOKEN", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    assert entry.main(["--check"]) == 1
    assert "TELEGRAM_BOT_TOKEN" in capsys.readouterr().out


def test_check_ok(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_ID", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert entry.main(["--check"]) == 0
    assert "config ok" in capsys.readouterr().out


def test_check_owner_not_paired(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_ID", "")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    assert entry.main(["--check"]) == 0
    assert "config ok (owner not paired yet)" in capsys.readouterr().out


def test_logon_task_starts_pythonw_directly():
    """Task Scheduler's stop only ends the process it started, so nothing may sit in between."""
    from pathlib import Path
    scripts = Path(__file__).resolve().parent.parent / "scripts"
    text = (scripts / "install-logon-task.ps1").read_text(encoding="utf-8")
    action = next(ln for ln in text.splitlines() if "New-ScheduledTaskAction" in ln)
    assert "pythonw.exe" in text and "-m gym_coach" in text
    assert "conhost" not in action and "powershell" not in action.lower()
    assert "ExecutionPolicy" not in text
    assert not (scripts / "run-bot.ps1").exists()


def test_logon_task_runs_at_normal_priority():
    """Task 14e: the default priority 7 (below normal CPU, low disk) starved the start for
    48 minutes on a busy PC; 4 is normal."""
    import re
    from pathlib import Path
    scripts = Path(__file__).resolve().parent.parent / "scripts"
    text = (scripts / "install-logon-task.ps1").read_text(encoding="utf-8")
    assert re.search(r"New-ScheduledTaskSettingsSet[^\n]*`?\n?[^\n]*-Priority 4\b", text)


# Task 14f: one failing part never stops the text reply

class FailingTelegram(FakeTelegram):
    def __init__(self, *a, fail_pictures=False, fail_texts=(), fail_download=False, **kw):
        super().__init__(*a, **kw)
        self.fail_pictures, self.fail_texts, self.fail_download = (
            fail_pictures, set(fail_texts), fail_download)

    def send_pictures(self, chat_id, images, caption):
        if self.fail_pictures:
            raise TelegramError("send album failed: ConnectError")
        super().send_pictures(chat_id, images, caption)

    def send_message(self, chat_id, text):
        if text in self.fail_texts:
            raise TelegramError("sendMessage failed: ConnectError")
        super().send_message(chat_id, text)

    def download_file(self, file_id):
        if self.fail_download:
            raise TelegramError("download failed: ConnectError")
        return super().download_file(file_id)


class FlowRouter(StubRouter):
    """Each reply moves on to exercise 1 of a two-exercise session."""
    def __init__(self):
        super().__init__()
        self._next = None
        self.session = {"exercises": [{"name": "Squat"}, {"name": "Row"}]}

    def handle(self, text):
        self._next = (self.session, 1)
        return super().handle(text)

    def pop_exercise(self):
        shown, self._next = self._next, None
        return shown


def test_failing_album_still_sends_the_text(store):
    tg = FailingTelegram(fail_pictures=True)
    app = App(tg, FlowRouter(), store, exercise_for=lambda s, i: ("Row 3x10", [b"jpg"]))
    app.handle(Incoming(1, 5, text="done"))
    assert tg.sent == [(5, "re:done"), (5, "Row 3x10")]


def test_failing_exercise_message_still_sends_the_reply(store):
    tg = FailingTelegram(fail_pictures=True, fail_texts={"Row 3x10"})
    app = App(tg, FlowRouter(), store, exercise_for=lambda s, i: ("Row 3x10", [b"jpg"]))
    app.handle(Incoming(1, 5, text="done"))  # no raise
    assert tg.sent == [(5, "re:done")]


def test_broken_exercise_builder_still_sends_the_reply(store):
    def boom(s, i):
        raise RuntimeError("x")
    tg = FakeTelegram()
    app = App(tg, FlowRouter(), store, exercise_for=boom)
    app.handle(Incoming(1, 5, text="done"))
    assert tg.sent[0] == (5, "re:done") and len(tg.sent) == 2


def test_failing_photo_download_still_answers(store):
    tg = FailingTelegram(fail_download=True)
    App(tg, StubRouter(), store).handle(Incoming(1, 5, photo_file_id="f"))
    assert len(tg.sent) == 1 and "photo" in tg.sent[0][1].lower()


def test_failing_part_does_not_stop_later_parts(store):
    tg = FailingTelegram(fail_pictures=True, fail_texts={"one"})
    App(tg, StubRouter(), store).send_parts(5, [("one", [b"x"]), ("two", [b"y"]), ("three", [])])
    assert tg.sent == [(5, "two"), (5, "three")]


def test_one_log_line_per_message_and_per_reply(store, caplog):
    import logging
    caplog.set_level(logging.INFO, logger="gym_coach.app")
    tg = FakeTelegram()
    app = App(tg, FlowRouter(), store, exercise_for=lambda s, i: ("Row 3x10", [b"a", b"b"]))
    app.handle(Incoming(1, 5, text="squat 40 kg 10 10 10"))
    lines = [r.getMessage() for r in caplog.records]
    assert any(m == "received text (20 chars)" for m in lines)
    sent = [m for m in lines if m.startswith("replied:")]
    assert len(sent) == 1 and "2 messages" in sent[0] and "2 pictures" in sent[0]
    assert "squat" not in " ".join(lines)


def test_failing_reply_still_sends_the_exercise(store):
    tg = FailingTelegram(fail_texts={"re:done"})
    app = App(tg, FlowRouter(), store, exercise_for=lambda s, i: ("Row 3x10", [b"jpg"]))
    app.handle(Incoming(1, 5, text="done"))  # no raise
    assert tg.pictures == [(5, [b"jpg"], "Row 3x10")]
