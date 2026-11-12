"""Minimal Telegram Bot API client: long polling, sending text, downloading files."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

log = logging.getLogger(__name__)

MAX_MESSAGE_CHARS = 4000
MAX_PHOTO_EDGE = 1280
POLL_TIMEOUT_S = 50
RETRY_PAUSE_S = 5.0
# Explicit per-phase limits: the read limit must outlast the long poll by a margin.
HTTP_TIMEOUT = httpx.Timeout(connect=10, read=POLL_TIMEOUT_S + 10, write=10, pool=10)


def new_http_client() -> httpx.Client:
    """No pooled keep-alive sockets: every call opens a fresh connection, so a dead idle
    socket can never be reused for the next long poll."""
    return httpx.Client(
        timeout=HTTP_TIMEOUT,
        limits=httpx.Limits(max_keepalive_connections=0),
        headers={"Connection": "close"},
    )
PAIRED_REPLY = "Paired with this account. I will answer only you."


class TelegramError(Exception):
    """A Telegram call failed. The message never contains the bot token."""


@dataclass(frozen=True)
class Incoming:
    update_id: int
    chat_id: int
    text: str | None = None
    photo_file_id: str | None = None
    caption: str | None = None


def pick_photo(sizes: list[dict]) -> str | None:
    """File id of the largest size whose long edge is at most 1280 px (smallest if none fit)."""
    if not sizes:
        return None
    fitting = [s for s in sizes if max(s.get("width", 0), s.get("height", 0)) <= MAX_PHOTO_EDGE]
    if fitting:
        best = max(fitting, key=lambda s: s["width"] * s["height"])
    else:
        best = min(sizes, key=lambda s: s["width"] * s["height"])
    return best["file_id"]


def split_text(text: str, limit: int = MAX_MESSAGE_CHARS) -> list[str]:
    """Split text into chunks of at most `limit` characters, preferring line breaks."""
    chunks: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text or not chunks:
        chunks.append(text)
    return chunks


class TelegramClient:
    def __init__(
        self,
        token: str,
        allowed_user_id: int | None,
        *,
        on_pair: Callable[[int], None] | None = None,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        offset: int | None = None,
    ) -> None:
        self._token = token
        self._allowed = allowed_user_id  # None until the first private message pairs
        self._on_pair = on_pair
        self._http = client or new_http_client()
        self._sleep = sleep
        self.offset = offset  # next update_id to ask for; the caller may persist it

    def _url(self, method: str) -> str:
        return f"https://api.telegram.org/bot{self._token}/{method}"

    def _call(self, method: str, payload: dict) -> list | dict:
        try:
            resp = self._http.post(self._url(method), json=payload)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            # Never include the URL (it holds the token) in the log or the error.
            raise TelegramError(f"{method} failed: {type(exc).__name__}") from None
        if not data.get("ok"):
            raise TelegramError(f"{method} failed: {data.get('description', 'unknown error')}")
        return data["result"]

    def get_updates(self) -> list[Incoming]:
        """One long poll. A network error is logged, followed by a pause, and gives []."""
        payload: dict = {"timeout": POLL_TIMEOUT_S, "allowed_updates": ["message"]}
        if self.offset is not None:
            payload["offset"] = self.offset
        try:
            raw = self._call("getUpdates", payload)
        except TelegramError as exc:
            log.warning("%s; retrying after a pause", exc)
            self._sleep(RETRY_PAUSE_S)
            return []
        out: list[Incoming] = []
        for upd in raw:
            self.offset = upd["update_id"] + 1
            msg = upd.get("message")
            if not msg:
                continue
            sender = msg.get("from", {}).get("id")
            if (self._allowed is None and sender is not None
                    and msg.get("chat", {}).get("type") == "private"):
                self._allowed = sender
                if self._on_pair:
                    self._on_pair(sender)
                log.info("owner paired")
                self.send_message(msg["chat"]["id"], PAIRED_REPLY)
            if sender is None or sender != self._allowed:
                continue
            out.append(
                Incoming(
                    update_id=upd["update_id"],
                    chat_id=msg["chat"]["id"],
                    text=msg.get("text"),
                    photo_file_id=pick_photo(msg.get("photo", [])),
                    caption=msg.get("caption"),
                )
            )
        return out

    def send_message(self, chat_id: int, text: str) -> None:
        for chunk in split_text(text):
            self._call("sendMessage", {"chat_id": chat_id, "text": chunk})

    def download_file(self, file_id: str) -> bytes:
        info = self._call("getFile", {"file_id": file_id})
        url = f"https://api.telegram.org/file/bot{self._token}/{info['file_path']}"
        try:
            resp = self._http.get(url)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise TelegramError(f"download failed: {type(exc).__name__}") from None
        return resp.content
