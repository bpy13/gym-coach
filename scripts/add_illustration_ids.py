r"""One-off (Task 9i): add illustration ids to the stored sessions of a date range.

Usage: python scripts\add_illustration_ids.py 2026-11-17 2026-11-20 [--write]

Matches exercise names against the catalogue by code; what is left goes to the model once
(an id of the closest variant only, never a replacement exercise). Changes only the
"illustration" key of exercises; prints exercise names and picture counts per day, no weights.
Without --write it only reports.
"""

import sys
from pathlib import Path

from gym_coach.albums import session_album
from gym_coach.config import load_config
from gym_coach.context import equipment_for
from gym_coach.illustrations import Illustrations
from gym_coach.llm import Claude
from gym_coach.planner import ensure_pictures
from gym_coach.store import Store


def main(start: str, end: str, write: bool) -> None:
    store = Store(Path("data/gym.db"))
    ill = Illustrations(Path("data/illustrations"))
    equipment = {g: equipment_for(g, "data/equipment.md") for g in ("home", "parents")}
    config = load_config()
    import anthropic
    claude = Claude(anthropic.Anthropic(api_key=config.anthropic_api_key), store,
                    config.monthly_ceiling_usd)
    allowed = {g: ill.allowed(equipment[g]) for g in equipment}
    for s in store.plan_sessions(start, end):
        if s["kind"] != "strength":
            continue
        left = ensure_pictures([s], ill, allowed, equipment, claude=claude, model=config.model_fast,
                              equipment_path="data/equipment.md", allow_replace=False)
        if write:
            store.add_plan_session(s["date"], s["gym"], s["kind"], s["status"], s["exercises"])
        n = len(s["exercises"])
        album = session_album(s, "data/equipment.md", illustrations=ill)
        print(s["date"], s["gym"], f"{n} exercises", f"{len(album)} images",
              "without picture:", left or "none")
    store.close()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], "--write" in sys.argv)
