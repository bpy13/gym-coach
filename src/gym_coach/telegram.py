"""Minimal Telegram Bot API client: long polling, sending text, downloading files."""

import json
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
# A send that could not connect is tried again after these pauses (4 tries in all). Only
# errors raised before the request left this PC are retried, so Telegram never gets it twice.
SEND_PAUSES_S = (1, 3, 8)
NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
# Explicit per-phase limits: the read limit must outlast the long poll by a margin.
HTTP_TIMEOUT = httpx.Timeout(connect=10, read=POLL_TIMEOUT_S + 10, write=10, pool=10)


KEEPALIVE_S = 30.0


def new_http_client() -> httpx.Client:
    """Kept connections, dropped after 30 s idle. Task 14f, 200 getMe calls each from this
    PC: a new connection per call failed 26-28 times in the TLS handshake (SSL
    UNEXPECTED_EOF_WHILE_READING), median 0.85 s; a kept one failed 0 times, median 0.28 s."""
    return httpx.Client(
        timeout=HTTP_TIMEOUT,
        limits=httpx.Limits(max_keepalive_connections=2, keepalive_expiry=KEEPALIVE_S),
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

    def _cause(self, exc: Exception) -> str:
        """Error name and cause text, without the token (the URL holds it)."""
        text = str(exc).replace(self._token, "<token>")
        return f"{type(exc).__name__} ({text[:160]})" if text else type(exc).__name__

    def _request(self, what: str, send: Callable[[], httpx.Response],
                 retry: bool = True) -> httpx.Response:
        """`send()` once, or again after a pause while it fails to connect."""
        pauses = SEND_PAUSES_S if retry else ()
        for attempt in range(len(pauses) + 1):
            try:
                resp = send()
                resp.raise_for_status()
                return resp
            except NOT_SENT as exc:
                if attempt == len(pauses):
                    raise TelegramError(f"{what} failed: {self._cause(exc)}") from None
                log.warning("%s could not connect: %s; try %d of %d in %g s", what,
                            self._cause(exc), attempt + 2, len(pauses) + 1, pauses[attempt])
                self._sleep(pauses[attempt])
            except httpx.HTTPError as exc:
                # Never include the URL (it holds the token) in the log or the error.
                raise TelegramError(f"{what} failed: {self._cause(exc)}") from None
        raise AssertionError("unreachable")

    def _call(self, method: str, payload: dict, retry: bool = True) -> list | dict:
        resp = self._request(method, lambda: self._http.post(self._url(method), json=payload),
                             retry)
        try:
            data = resp.json()
        except ValueError:
            raise TelegramError(f"{method} failed: bad JSON") from None
        if not data.get("ok"):
            raise TelegramError(f"{method} failed: {data.get('description', 'unknown error')}")
        return data["result"]

    def get_updates(self) -> list[Incoming]:
        """One long poll. A network error is logged, followed by a pause, and gives []."""
        payload: dict = {"timeout": POLL_TIMEOUT_S, "allowed_updates": ["message"]}
        if self.offset is not None:
            payload["offset"] = self.offset
        try:
            raw = self._call("getUpdates", payload, retry=False)  # the poll loop retries
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

    def send_message(self, chat_id: int, text: str, reply_markup: dict | None = None) -> None:
        """`reply_markup`: a reply keyboard to show (or remove), sent with the last chunk."""
        chunks = split_text(text)
        for i, chunk in enumerate(chunks):
            payload = {"chat_id": chat_id, "text": chunk}
            if reply_markup is not None and i == len(chunks) - 1:
                payload["reply_markup"] = reply_markup
            self._call("sendMessage", payload)

    def send_chat_action(self, chat_id: int, action: str = "typing") -> None:
        """Show "typing..." in his chat (about 5 s, or until the next message). One try."""
        self._call("sendChatAction", {"chat_id": chat_id, "action": action}, retry=False)

    def send_album(self, chat_id: int, photos: list[tuple[bytes, str]]) -> None:
        """Send (jpeg bytes, caption) pairs as media groups of at most 10 (Telegram's limit);
        a single photo goes alone."""
        for i in range(0, len(photos), 10):
            self._send_group(chat_id, photos[i:i + 10])

    def send_pictures(self, chat_id: int, images: list[bytes], caption: str) -> None:
        """One exercise's pictures with ONE caption, on the first item (Telegram shows no
        caption under an album unless exactly one item carries it)."""
        self.send_album(chat_id, [(img, caption if i == 0 else "")
                                  for i, img in enumerate(images)])

    def _send_group(self, chat_id: int, photos: list[tuple[bytes, str]]) -> None:
        if len(photos) == 1:
            data, caption = photos[0]

            def send():
                return self._http.post(
                    self._url("sendPhoto"),
                    data={"chat_id": chat_id, "caption": caption[:1024]},
                    files={"photo": ("photo.jpg", data, "image/jpeg")},
                )
            self._request("send photo", send)
            return
        media = [{"type": "photo", "media": f"attach://p{i}", "caption": cap[:1024]}
                 for i, (_, cap) in enumerate(photos)]

        def send_group():
            return self._http.post(
                self._url("sendMediaGroup"),
                data={"chat_id": chat_id, "media": json.dumps(media)},
                files={f"p{i}": (f"p{i}.jpg", d, "image/jpeg")
                       for i, (d, _) in enumerate(photos)},
            )
        self._request("send album", send_group)

    def download_file(self, file_id: str) -> bytes:
        info = self._call("getFile", {"file_id": file_id})
        url = f"https://api.telegram.org/file/bot{self._token}/{info['file_path']}"
        return self._request("download", lambda: self._http.get(url)).content
