"""The one wrapper every Claude call goes through: records cost, enforces the monthly ceiling."""

from __future__ import annotations

import base64
import json
import re
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

HK = ZoneInfo("Asia/Hong_Kong")

# US$ per million tokens: (input, output). Haiku costs more when the prompt is over 100,000 tokens.
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-opus-5-5": (4.0, 20.0),
}
HAIKU_LONG = (0.50, 2.50)
LONG_PROMPT_TOKENS = 100_000
MAX_TOKENS = 4096
MAX_TOOL_ROUNDS = 6


class CeilingReached(Exception):
    """This month's API cost is at or over the ceiling; no call was made."""


class LLMError(Exception):
    """The model's answer could not be used."""


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    if model not in PRICES:
        raise LLMError(f"No price known for model {model}")
    price_in, price_out = PRICES[model]
    if model == "claude-haiku-5-5" and input_tokens > LONG_PROMPT_TOKENS:
        price_in, price_out = HAIKU_LONG
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


def _month_bounds(now: datetime) -> tuple[str, str]:
    """ISO start (inclusive) and end (exclusive) of the month containing `now` (HK time)."""
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start.isoformat(), end.isoformat()


def _parse_json(text: str):
    """Parse JSON from a reply, tolerating a markdown code fence around it."""
    text = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    return json.loads(fenced.group(1) if fenced else text)


class LazyAnthropic:
    """Stands in for an `anthropic.Anthropic` and builds it on first use (thread-safe).

    Importing the SDK reads about 2,800 modules; on a busy PC that took minutes and kept the
    bot from starting (Task 14e). A failed load is retried on the next use.
    """

    def __init__(self, factory):
        self._factory = factory
        self._client = None
        self._lock = threading.Lock()

    def load(self):
        with self._lock:
            if self._client is None:
                self._client = self._factory()
            return self._client

    @property
    def messages(self):
        return self.load().messages


class Claude:
    """`client` is an `anthropic.Anthropic`, a `LazyAnthropic`, or a fake with
    `messages.create`."""

    def __init__(self, client, store, ceiling_usd: float, now=None):
        self._client = client
        self._store = store
        self._ceiling = ceiling_usd
        self._now = now or (lambda: datetime.now(HK))
        # While the app handles one message it sets a list here; each call adds its model,
        # seconds, tokens and reply text (Task 14h traces). None: nothing is kept.
        self.trace: list | None = None

    @property
    def client(self):
        return self._client

    @property
    def ceiling_usd(self) -> float:
        return self._ceiling

    def month_cost(self) -> float:
        start, end = _month_bounds(self._now().astimezone(HK))
        return self._store.cost_between(start, end)

    def text(self, model: str, prompt: str, system: str = "") -> str:
        return self._call(model, prompt, system, None)

    def text_with_image(self, model: str, prompt: str, jpeg: bytes, system: str = "") -> str:
        return self._call(model, prompt, system, jpeg)

    def json(self, model: str, prompt: str, system: str = "", jpeg: bytes | None = None):
        """Ask for JSON and parse it. On a parse failure ask once more, then raise LLMError."""
        system = (system + "\n\n" if system else "") + "Reply with JSON only, no other text."
        for attempt in (1, 2):
            reply = self._call(model, prompt, system, jpeg)
            try:
                return _parse_json(reply)
            except json.JSONDecodeError:
                if attempt == 2:
                    raise LLMError("The model did not return valid JSON twice") from None

    def converse(self, model: str, system: str, messages: list[dict], tools: list[dict],
                 run_tool, jpeg: bytes | None = None) -> str:
        """Run a tool-use conversation and return the model's final text.

        `messages` are Anthropic message dicts (the caller's list is not changed); `tools` are
        Anthropic tool definitions; `run_tool(name, input) -> str` gives each tool's result
        text. An exception in `run_tool` goes back to the model as an `is_error` result.
        `jpeg` goes first in the first user message. Each round checks the ceiling, records
        its cost and adds a trace entry; after MAX_TOOL_ROUNDS rounds it raises LLMError.
        """
        convo = [dict(m) for m in messages]
        if jpeg is not None:
            first = next(m for m in convo if m["role"] == "user")
            content = first["content"]
            if isinstance(content, str):
                content = [{"type": "text", "text": content}]
            first["content"] = [_image_block(jpeg), *content]
        for _ in range(MAX_TOOL_ROUNDS):
            response, reply = self._round(model, system, list(convo), jpeg is not None,
                                          tools=tools)
            calls = [b for b in response.content if getattr(b, "type", "") == "tool_use"]
            if not calls:
                return reply
            convo.append({"role": "assistant",
                          "content": [_block_dict(b) for b in response.content]})
            convo.append({"role": "user", "content": [_run(run_tool, b) for b in calls]})
        raise LLMError(f"The model still called tools after {MAX_TOOL_ROUNDS} rounds")

    def _call(self, model: str, prompt: str, system: str, jpeg: bytes | None) -> str:
        content: list[dict] = [_image_block(jpeg)] if jpeg is not None else []
        content.append({"type": "text", "text": prompt})
        messages = [{"role": "user", "content": content}]
        return self._round(model, system, messages, jpeg is not None)[1]

    def _round(self, model: str, system: str, messages: list[dict], image: bool,
               tools: list[dict] | None = None):
        """One API call: ceiling check, cost row, trace entry. Returns (response, text)."""
        if self.month_cost() >= self._ceiling:
            raise CeilingReached()
        kwargs: dict = {"system": system} if system else {}
        if tools is not None:
            kwargs["tools"] = tools
        started = time.monotonic()
        try:
            response = self._client.messages.create(
                model=model, max_tokens=MAX_TOKENS, messages=messages, **kwargs,
            )
        except Exception as exc:
            self._traced(model, started, error=f"{type(exc).__name__}: {exc}"[:300])
            raise
        usage = response.usage
        self._store.add_api_call(
            self._now().astimezone(HK).isoformat(), model,
            usage.input_tokens, usage.output_tokens,
            cost_usd(model, usage.input_tokens, usage.output_tokens),
        )
        reply = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
        extra = {}
        if tools is not None:
            extra["tools"] = [b.name for b in response.content
                              if getattr(b, "type", "") == "tool_use"]
        self._traced(model, started, image=image, input_tokens=usage.input_tokens,
                     output_tokens=usage.output_tokens, reply=reply[:2000], **extra)
        return response, reply

    def _traced(self, model: str, started: float, **fields) -> None:
        if self.trace is not None:
            self.trace.append({"model": model,
                               "seconds": round(time.monotonic() - started, 2), **fields})


def _image_block(jpeg: bytes) -> dict:
    data = base64.b64encode(jpeg).decode("ascii")
    return {"type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


def _block_dict(block) -> dict:
    """An SDK content block (or a fake's) as the plain dict the API accepts back."""
    if isinstance(block, dict):
        return block
    if block.type == "text":
        return {"type": "text", "text": block.text}
    if block.type == "tool_use":
        return {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
    return block.model_dump(exclude_none=True)


def _run(run_tool, block) -> dict:
    """Run one tool call; a failure becomes an error result for the model, not a crash."""
    try:
        return {"type": "tool_result", "tool_use_id": block.id,
                "content": str(run_tool(block.name, block.input))}
    except Exception as exc:  # noqa: BLE001 - any tool failure goes back to the model
        return {"type": "tool_result", "tool_use_id": block.id, "is_error": True,
                "content": str(exc) or type(exc).__name__}
