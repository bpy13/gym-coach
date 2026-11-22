r"""One-off (Task 15a): fix two equipment names stored in plan_sessions.exercises.

Usage: python scripts\migrate_equipment_names.py [--db data\gym.db] [--today 2026-11-23]

Copies the database to <db>.bak-15a first (once; an existing copy is kept), then in every
exercise replaces the equipment `lat pulldown with low row (one tower` with the full name and
`leg extension and leg curl` with `leg extension (seated) and lying leg curl`. An exercise on
that machine whose name says "leg curl" becomes "Lying leg curl" with illustration
`Lying_Leg_Curls`, but only on days from today on: past days keep their exercise names
(logged sets point at them). Safe to run twice: the second run changes nothing.
"""

import argparse
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from gym_coach.context import HK

OLD_TOWER = "lat pulldown with low row (one tower"
NEW_TOWER = "lat pulldown with low row (one tower, high bar and low handle)"
OLD_COMBINED = "leg extension and leg curl"
NEW_COMBINED = "leg extension (seated) and lying leg curl"


def migrate(db: Path, today: str) -> list[str]:
    """Apply the changes; returns one line per changed exercise."""
    backup = db.with_name(db.name + ".bak-15a")
    if not backup.exists():
        shutil.copy2(db, backup)
    changes: list[str] = []
    con = sqlite3.connect(db)
    try:
        rows = con.execute("SELECT date, exercises FROM plan_sessions").fetchall()
        for day, raw in rows:
            exercises = json.loads(raw)
            touched = False
            for ex in exercises:
                equipment = ex.get("equipment", "")
                new_equipment = equipment
                if equipment.strip().lower() == OLD_TOWER:
                    new_equipment = NEW_TOWER
                elif equipment.strip().lower() == OLD_COMBINED:
                    new_equipment = NEW_COMBINED
                if new_equipment != equipment:
                    ex["equipment"] = new_equipment
                    touched = True
                    changes.append(f"{day}: {ex['name']}: equipment -> {new_equipment}")
                if (new_equipment == NEW_COMBINED and day >= today
                        and "leg curl" in ex["name"].lower()
                        and (ex["name"], ex.get("illustration")) != ("Lying leg curl", "Lying_Leg_Curls")):
                    changes.append(f"{day}: {ex['name']} -> Lying leg curl (Lying_Leg_Curls)")
                    ex["name"], ex["illustration"] = "Lying leg curl", "Lying_Leg_Curls"
                    touched = True
            if touched:
                con.execute("UPDATE plan_sessions SET exercises=? WHERE date=?",
                            (json.dumps(exercises), day))
        con.commit()
    finally:
        con.close()
    return changes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/gym.db")
    ap.add_argument("--today", default=datetime.now(HK).date().isoformat())
    args = ap.parse_args()
    changes = migrate(Path(args.db), args.today)
    print("\n".join(changes) if changes else "nothing to change")


if __name__ == "__main__":
    main()
