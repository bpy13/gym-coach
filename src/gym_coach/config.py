"""Settings read from the `.env` file and the process environment (standard library only)."""

import os
from dataclasses import dataclass
from pathlib import Path

REQUIRED = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USER_ID", "ANTHROPIC_API_KEY")


class ConfigError(Exception):
    """A required setting is missing or invalid. The message names the key, never a value."""


@dataclass(frozen=True)
class Config:
    telegram_bot_token: str
    telegram_allowed_user_id: int
    anthropic_api_key: str
    monthly_ceiling_usd: float = 5.0
    session_time: str = "07:00"
    review_time: str = "20:00"
    body_prompt_time: str = "07:00"
    timezone: str = "Asia/Hong_Kong"
    model_fast: str = "claude-haiku-5-5"
    model_coach: str = "claude-opus-5-5"
    data_dir: str = "data"

    def __repr__(self) -> str:
        return "Config(<secrets hidden>)"


def parse_env_file(path: Path) -> dict[str, str]:
    """Read KEY=VALUE lines; skip blanks and # comments; strip optional quotes."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def load_config(env_path: Path | str = ".env", environ: dict[str, str] | None = None) -> Config:
    """Load settings. Real environment variables override the file."""
    values = parse_env_file(Path(env_path))
    values.update(os.environ if environ is None else environ)

    for key in REQUIRED:
        if not values.get(key, "").strip():
            raise ConfigError(f"Missing setting {key}: add it to .env")

    try:
        user_id = int(values["TELEGRAM_ALLOWED_USER_ID"])
    except ValueError:
        raise ConfigError("TELEGRAM_ALLOWED_USER_ID must be a whole number") from None
    try:
        ceiling = float(values.get("MONTHLY_CEILING_USD", "5"))
    except ValueError:
        raise ConfigError("MONTHLY_CEILING_USD must be a number") from None

    def get(key: str, default: str) -> str:
        return values.get(key, "").strip() or default

    return Config(
        telegram_bot_token=values["TELEGRAM_BOT_TOKEN"].strip(),
        telegram_allowed_user_id=user_id,
        anthropic_api_key=values["ANTHROPIC_API_KEY"].strip(),
        monthly_ceiling_usd=ceiling,
        session_time=get("SESSION_TIME", "07:00"),
        review_time=get("REVIEW_TIME", "20:00"),
        body_prompt_time=get("BODY_PROMPT_TIME", "07:00"),
        timezone=get("TIMEZONE", "Asia/Hong_Kong"),
        model_fast=get("MODEL_FAST", "claude-haiku-5-5"),
        model_coach=get("MODEL_COACH", "claude-opus-5-5"),
        data_dir=get("DATA_DIR", "data"),
    )
