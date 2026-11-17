"""Print one day's chat with the bot's traces, in time order, from data/gym.db (read-only).

Each message of Brian's is followed by what the bot understood, each model call (seconds,
tokens, reply), the seconds to its reply and any error. Each logged set appears at the time
it was saved ("Set saved"); sets saved before Task 14h have no time and come first.

    python scripts/show_chat.py --day 2026-11-17 [--db data/gym.db]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "gym.db"
PAD = " " * 9


def _trace_lines(t: dict) -> list[str]:
    lines = []
    if t["understood"] and t["understood"] != "scheduled":
        lines.append(f"{PAD}understood: {t['understood']}")
    for c in json.loads(t["calls"] or "[]"):
        tokens = (f" (in {c['input_tokens']}, out {c['output_tokens']} tokens)"
                  if "input_tokens" in c else "")
        image = " with image" if c.get("image") else ""
        tail = f": {' '.join(str(c.get('reply', '')).split())[:300]}" if c.get("reply") else ""
        error = f" ERROR {c['error']}" if c.get("error") else ""
        lines.append(f"{PAD}model {c['model']}{image} {c['seconds']} s{tokens}{error}{tail}")
    if t["seconds"] is not None:
        lines.append(f"{PAD}reply after {t['seconds']} s")
    if t["error"]:
        lines.append(f"{PAD}ERROR {t['error']}")
    if t.get("exercise"):  # Task 14i: the exercise shown after the message
        lines.append(f"{PAD}now shown: {t['exercise']}")
    return lines


def _set_line(r: dict) -> str:
    weight = "" if r["weight_kg"] is None else f"{r['weight_kg']:g} kg x "
    effort = f" ({r['effort']})" if r["effort"] else ""
    return f"Set saved: {r['exercise']} set {r['set_no']}: {weight}{r['reps']}{effort}"


def render(db_path, day: str) -> str:
    db = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        chat = [dict(r) for r in db.execute(
            "SELECT * FROM chat WHERE substr(timestamp,1,10)=? ORDER BY id", (day,))]
        try:
            traces = [dict(r) for r in db.execute(
                "SELECT * FROM trace WHERE substr(timestamp,1,10)=? ORDER BY id", (day,))]
        except sqlite3.OperationalError:  # a database the bot has not opened since Task 14h
            traces = []
        sets = [dict(r) for r in db.execute(
            "SELECT * FROM logged_sets WHERE date=? ORDER BY id", (day,))]
    finally:
        db.close()
    by_row = {t["chat_row"]: t for t in traces}
    out = [f"(no save time) {_set_line(r)}" for r in sets if not r.get("saved_at")]
    events = [(r["timestamp"], 0, r["id"], "chat", r) for r in chat]
    events += [(r["saved_at"], 1, r["id"], "set", r) for r in sets if r.get("saved_at")]
    for stamp, _, _, what, row in sorted(events, key=lambda e: e[:3]):
        clock = stamp[11:19]
        if what == "set":
            out.append(f"{clock} {_set_line(row)}")
            continue
        who = "Brian" if row["direction"] == "in" else "Bot"
        flags = ("" if row["delivered"] else " [NOT delivered]") + (" [late]" if row["late"]
                                                                    else "")
        text = row["text"].replace("\n", "\n" + PAD)
        out.append(f"{clock} {who}{flags} #{row['id']}: {text}")
        if row["id"] in by_row:
            out.extend(_trace_lines(by_row[row["id"]]))
    return "\n".join(out) if out else f"Nothing in the chat on {day}."


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--day", required=True, help="YYYY-MM-DD (Hong Kong date)")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    args = parser.parse_args(argv)
    print(render(args.db, args.day))


if __name__ == "__main__":
    main()
