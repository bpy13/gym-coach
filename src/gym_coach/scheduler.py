"""Time-triggered messages: a loop checks due jobs each minute; kv markers prevent repeats."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from gym_coach.messages import session_message

log = logging.getLogger(__name__)


class Scheduler:
    """`send(text)` delivers a message to Brian. `now()` returns an aware datetime."""

    def __init__(self, store, send, session_time: str = "07:00",
                 timezone: str = "Asia/Hong_Kong", now=None,
                 album_for=None, send_album=None):
        self.store = store
        self.send = send
        self._album_for = album_for  # session -> [(jpeg bytes, caption)]
        self._send_album = send_album
        self.session_time = session_time
        self._tz = ZoneInfo(timezone)
        self._now = now or (lambda: datetime.now(self._tz))

    def tick(self) -> None:
        """Run every job that is due now and has not run today."""
        now = self._now().astimezone(self._tz)
        if now.strftime("%H:%M") >= self.session_time:  # zero-padded, so text order = time order
            self._send_session(now.date().isoformat())

    def _send_session(self, day: str) -> None:
        marker = f"sent:session:{day}"
        if self.store.get(marker):
            return
        session = self.store.plan_session(day)
        if not session or session["status"] != "approved":
            return
        self._try_album(session)
        self.send(session_message(session))
        # Marked after the send: a crash in between may repeat a message, never lose one.
        self.store.set(marker, "1")

    def _try_album(self, session: dict) -> None:
        """Machine photos first; a failure here never blocks the text."""
        if not (self._album_for and self._send_album):
            return
        try:
            album = self._album_for(session)
            if album:
                self._send_album(album)
        except Exception:
            log.exception("sending the session's photos failed")

    def run(self, should_stop=lambda: False, interval: float = 60.0) -> None:
        while not should_stop():
            try:
                self.tick()
            except Exception:  # keep the loop alive; the next minute retries
                log.exception("scheduler tick failed")
            time.sleep(interval)
