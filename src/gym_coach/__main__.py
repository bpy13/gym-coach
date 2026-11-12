"""`python -m gym_coach` runs the bot; `--check` only validates the settings."""

import sys

from gym_coach.config import ConfigError, load_config


def main(argv: list[str]) -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(exc)
        return 1
    if "--check" in argv:
        print("config ok")
        return 0
    from gym_coach import app
    try:
        app.main(config)
    except app.AlreadyRunning:
        print("Another instance is already running.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
