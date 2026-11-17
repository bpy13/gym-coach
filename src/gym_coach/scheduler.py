"""Time-triggered messages: a loop checks due jobs each minute; kv markers prevent repeats."""

from __future__ import annotations

import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from gym_coach import reports
from gym_coach.messages import list_message

log = logging.getLogger(__name__)
CLOSE_DAY_TIME = "21:00"  # a day with sets logged is marked done (orchestrator, 2026-11-17)


class Scheduler:
    """`send(text)` delivers a message to Brian. `now()` returns an aware datetime."""

    def __init__(self, store, send, session_time: str = "07:00",
                 timezone: str = "Asia/Hong_Kong", now=None,
                 send_exercise=None):
        self.store = store
        self.send = send
        self._send_exercise = send_exercise  # (session, index): exercise message
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
        if now.strftime("%H:%M") >= CLOSE_DAY_TIME:
            self._close_day(now.date().isoformat())

    def _close_day(self, day: str) -> None:
        """Silently mark the day done when sets were logged but the flow never closed, and
        close a workout he never ended."""
        if reports.mark_done(self.store, day):
            log.info("day closed at the evening check")
        if reports.close_workout(self.store, day):
            log.info("workout closed at the evening check")

    def _send_body_prompt(self, day: str) -> None:
        marker = f"sent:body:{day}"
        if self.store.get(marker):
            return
        self.send('Weekly check-in: what is your body weight today? '
                  'Reply like "81.6 kg".')
        self.store.set(marker, "1")

    def _send_session(self, day: str) -> None:
        marker = f"sent:session:{day}"
        if self.store.get(marker):
            return
        session = self.store.plan_session(day)
        if not session or session["status"] != "approved":
            return
        self.send(list_message(session))
        if session["kind"] == "strength" and session["exercises"]:
            if self._send_exercise:  # the first exercise right after the list
                self._send_exercise(session, 0)
            self.store.set(f"flow:{day}", "0")  # the router shows the next one per reply
        # Marked after the send: a crash in between may repeat a message, never lose one.
        self.store.set(marker, "1")

    def run(self, should_stop=lambda: False, interval: float = 60.0) -> None:
        while not should_stop():
            try:
                self.tick()
            except Exception:  # keep the loop alive; the next minute retries
                log.exception("scheduler tick failed")
            time.sleep(interval)
