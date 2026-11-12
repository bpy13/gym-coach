import pytest

from fakes import FakeTelegram
from gym_coach import __main__ as entry
from gym_coach.app import AlreadyRunning, App, InstanceLock, run_forever
from gym_coach.store import Store
from gym_coach.telegram import Incoming


class StubRouter:
    def __init__(self):
        self.seen = []

    def handle(self, text):
        self.seen.append(text)
        return f"re:{text}"

    def pop_album_session(self):
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
