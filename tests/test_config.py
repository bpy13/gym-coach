import pytest

from gym_coach.config import ConfigError, load_config

SECRETS = (
    "TELEGRAM_BOT_TOKEN=tok-123\n"
    "TELEGRAM_ALLOWED_USER_ID=42\n"
    "ANTHROPIC_API_KEY=key-abc\n"
)


def write_env(tmp_path, text):
    path = tmp_path / ".env"
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults(tmp_path):
    cfg = load_config(write_env(tmp_path, SECRETS), environ={})
    assert cfg.telegram_allowed_user_id == 42
    assert cfg.monthly_ceiling_usd == 5.0
    assert cfg.session_time == "07:00"
    assert cfg.review_time == "20:00"
    assert cfg.body_prompt_time == "07:00"
    assert cfg.timezone == "Asia/Hong_Kong"
    assert cfg.model_fast == "claude-haiku-5-5"
    assert cfg.model_coach == "claude-opus-5-5"
    assert cfg.data_dir == "data"


def test_overrides_comments_and_quotes(tmp_path):
    text = "# note\n" + SECRETS + 'SESSION_TIME="06:30"\nMONTHLY_CEILING_USD=3\n'
    cfg = load_config(write_env(tmp_path, text), environ={})
    assert cfg.session_time == "06:30"
    assert cfg.monthly_ceiling_usd == 3.0


@pytest.mark.parametrize(
    "key", ["TELEGRAM_BOT_TOKEN", "ANTHROPIC_API_KEY"]
)
def test_missing_secret_names_key_not_values(tmp_path, key):
    text = "".join(line + "\n" for line in SECRETS.splitlines() if not line.startswith(key))
    with pytest.raises(ConfigError) as err:
        load_config(write_env(tmp_path, text), environ={})
    assert key in str(err.value)
    assert "tok-123" not in str(err.value) and "key-abc" not in str(err.value)


def test_missing_file_reports_first_key(tmp_path):
    with pytest.raises(ConfigError, match="TELEGRAM_BOT_TOKEN"):
        load_config(tmp_path / "none.env", environ={})


def test_bad_user_id(tmp_path):
    text = SECRETS.replace("=42", "=abc")
    with pytest.raises(ConfigError, match="TELEGRAM_ALLOWED_USER_ID"):
        load_config(write_env(tmp_path, text), environ={})


def test_environment_overrides_file(tmp_path):
    cfg = load_config(write_env(tmp_path, SECRETS), environ={"TELEGRAM_ALLOWED_USER_ID": "7"})
    assert cfg.telegram_allowed_user_id == 7


def test_repr_hides_secrets(tmp_path):
    cfg = load_config(write_env(tmp_path, SECRETS), environ={})
    assert "tok-123" not in repr(cfg) and "key-abc" not in repr(cfg)


def test_user_id_is_optional(tmp_path):
    lines = [ln for ln in SECRETS.splitlines() if not ln.startswith("TELEGRAM_ALLOWED")]
    cfg = load_config(write_env(tmp_path, "\n".join(lines) + "\n"), environ={})
    assert cfg.telegram_allowed_user_id is None
