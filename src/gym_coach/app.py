"""The long-running program: poll loop and scheduler in one process, one instance at a time."""

from __future__ import annotations

import logging
import threading
import time
from datetime import timedelta
from pathlib import Path

from gym_coach.albums import exercise_parts, session_parts
from gym_coach.boot import AlreadyRunning, InstanceLock, setup_logging, start  # noqa: F401
from gym_coach.config import Config
from gym_coach.illustrations import Illustrations
from gym_coach.llm import Claude, LazyAnthropic
from gym_coach.messages import exercise_line
from gym_coach.router import Router
from gym_coach.scheduler import Scheduler
from gym_coach.store import Store
from gym_coach.telegram import TelegramClient

log = logging.getLogger(__name__)
RESTART_PAUSE_S = 30.0


class App:
    def __init__(self, telegram, router: Router, store: Store, chat_id: int | None = None,
                 parts_for=None, exercise_for=None):
        self.parts_for = parts_for  # session -> [(text, [jpeg bytes])], one per message
        self.exercise_for = exercise_for  # (session, index) -> (caption, [jpeg bytes])
        self.telegram = telegram
        self.router = router
        self.store = store
        self.chat_id = chat_id

    def handle(self, incoming) -> None:
        """Reply to one incoming message: a meal photo (kept in memory only) or text."""
        self.store.set("chat_id", str(incoming.chat_id))
        self.chat_id = incoming.chat_id
        if incoming.photo_file_id:
            jpeg = self.telegram.download_file(incoming.photo_file_id)
            self.telegram.send_message(
                incoming.chat_id, self.router.handle_photo(jpeg, incoming.caption))
            return
        text = (incoming.text or "").strip()
        if not text:
            self.telegram.send_message(incoming.chat_id, "I can only read text for now.")
            return
        reply = self.router.handle(text)
        if text.split()[0].lower() == "/start" and not self._has_upcoming_plan():
            reply += "\n\n" + self.router.handle("/propose")
        session = self.router.pop_album_session()
        if session and self.parts_for:
            try:  # a preview of the first strength day, one message per exercise
                self.send_parts(incoming.chat_id, self.parts_for(session, closing=False))
            except Exception:
                log.exception("sending the proposal's pictures failed")
        self.telegram.send_message(incoming.chat_id, reply)
        self._send_exercise(incoming.chat_id)

    def _send_exercise(self, chat_id: int) -> None:
        """The exercise the router just moved to, after its short reply, so he reads it
        while resting."""
        shown = self.router.pop_exercise()
        if shown is not None:
            self.send_exercise(chat_id, *shown)

    def send_exercise(self, chat_id: int, session: dict, index: int) -> None:
        try:
            part = (self.exercise_for(session, index) if self.exercise_for
                    else (exercise_line(session["exercises"][index]), []))
        except Exception:
            log.exception("building the exercise message failed; sending text")
            part = (exercise_line(session["exercises"][index]), [])
        self.send_parts(chat_id, [part])

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

    def send_parts(self, chat_id: int, parts) -> None:
        """Each part is (text, images): pictures with the text as their one caption, or the
        text alone. A picture that fails to send falls back to its caption as text."""
        for text, images in parts:
            if not images:
                self.telegram.send_message(chat_id, text)
                continue
            try:
                self.telegram.send_pictures(chat_id, images, text)
            except Exception:
                log.exception("sending pictures failed; sending the text")
                self.telegram.send_message(chat_id, text)

    def send_exercise_to_owner(self, session: dict, index: int) -> None:
        chat = self.chat_id or int(self.store.get("chat_id") or 0)
        if chat:
            self.send_exercise(chat, session, index)

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


def build(config: Config) -> tuple[App, Scheduler, Store]:
    data = Path(config.data_dir)
    store = Store(data / "gym.db")

    def make_client():
        import anthropic  # ~2,800 modules: minutes on a busy PC, so never on the start path
        return anthropic.Anthropic(api_key=config.anthropic_api_key)

    claude = Claude(LazyAnthropic(make_client), store, config.monthly_ceiling_usd)
    illustrations = Illustrations(data / "illustrations")
    router = Router(store, claude, config.model_fast, config.model_coach,
                    illustrations=illustrations)
    owner = config.telegram_allowed_user_id
    if owner is None and store.get("owner_id"):
        owner = int(store.get("owner_id"))
    telegram = TelegramClient(config.telegram_bot_token, owner,
                              on_pair=lambda uid: store.set("owner_id", str(uid)))
    def parts_for(session, closing=True):
        return session_parts(session, photos_dir=Path(config.photos_dir),
                             illustrations=illustrations, closing=closing,
                             show_tip=config.show_form_tip)

    def exercise_for(session, index):
        return exercise_parts(session, index, photos_dir=Path(config.photos_dir),
                              illustrations=illustrations, show_tip=config.show_form_tip)

    app = App(telegram, router, store, parts_for=parts_for, exercise_for=exercise_for)
    scheduler = Scheduler(store, app.send_to_owner, config.session_time, config.timezone,
                          send_exercise=app.send_exercise_to_owner)
    return app, scheduler, store


def warm_up(client) -> threading.Thread:
    """Load the Claude client in the background, so the first meal photo does not wait."""
    def load():
        try:
            client.load()
            log.info("claude client ready")
        except Exception:
            log.exception("loading the claude client failed; it retries on first use")

    thread = threading.Thread(target=load, name="claude-warm-up", daemon=True)
    thread.start()
    return thread


def main(config: Config, lock: InstanceLock | None = None) -> None:
    """`lock` comes from `boot.start` when `__main__` already wrote the "starting" line."""
    lock = lock or start(config)  # raises AlreadyRunning
    app, scheduler, store = build(config)
    log.info("bot started")
    warm_up(app.router.claude.client)
    try:
        run_forever(app, scheduler)
    finally:
        store.close()
        lock.release()
