"""The one wrapper every Claude call goes through: records cost, enforces the monthly ceiling."""

from __future__ import annotations

import base64
import json
import re
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


class Claude:
    """`client` is an `anthropic.Anthropic` (or a fake with `messages.create`)."""

    def __init__(self, client, store, ceiling_usd: float, now=None):
        self._client = client
        self._store = store
        self._ceiling = ceiling_usd
        self._now = now or (lambda: datetime.now(HK))

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

    def _call(self, model: str, prompt: str, system: str, jpeg: bytes | None) -> str:
        if self.month_cost() >= self._ceiling:
            raise CeilingReached()
        content: list[dict] = []
        if jpeg is not None:
            data = base64.b64encode(jpeg).decode("ascii")
            content.append(
                {"type": "image",
                 "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}
            )
        content.append({"type": "text", "text": prompt})
        kwargs = {"system": system} if system else {}
        response = self._client.messages.create(
            model=model, max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": content}], **kwargs,
        )
        usage = response.usage
        self._store.add_api_call(
            self._now().astimezone(HK).isoformat(), model,
            usage.input_tokens, usage.output_tokens,
            cost_usd(model, usage.input_tokens, usage.output_tokens),
        )
        return "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
