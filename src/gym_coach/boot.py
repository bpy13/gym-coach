"""The first steps of a start: lock, log file, a "starting" line (standard library only).

`__main__` runs this before importing the rest of the program, so `data\bot.log` shows the
start even when later imports are slow (Task 14e: on a busy PC, importing the anthropic SDK
took minutes and the log stayed silent).
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

log = logging.getLogger("gym_coach.app")


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


def setup_logging(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        data_dir / "bot.log", maxBytes=500_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its URLs hold the bot token


def start(config) -> InstanceLock:
    """Take the lock (raises AlreadyRunning), open the log, write "starting"."""
    data = Path(config.data_dir)
    lock = InstanceLock(data / "bot.lock")
    lock.acquire()
    setup_logging(data)
    log.info("starting (pid %s)", os.getpid())
    return lock
