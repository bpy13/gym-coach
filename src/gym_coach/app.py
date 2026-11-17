"""The long-running program: poll loop and scheduler in one process, one instance at a time."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from gym_coach.albums import exercise_parts, session_parts
from gym_coach.boot import AlreadyRunning, InstanceLock, setup_logging, start  # noqa: F401
from gym_coach.config import Config
from gym_coach.illustrations import Illustrations
from gym_coach.llm import HK, Claude, LazyAnthropic
from gym_coach.messages import exercise_line
from gym_coach.router import Router
from gym_coach.scheduler import Scheduler
from gym_coach.store import Store
from gym_coach.telegram import TelegramClient, TelegramError

log = logging.getLogger(__name__)
RESTART_PAUSE_S = 30.0
CHAT_DAYS = 30  # chat text kept this long (orchestrator, 2026-11-17)
LATE = "(late) "
PHOTO_FAILED = "I could not fetch that photo from Telegram. Please send it again."


class App:
    def __init__(self, telegram, router: Router, store: Store, chat_id: int | None = None,
                 parts_for=None, exercise_for=None, now=None):
        self.parts_for = parts_for  # session -> [(text, [jpeg bytes])], one per message
        self.exercise_for = exercise_for  # (session, index) -> (caption, [jpeg bytes])
        self.telegram = telegram
        self.router = router
        self.store = store
        self.chat_id = chat_id
        self._count = [0, 0]  # messages and pictures sent since the last reset
        self._now = now or getattr(router, "_now", None) or (lambda: datetime.now(HK))
        self._send_lock = threading.RLock()  # the poll loop and the scheduler both send

    def _stamp(self) -> str:
        return self._now().astimezone(HK).isoformat(timespec="seconds")

    def handle(self, incoming) -> None:
        """Reply to one incoming message: a meal photo (kept in memory only) or text.
        Logs one line on receipt (kind and length, never the text) and one when replied."""
        started = time.monotonic()
        self._count = [0, 0]
        if incoming.photo_file_id:
            log.info("received photo (caption %d chars)", len(incoming.caption or ""))
        else:
            log.info("received text (%d chars)", len((incoming.text or "").strip()))
        try:
            self.store.prune_chat(
                (self._now().astimezone(HK) - timedelta(days=CHAT_DAYS)).isoformat())
            self._handle(incoming)
        finally:
            log.info("replied: %d messages, %d pictures, %.1f s after receipt",
                     self._count[0], self._count[1], time.monotonic() - started)

    def _text(self, chat_id: int, text: str, kind: str = "text") -> None:
        """Send and record a text. A text that fails (after the client's own tries) stays
        recorded as not delivered; kind "text" is then sent first, marked (late), by the next
        send that works today. Raises when the send fails."""
        with self._send_lock:
            self._send_late(chat_id)
            row = self.store.add_chat(self._stamp(), "out", text, delivered=False, kind=kind)
            self.telegram.send_message(chat_id, text)
            self.store.set_chat_delivered(row)
            self._count[0] += 1

    def _pictures(self, chat_id: int, images: list, caption: str) -> None:
        with self._send_lock:
            self._send_late(chat_id)
            row = self.store.add_chat(self._stamp(), "out", caption, delivered=False,
                                      kind="pictures")
            self.telegram.send_pictures(chat_id, images, caption)
            self.store.set_chat_delivered(row)
            self._count[0] += 1
            self._count[1] += len(images)

    def _send_late(self, chat_id: int) -> None:
        """Today's texts that never reached Telegram, oldest first, each marked (late).
        Stops at the first failure; the rest wait for the next send."""
        today = self._now().astimezone(HK).date().isoformat()
        for row in self.store.undelivered_texts(today):
            try:
                self.telegram.send_message(chat_id, LATE + row["text"])
            except TelegramError:
                log.warning("late reply still not sent; kept for the next send")
                return
            self.store.set_chat_delivered(row["id"], late=True)
            self._count[0] += 1
            log.info("sent a late reply")

    def _record_in(self, received: str, text: str) -> None:
        try:
            self.store.add_chat(received, "in", text)
        except Exception:
            log.exception("recording the message failed")

    def _handle(self, incoming) -> None:
        self.store.set("chat_id", str(incoming.chat_id))
        self.chat_id = incoming.chat_id
        received = self._stamp()
        if incoming.photo_file_id:
            try:
                jpeg = self.telegram.download_file(incoming.photo_file_id)
            except Exception:
                log.exception("downloading the photo failed")
                self._record_in(received, "[photo, not fetched]")
                self._text(incoming.chat_id, PHOTO_FAILED)
                return
            try:
                reply = self.router.handle_photo(jpeg, incoming.caption)
            finally:
                self._record_in(received, ("[photo] " + (incoming.caption or "")).strip())
            self._text(incoming.chat_id, reply)
            return
        text = (incoming.text or "").strip()
        if not text:
            self._record_in(received, "[not text]")
            self._text(incoming.chat_id, "I can only read text for now.")
            return
        try:  # recorded after the router read it, so its chat lines end before this one
            reply = self.router.handle(text)
        finally:
            self._record_in(received, text)
        if text.split()[0].lower() == "/start" and not self._has_upcoming_plan():
            reply += "\n\n" + self.router.handle("/propose")
        session = self.router.pop_album_session()
        if session and self.parts_for:
            try:  # a preview of the first strength day, one message per exercise
                self.send_parts(incoming.chat_id, self.parts_for(session, closing=False))
            except Exception:
                log.exception("sending the proposal's pictures failed")
        shown = self.router.pop_exercise()  # taken before the send, so a failure keeps no state
        try:
            self._text(incoming.chat_id, reply)
        except Exception:
            log.exception("sending the reply failed")  # the exercise below still goes out
        if shown is not None:
            # the exercise the router just moved to, after its short reply, so he reads it
            # while resting
            self.send_exercise(incoming.chat_id, *shown)

    def send_exercise(self, chat_id: int, session: dict, index: int) -> None:
        try:
            part = (self.exercise_for(session, index) if self.exercise_for
                    else (exercise_line(session["exercises"][index]), []))
        except Exception:
            log.exception("building the exercise message failed; sending its name")
            ex = session["exercises"][index]
            try:
                part = (exercise_line(ex), [])
            except (KeyError, TypeError, ValueError):
                part = (str(ex.get("name", "Next exercise")), [])
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
        text alone. A picture that fails to send falls back to its caption as text; a part
        that cannot be sent at all is logged and skipped, so later parts still go out."""
        for text, images in parts:
            try:
                if images:
                    try:
                        self._pictures(chat_id, images, text)
                        continue
                    except Exception:
                        log.exception("sending pictures failed; sending the text")
                self._text(chat_id, text)
                if images:
                    log.info("sent the text in place of the pictures")
            except Exception:
                log.exception("sending a message part failed; going on")

    def send_exercise_to_owner(self, session: dict, index: int) -> None:
        chat = self.chat_id or int(self.store.get("chat_id") or 0)
        if chat:
            self.send_exercise(chat, session, index)

    def send_to_owner(self, text: str) -> None:
        chat = self.chat_id or int(self.store.get("chat_id") or 0)
        if chat:  # the scheduler retries a failed one itself, so it is not sent late
            self._text(chat, text, kind="scheduled")
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
