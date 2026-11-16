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
                 parts_for=None, send_parts=None):
        self.store = store
        self.send = send
        self._parts_for = parts_for  # session -> [(text, [jpeg bytes])], one per message
        self._send_parts = send_parts
        self.session_time = session_time
        self._tz = ZoneInfo(timezone)
        self._now = now or (lambda: datetime.now(self._tz))

    def tick(self) -> None:
        """Run every job that is due now and has not run today."""
        now = self._now().astimezone(self._tz)
        if now.strftime("%H:%M") >= self.session_time:  # zero-padded, so text order = time order
            self._send_session(now.date().isoformat())
            if now.weekday() == 0:  # Monday
                self._send_body_prompt(now.date().isoformat())

    def _send_body_prompt(self, day: str) -> None:
        marker = f"sent:body:{day}"
        if self.store.get(marker):
            return
        self.send('Weekly check-in: what is your body weight and waist today? '
                  'Reply like "81.6 kg, waist 91".')
        self.store.set(marker, "1")

    def _send_session(self, day: str) -> None:
        marker = f"sent:session:{day}"
        if self.store.get(marker):
            return
        session = self.store.plan_session(day)
        if not session or session["status"] != "approved":
            return
        self._send_session_messages(session)
        # Marked after the send: a crash in between may repeat a message, never lose one.
        self.store.set(marker, "1")

    def _send_session_messages(self, session: dict) -> None:
        """One message per exercise with its pictures; if they cannot be built, the plain text."""
        if self._parts_for and self._send_parts:
            try:
                parts = self._parts_for(session)
            except Exception:
                log.exception("building the session's messages failed; sending text")
            else:
                self._send_parts(parts)
                return
        self.send(session_message(session))

    def run(self, should_stop=lambda: False, interval: float = 60.0) -> None:
        while not should_stop():
            try:
                self.tick()
            except Exception:  # keep the loop alive; the next minute retries
                log.exception("scheduler tick failed")
            time.sleep(interval)
