"""`python -m gym_coach` runs the bot; `--check` only validates the settings."""

import sys

from gym_coach.config import ConfigError, load_config


def _stored_owner(config) -> bool:
    from pathlib import Path

    from gym_coach.store import Store
    db = Path(config.data_dir) / "gym.db"
    if not db.exists():
        return False
    store = Store(db)
    try:
        return bool(store.get("owner_id"))
    finally:
        store.close()


def main(argv: list[str]) -> int:
    try:
        config = load_config()
    except ConfigError as exc:
        print(exc)
        return 1
    if "--check" in argv:
        if config.telegram_allowed_user_id is None and not _stored_owner(config):
            print("config ok (owner not paired yet)")
        else:
            print("config ok")
        return 0
    from gym_coach import app
    watch = None
    if "--exit-with-parent" in argv:
        import os
        watch = os.getppid()
    try:
        app.main(config, watch_parent=watch)
    except app.AlreadyRunning:
        print("Another instance is already running.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
