"""Replay one day's messages from Brian through the current coach chat (Task 15d).

    python scripts/replay_day.py --day 2026-11-22 [--db PATH] [--from N --to M]
                                 [--old-machine] [--append] [--out FILE] [--max-cost 0.50]
                                 [--work-dir DIR]

It copies the database into --work-dir (default: gym-coach-replay in the system temp folder;
the original is only read), resets the day in the copy (sets, kv keys, that day's chat and trace rows, the session as sent at 07:00),
feeds Brian's messages from the chat table in order with the clock at each message's time, and
writes every message, the tool calls, the reply, any exercise card or keyboard and the cost of
each message to data/replay/<day>.txt. Real model calls: the cost is added up and the run
stops when it passes --max-cost. Those calls are recorded in the copy only, so the bot's
monthly ceiling never sees them: before the run the script reads this month's cost from the
source database and refuses when that plus --max-cost is over the ceiling in the config.
Photos are not kept, so a "[photo]" message goes through as the text it was stored as.

With --from (and --seed for sets that were corrected later in the stored rows), the chat rows before that message, the sets saved before it and the workout and
flow state of that moment are copied from the source first, so the replay starts mid-workout.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import statistics
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from gym_coach import reports
from gym_coach.albums import exercise_parts
from gym_coach.config import load_config
from gym_coach.illustrations import Illustrations
from gym_coach.llm import HK, Claude, LazyAnthropic, _month_bounds
from gym_coach.messages import exercise_line
from gym_coach.router import Router
from gym_coach.store import Store

WORK_DIR = Path(tempfile.gettempdir()) / "gym-coach-replay"
# "Name: 3 x 8-12 at 35 kg" (before Task 14o) or "Name: 3 x 8-12 (last time, ...)" (no weight)
LINE = re.compile(r"^(?P<name>.+?): (?P<sets>\d+) x (?P<lo>\d+)-(?P<hi>\d+)"
                  r"(?: at (?P<kg>[\d.]+) kg)?(?: \(.*\))?$")
# the leg curl exercise was dropped from the stored row, so it is rebuilt by hand
LEG_CURL = {
    "default": ("Lying leg curl", "leg extension (seated) and lying leg curl", "Lying_Leg_Curls"),
    "old": ("Seated leg curl", "leg extension and leg curl", "Seated_Leg_Curl"),
}
FAR = "=" * 78


class CostStop(Exception):
    pass


def _rows(db: sqlite3.Connection, sql: str, args=()) -> list[dict]:
    return [dict(r) for r in db.execute(sql, args).fetchall()]


def build_session(original: sqlite3.Connection, day: str, morning: str,
                  old_machine: bool) -> tuple[str, list[dict]]:
    """The strength session as the 07:00 message listed it: (gym, exercises)."""
    stored = _rows(original, "SELECT * FROM plan_sessions WHERE date=?", (day,))[0]
    by_name = {e["name"].strip().lower(): e for e in json.loads(stored["exercises"])}
    exercises = []
    for text in morning.splitlines()[1:]:
        m = LINE.match(text.strip())
        if not m:
            continue
        name = m["name"]
        known = by_name.get(name.strip().lower())
        weight = float(m["kg"]) if m["kg"] else (known or {}).get("weight_kg")
        if isinstance(weight, float):
            weight = int(weight) if weight == int(weight) else weight
        ex = {"name": name, "equipment": "", "sets": int(m["sets"]), "rep_low": int(m["lo"]),
              "rep_high": int(m["hi"]), "weight_kg": weight}
        if "leg curl" in name.lower():
            new_name, equipment, illustration = LEG_CURL["old" if old_machine else "default"]
            ex.update(name=new_name, equipment=equipment, illustration=illustration)
        elif known:
            ex.update(equipment=known["equipment"], illustration=known.get("illustration"))
        exercises.append({k: v for k, v in ex.items() if v is not None})
    return stored["gym"], exercises


def parse_seed(text: str) -> list[tuple[str, float, int]]:
    """"Name:28x15,28x12;Other:10x8" -> [(name, kg, reps), ...] in that order."""
    sets = []
    for part in filter(None, (p.strip() for p in text.split(";"))):
        name, _, numbers = part.partition(":")
        for item in numbers.split(","):
            kg, _, reps = item.strip().partition("x")
            sets.append((name.strip(), float(kg), int(reps)))
    return sets


def budget_check(source: Path, ceiling: float, max_cost: float,
                 now: datetime) -> tuple[bool, str]:
    """Whether this month's cost in the source database (read only) plus `max_cost` stays
    within `ceiling`, and a line saying so."""
    start, end = _month_bounds(now.astimezone(HK))
    db = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    try:
        spent = float(db.execute("SELECT COALESCE(SUM(cost_usd),0) FROM api_calls"
                                 " WHERE timestamp>=? AND timestamp<?",
                                 (start, end)).fetchone()[0])
    finally:
        db.close()
    ok = spent + max_cost <= ceiling
    return ok, (f"Budget check: this month US${spent:.4f} in {source.name} + --max-cost "
                f"US${max_cost:.2f} = US${spent + max_cost:.4f}, "
                f"{'within' if ok else 'over'} the US${ceiling:g} ceiling.")


def prepare(source: Path, copy: Path, day: str, first: dict, old_machine: bool,
            preload: bool, seed: list[tuple[str, float, int]]) -> None:
    """Copy the database and reset the day in the copy."""
    copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, copy)
    original = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    original.row_factory = sqlite3.Row
    try:
        morning = next(r["text"] for r in _rows(
            original, "SELECT * FROM chat WHERE substr(timestamp,1,10)=? AND kind='scheduled'"
            " ORDER BY id", (day,)) if r["text"].count("\n") >= 2)
        gym, exercises = build_session(original, day, morning, old_machine)
        before_sets = _rows(original, "SELECT * FROM logged_sets WHERE date=? AND saved_at<?"
                            " ORDER BY id", (day, first["timestamp"]))
        traces = _rows(original, "SELECT * FROM trace WHERE chat_row<? AND exercise IS NOT NULL"
                       " ORDER BY id DESC LIMIT 1", (first["id"],))
        workout = (original.execute("SELECT value FROM kv WHERE key=?",
                                    (reports.WORKOUT_KEY + day,)).fetchone() or [""])[0]
    finally:
        original.close()
    db = sqlite3.connect(copy)
    with db:
        db.execute("DELETE FROM logged_sets WHERE date=?", (day,))
        db.execute("DELETE FROM kv WHERE key IN (?,?,?,?)",
                   tuple(p + day for p in ("workout:", "flow:", "passed:", "warmup:")))
        db.execute("DELETE FROM meals WHERE timestamp>=?", (first["timestamp"],))
        db.execute("DELETE FROM trace WHERE substr(timestamp,1,10)=? AND chat_row>=?",
                   (day, first["id"]))
        db.execute("DELETE FROM chat WHERE substr(timestamp,1,10)=? AND id>=?",
                   (day, first["id"]))
        db.execute("UPDATE sqlite_sequence SET seq=(SELECT COALESCE(MAX(id),0) FROM chat)"
                   " WHERE name='chat'")
        db.execute("UPDATE sqlite_sequence SET seq=(SELECT COALESCE(MAX(id),0) FROM trace)"
                   " WHERE name='trace'")
    db.close()
    store = Store(copy)
    try:
        store.add_plan_session(day, gym, "strength", "approved", exercises)
        # what the scheduler does at 07:00: warm-up pending, flow at the first exercise
        store.set("warmup:" + day, "1")
        store.set("flow:" + day, "0")
        if preload:  # a mid-workout start: the state at the time of the first message
            opened = workout.split("|")
            if workout and opened[2] <= first["timestamp"]:
                store.set(reports.WORKOUT_KEY + day, f"open|{opened[1]}|{opened[2]}")
                store.set("warmup:" + day, "")
            if traces:
                store.set("flow:" + day, traces[0]["exercise"].split(":")[0])
            for r in before_sets:
                store.add_logged_set(day, r["exercise"], r["set_no"], r["weight_kg"], r["reps"],
                                     r["effort"], r["saved_at"])
            for name, kg, reps in seed:  # sets the stored rows no longer show (see --seed)
                number = reports.sets_done(store, day, name) + 1
                store.add_logged_set(day, name, number, kg, reps, None, first["timestamp"])
    finally:
        store.close()


def run(args) -> int:
    day = args.day
    source = Path(args.db)
    original = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    original.row_factory = sqlite3.Row
    incoming = _rows(original, "SELECT * FROM chat WHERE direction='in'"
                     " AND substr(timestamp,1,10)=? AND id>=? AND id<=? ORDER BY id",
                     (day, args.first, args.last))
    original.close()
    if not incoming:
        print("No messages from Brian in that range.")
        return 1
    config = load_config()
    ok, line = budget_check(source, config.monthly_ceiling_usd, args.max_cost, datetime.now(HK))
    print(line)
    if not ok:
        print("Refused: the replay's real cost could take the bot past its ceiling.")
        return 3
    stamp = datetime.now().strftime("%H%M%S")
    copy = Path(args.work_dir) / f"{day}-{stamp}" / "gym.db"
    preload = args.first > 0
    prepare(source, copy, day, incoming[0], args.old_machine, preload, parse_seed(args.seed))

    store = Store(copy)
    clock = [datetime.fromisoformat(incoming[0]["timestamp"])]
    now = lambda: clock[0]
    claude = Claude(LazyAnthropic(lambda: __import__("anthropic").Anthropic(
        api_key=config.anthropic_api_key)), store, config.monthly_ceiling_usd, now=now)
    illustrations = Illustrations(Path(config.data_dir) / "illustrations")
    router = Router(store, claude, config.model_fast, config.model_coach, now=now,
                    illustrations=illustrations)

    heading = (f"RUN: day {day}, source {source.name}"
               + (", old machine name (Seated leg curl on 'leg extension and leg curl')"
                  if args.old_machine else ", default session (Lying leg curl)")
               + (f", messages #{incoming[0]['id']}-#{incoming[-1]['id']}"
                  if preload or args.last < 10**9 else ", full day")
               + f"\nmodel {config.model_fast}; database copy {copy}")
    out = [FAR, heading, FAR]
    session = store.plan_session(day)
    out.append("Session at 07:00 in the copy:\n" + "\n".join(
        f"  {exercise_line(e)}  [{e['equipment'] or 'no equipment'}]"
        for e in session["exercises"]))
    costs: list[tuple[int, float, int]] = []  # (original id, US$, model calls)
    stopped = None
    try:
        for msg in incoming:
            clock[0] = datetime.fromisoformat(msg["timestamp"])
            last_call = int(store._db.execute(
                "SELECT COALESCE(MAX(id),0) FROM api_calls").fetchone()[0])
            claude.trace = []
            router.understood = router.error = None
            text = msg["text"].strip()
            out.append(f"\n--- #{msg['id']} {msg['timestamp'][11:19]} Brian: {text}")
            try:
                reply = router.handle(text)
            except Exception as exc:  # noqa: BLE001  a crash is part of what the replay shows
                reply, router.error = f"(crashed: {type(exc).__name__}: {exc})", str(exc)
            understood, error, keyboard = router.understood, router.error, router.pop_keyboard()
            store.add_chat(clock[0].isoformat(timespec="seconds"), "in", text)
            card = router.pop_exercise()
            router.pop_album_session()
            store.add_chat(clock[0].isoformat(timespec="seconds"), "out", reply)
            if understood and understood != "local":
                for c in json.loads(understood):
                    out.append(f"    tool {c['tool']} {json.dumps(c['input'], ensure_ascii=False)}"
                               f"\n      -> {' '.join(str(c['result']).split())}")
            elif understood == "local":
                out.append("    (handled locally, no model call)")
            rounds = len(claude.trace)
            for call in claude.trace:
                if call.get("error"):
                    out.append(f"    model error: {call['error']}")
            out.append("    Bot: " + reply.replace("\n", "\n         "))
            if keyboard:
                out.append(f"    keyboard: {json.dumps(keyboard)}")
            if card:
                caption = exercise_line(card[0]["exercises"][card[1]])
                try:
                    caption = exercise_parts(card[0], card[1], illustrations=illustrations,
                                             photos_dir=Path(config.photos_dir))[0]
                except (OSError, KeyError, ValueError):  # the plain line stays
                    pass
                store.add_chat(clock[0].isoformat(timespec="seconds"), "out", caption,
                               kind="pictures")
                out.append("    exercise card queued: " + caption.replace("\n", " | ")[:160])
            if error:
                out.append(f"    ERROR: {error}")
            cost = float(store._db.execute(
                "SELECT COALESCE(SUM(cost_usd),0) FROM api_calls WHERE id>?",
                (last_call,)).fetchone()[0])
            costs.append((msg["id"], cost, rounds))
            total = sum(c for _, c, _ in costs)
            out.append(f"    cost US${cost:.5f} ({rounds} model call{'s' if rounds != 1 else ''});"
                       f" running US${total:.4f}")
            if total > args.max_cost:
                stopped = f"STOPPED: running cost US${total:.4f} passed US${args.max_cost:.2f}"
                break
    finally:
        claude.trace = None
        out.append("\n" + FAR + "\nLog at the end of the run (copy of the database):")
        out.append(reports.format_log(store, day))
        out.append("Session at the end:\n" + "\n".join(
            f"  {exercise_line(e)}  [{e['equipment'] or 'no equipment'}]"
            for e in store.plan_session(day)["exercises"]))
        store.close()
    if stopped:
        out.append(stopped)
    values = [c for _, c, _ in costs]
    with_calls = [c for _, c, n in costs if n]
    out.append(FAR)
    out.append(f"Messages replayed: {len(costs)}; total cost US${sum(values):.4f}")
    out.append(f"Median cost per message (all messages): US${statistics.median(values):.5f}")
    if with_calls:
        out.append(f"Median cost per message that made a model call ({len(with_calls)}): "
                   f"US${statistics.median(with_calls):.5f}")
    text = "\n".join(out) + "\n"
    target = Path(args.out) if args.out else ROOT / "data" / "replay" / f"{day}.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a" if args.append else "w", encoding="utf-8") as fh:
        fh.write(("\n\n" if args.append else "") + text)
    print(text[-900:])
    print(f"Written to {target}")
    return 2 if stopped else 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--day", required=True, help="YYYY-MM-DD (Hong Kong date)")
    parser.add_argument("--db", default=str(ROOT / "data" / "gym.db"))
    parser.add_argument("--from", dest="first", type=int, default=0, help="first chat id")
    parser.add_argument("--to", dest="last", type=int, default=10**9, help="last chat id")
    parser.add_argument("--seed", default="",
                        help='sets to add before a --from start, "Name:28x15,28x12;Other:10x8" '
                             "(for sets the stored rows had corrected later)")
    parser.add_argument("--old-machine", action="store_true",
                        help="the leg curl as stored before Task 15a")
    parser.add_argument("--append", action="store_true", help="append to the output file")
    parser.add_argument("--out", help="output file (default data/replay/<day>.txt)")
    parser.add_argument("--max-cost", type=float, default=0.50, help="stop above this US$")
    parser.add_argument("--work-dir", default=str(WORK_DIR),
                        help="folder for the database copy (default: the system temp folder)")
    args = parser.parse_args(argv)
    if args.out and Path(args.out).resolve().name.startswith("gym.db"):
        parser.error("--out must not be a database file")
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
