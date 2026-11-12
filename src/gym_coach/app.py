"""The long-running program: poll loop and scheduler in one process, one instance at a time."""

from __future__ import annotations

import logging
import logging.handlers
import os
import threading
import time
from datetime import timedelta
from pathlib import Path

from gym_coach.config import Config
from gym_coach.llm import Claude
from gym_coach.router import Router
from gym_coach.scheduler import Scheduler
from gym_coach.store import Store
from gym_coach.telegram import TelegramClient

log = logging.getLogger(__name__)
RESTART_PAUSE_S = 30.0


class AlreadyRunning(Exception):
    """Another instance holds the lock file."""


class InstanceLock:
    """Exclusive lock file in the data folder; the OS drops it when the process ends."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._fh = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+b")  # noqa: SIM115 - kept open for the process lifetime
        try:
            if os.name == "nt":
                import msvcrt
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            raise AlreadyRunning(str(self.path)) from None
        self._fh = fh

    def release(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None


class App:
    def __init__(self, telegram, router: Router, store: Store, chat_id: int | None = None):
        self.telegram = telegram
        self.router = router
        self.store = store
        self.chat_id = chat_id

    def handle(self, incoming) -> None:
        """Reply to one incoming message. Photos are not handled yet (milestone 2)."""
        self.store.set("chat_id", str(incoming.chat_id))
        self.chat_id = incoming.chat_id
        text = (incoming.text or "").strip()
        if not text:
            self.telegram.send_message(incoming.chat_id, "I can only read text for now.")
            return
        reply = self.router.handle(text)
        if text.split()[0].lower() == "/start" and not self._has_upcoming_plan():
            reply += "\n\n" + self.router.handle("/propose")
        self.telegram.send_message(incoming.chat_id, reply)

    def _has_upcoming_plan(self) -> bool:
        today = self.router._today()
        return bool(self.store.plan_sessions(today.isoformat(),
                                             (today + timedelta(days=21)).isoformat()))

    def poll_once(self) -> None:
        for incoming in self.telegram.get_updates():
            try:
                self.handle(incoming)
            except Exception:
                log.exception("handling a message failed")

    def send_to_owner(self, text: str) -> None:
        chat = self.chat_id or int(self.store.get("chat_id") or 0)
        if chat:
            self.telegram.send_message(chat, text)
        else:
            log.warning("no chat known yet; message not sent")


def run_forever(app: App, scheduler: Scheduler, should_stop=lambda: False,
                sleep=time.sleep) -> None:
    """Scheduler in a thread; poll loop here. An unexpected error pauses 30 s, then retries."""
    threading.Thread(target=scheduler.run, args=(should_stop,), daemon=True).start()
    while not should_stop():
        try:
            app.poll_once()
        except Exception:
            log.exception("poll loop failed; restarting in %s s", RESTART_PAUSE_S)
            sleep(RESTART_PAUSE_S)


def setup_logging(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        data_dir / "bot.log", maxBytes=500_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its URLs hold the bot token


def build(config: Config) -> tuple[App, Scheduler, Store]:
    import anthropic
    data = Path(config.data_dir)
    store = Store(data / "gym.db")
    claude = Claude(anthropic.Anthropic(api_key=config.anthropic_api_key), store,
                    config.monthly_ceiling_usd)
    router = Router(store, claude, config.model_fast, config.model_coach)
    telegram = TelegramClient(config.telegram_bot_token, config.telegram_allowed_user_id)
    app = App(telegram, router, store)
    scheduler = Scheduler(store, app.send_to_owner, config.session_time, config.timezone)
    return app, scheduler, store


def main(config: Config) -> None:
    data = Path(config.data_dir)
    lock = InstanceLock(data / "bot.lock")
    lock.acquire()  # raises AlreadyRunning
    setup_logging(data)
    app, scheduler, store = build(config)
    log.info("bot started")
    try:
        run_forever(app, scheduler)
    finally:
        store.close()
        lock.release()
