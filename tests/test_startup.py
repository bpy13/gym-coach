"""Task 14e: the start logs a first line before anything slow, and never waits on the
anthropic import (2,800 modules; minutes on a busy PC)."""

import logging
import sys
import threading

import pytest

from gym_coach.config import Config


@pytest.fixture
def clean_root_logger():
    root = logging.getLogger()
    before = list(root.handlers)
    yield
    for h in list(root.handlers):
        if h not in before:
            root.removeHandler(h)
            h.close()


def _config(tmp_path):
    return Config(telegram_bot_token="0:fake", anthropic_api_key="fake",
                  telegram_allowed_user_id=1, data_dir=str(tmp_path / "data"),
                  photos_dir=str(tmp_path / "photos"))


def test_boot_logs_starting_before_the_app_is_built(tmp_path, clean_root_logger):
    from gym_coach import boot
    lock = boot.start(_config(tmp_path))
    try:
        log_text = (tmp_path / "data" / "bot.log").read_text(encoding="utf-8")
        assert "starting" in log_text
    finally:
        lock.release()


def test_boot_needs_only_the_standard_library():
    from pathlib import Path

    from gym_coach import boot
    source = Path(boot.__file__).read_text(encoding="utf-8")
    for heavy in ("anthropic", "httpx", "PIL", "gym_coach.app", "gym_coach.store"):
        assert f"import {heavy}" not in source and f"from {heavy}" not in source


def test_build_does_not_import_anthropic(tmp_path, monkeypatch):
    from gym_coach import app
    monkeypatch.setitem(sys.modules, "anthropic", None)  # any import now raises
    bot, _scheduler, store = app.build(_config(tmp_path))
    try:
        assert bot.router.claude is not None
    finally:
        store.close()


def test_lazy_client_loads_once_on_first_use():
    from gym_coach.llm import LazyAnthropic
    made = []

    class Fake:
        messages = "the messages api"

    def factory():
        made.append(1)
        return Fake()

    lazy = LazyAnthropic(factory)
    assert made == []
    threads = [threading.Thread(target=lambda: lazy.messages) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert lazy.messages == "the messages api"
    assert made == [1]


def test_lazy_client_retries_after_a_failed_load():
    from gym_coach.llm import LazyAnthropic
    calls = []

    class Fake:
        messages = "ok"

    def factory():
        calls.append(1)
        if len(calls) == 1:
            raise ImportError("slow disk")
        return Fake()

    lazy = LazyAnthropic(factory)
    with pytest.raises(ImportError):
        lazy.load()
    assert lazy.messages == "ok"
