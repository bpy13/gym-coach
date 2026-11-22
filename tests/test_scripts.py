"""Task 15f: the replay's budget check and the equipment-name migration. Made-up data."""

import importlib.util
import json
from datetime import datetime
from pathlib import Path

from gym_coach.llm import HK
from gym_coach.store import Store

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
NOW = datetime(2026, 11, 23, 12, 0, tzinfo=HK)


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_replay_budget_check_counts_this_months_live_cost(tmp_path):
    replay = load("replay_day")
    db = tmp_path / "gym.db"
    store = Store(db)
    store.add_api_call("2026-10-31T23:00:00+08:00", "claude-opus-5-5", 1, 1, 9.0)  # last month
    store.add_api_call("2026-11-20T10:00:00+08:00", "claude-opus-5-5", 1, 1, 4.6)
    store.close()
    ok, line = replay.budget_check(db, 5.0, 0.50, NOW)
    assert not ok and "US$4.6000" in line and "over the US$5 ceiling" in line
    ok, line = replay.budget_check(db, 5.0, 0.40, NOW)
    assert ok and "within" in line


def test_replay_work_dir_is_not_a_personal_path():
    replay = load("replay_day")
    assert "scratchpad" not in str(replay.WORK_DIR)
    assert "scratchpad" not in (SCRIPTS / "replay_day.py").read_text(encoding="utf-8")


def test_migration_keeps_todays_leg_curl_name(tmp_path):
    migrate = load("migrate_equipment_names")
    db = tmp_path / "gym.db"
    store = Store(db)
    curl = {"name": "Seated leg curl", "equipment": "leg extension and leg curl", "sets": 3,
            "rep_low": 10, "rep_high": 12, "weight_kg": 25}
    for day in ("2026-11-23", "2026-11-24"):
        store.add_plan_session(day, "parents", "strength", "approved", [dict(curl)])
    store.close()
    migrate.migrate(db, "2026-11-23")
    store = Store(db)
    today, tomorrow = (store.plan_session(d)["exercises"][0]
                       for d in ("2026-11-23", "2026-11-24"))
    store.close()
    assert today["name"] == "Seated leg curl"  # sets logged today keep matching
    assert today["equipment"] == "leg extension (seated) and lying leg curl"
    assert tomorrow["name"] == "Lying leg curl"
    assert json.dumps(tomorrow).count("Lying_Leg_Curls") == 1
