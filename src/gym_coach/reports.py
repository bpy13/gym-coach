"""Log the sets Brian reports, format the log back to him, and apply corrections."""

from __future__ import annotations

from datetime import datetime

from gym_coach.llm import HK


def _clean(raw_sets) -> list[dict]:
    """Keep well-formed sets from the model's extraction; drop the rest."""
    out = []
    for s in raw_sets or []:
        if not isinstance(s, dict) or not str(s.get("exercise", "")).strip():
            continue
        try:
            reps = int(s["reps"])
            weight = None if s.get("weight_kg") is None else float(s["weight_kg"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append({"exercise": str(s["exercise"]).strip(), "weight_kg": weight, "reps": reps,
                    "effort": s.get("effort") or None})
    return out


def _key(name: str) -> str:
    return name.strip().lower()


def _rewrite(store, day: str, sets: list[dict]) -> None:
    """Replace the day's logged sets with `sets`, numbering them per exercise. Rows read back
    from the store keep their save time (empty for sets from before Task 14h); new sets are
    stamped now."""
    now = datetime.now(HK).isoformat(timespec="seconds")
    store.clear_logged_sets(day)
    counts: dict[str, int] = {}
    for s in sets:
        k = _key(s["exercise"])
        counts[k] = counts.get(k, 0) + 1
        store.add_logged_set(day, s["exercise"], counts[k], s["weight_kg"], s["reps"],
                             s["effort"], s.get("saved_at", now))


def log_report(store, day: str, raw_sets) -> list[dict]:
    """Add the reported sets to `day` (set numbers continue after any already logged).
    The day stays as it is: `mark_done` closes it at the end of the session."""
    sets = _clean(raw_sets)
    if sets:
        _rewrite(store, day, store.logged_sets(day) + sets)
    return sets


def remove(store, day: str, row_id: int) -> None:
    """Delete one logged set; the exercise's later sets move up one number."""
    _rewrite(store, day, [r for r in store.logged_sets(day) if r["id"] != row_id])


def mark_done(store, day: str) -> bool:
    """Mark a proposed or approved day `done` if any set or cardio is logged on it."""
    session = store.plan_session(day)
    if (session and session["status"] in ("proposed", "approved")
            and (store.logged_sets(day) or store.cardio_on(day))):
        store.set_plan_status(day, "done")
        return True
    return False


def missing(store, day: str, session: dict) -> list[str]:
    """'Name (done of planned)' for each exercise of the session with sets still to do."""
    out = []
    for ex in session["exercises"]:
        done = sets_done(store, day, ex["name"])
        if done < int(ex["sets"]):
            out.append(f"{ex['name']} ({done} of {ex['sets']})")
    return out


def correct(store, day: str, raw_sets) -> list[dict]:
    """Replace the day's sets for every exercise named in the correction."""
    sets = _clean(raw_sets)
    if sets:
        named = {_key(s["exercise"]) for s in sets}
        kept = [r for r in store.logged_sets(day) if _key(r["exercise"]) not in named]
        _rewrite(store, day, kept + sets)
    return sets


def format_log(store, day: str, header: str = "Logged:") -> str:
    """The day's sets, one line per exercise, e.g. 'Chest press: 35 kg x 10, 10, 8', then
    one line per cardio entry, e.g. 'Cardio: jogging 53 min, 7.2 km, avg 131 bpm'."""
    groups: dict[str, list[dict]] = {}
    for r in store.logged_sets(day):
        groups.setdefault(r["exercise"], []).append(r)
    lines = [f"{name}: {sets_text(rows)}" for name, rows in groups.items()]
    lines += [f"Cardio: {cardio_text(c)}" for c in store.cardio_on(day)]
    if not lines:
        return "Nothing logged yet today."
    return "\n".join([header] + lines)


def cardio_text(row: dict) -> str:
    """One cardio entry, e.g. 'jogging 53 min, 7.2 km, avg 131 bpm'."""
    parts = [f"{row['activity']} {row['minutes']:g} min"]
    if row.get("distance_km"):
        parts.append(f"{row['distance_km']:g} km")
    if row.get("avg_hr"):
        parts.append(f"avg {row['avg_hr']} bpm")
    return ", ".join(parts)


def sets_text(rows: list[dict]) -> str:
    """Sets of one exercise, e.g. '35 kg x 10, 10; 30 kg x 8'."""
    parts, i = [], 0
    while i < len(rows):  # group consecutive sets with the same weight
        w, reps = rows[i]["weight_kg"], []
        while i < len(rows) and rows[i]["weight_kg"] == w:
            reps.append(str(rows[i]["reps"]))
            i += 1
        parts.append((f"{w:g} kg x " if w is not None else "x ") + ", ".join(reps))
    return "; ".join(parts)


# A workout (Task 14i): kv "workout:<day>" is "open|<last chat row before it>|<open time>",
# then "closed|..." once it closes (no exercise left, "end", or the 21:00 close).
WORKOUT_KEY = "workout:"


def close_workout(store, day: str) -> bool:
    value = store.get(WORKOUT_KEY + day) or ""
    if value.startswith("open|"):
        store.set(WORKOUT_KEY + day, "closed|" + value[5:])
        return True
    return False


def sets_done(store, day: str, exercise: str) -> int:
    """How many sets of `exercise` are logged on `day`."""
    return sum(1 for r in store.logged_sets(day) if _key(r["exercise"]) == _key(exercise))


def format_exercise(store, day: str, exercise: str) -> str:
    """One exercise's logged sets, e.g. 'Chest press: 35 kg x 10, 10, 8'."""
    lines = format_log(store, day).splitlines()[1:]
    return next((ln for ln in lines if _key(ln).startswith(_key(exercise) + ":")),
                f"{exercise}: nothing logged")


def day_text(entry: dict) -> str:
    """One earlier day of an exercise (an entry of `Store.recent_sets`), e.g.
    '35 kg x 10, 10, 8 on 19 Nov'."""
    d = datetime.strptime(entry["date"], "%Y-%m-%d")
    return f"{sets_text(entry['sets'])} on {d.day} {d:%b}"


def set_text(row: dict) -> str:
    """One set, e.g. '28 kg x 12', with his effort word if saved: '28 kg x 12 (hard)'."""
    text = (f"{row['weight_kg']:g} kg x " if row["weight_kg"] is not None else "x ") + str(
        row["reps"])
    return text + (f" ({row['effort']})" if row.get("effort") else "")


def numbered_text(entry: dict) -> str:
    """One earlier day of an exercise with every set numbered and the count, for the coach
    (Task 14n: the grouped '21 kg x 15; 28 kg x 12, 15' was read as two sets), e.g.
    '17 Nov, 3 sets: set 1 21 kg x 15, set 2 28 kg x 12, set 3 28 kg x 15'."""
    d = datetime.strptime(entry["date"], "%Y-%m-%d")
    rows = entry["sets"]
    return (f"{d.day} {d:%b}, {len(rows)} set{'s' if len(rows) != 1 else ''}: "
            + ", ".join(f"set {i} {set_text(r)}" for i, r in enumerate(rows, 1)))


def top_weight(entry: dict) -> float | None:
    """The heaviest weight of that day's sets (he ramps up across sets); None for bodyweight."""
    weights = [r["weight_kg"] for r in entry["sets"] if r["weight_kg"] is not None]
    return max(weights) if weights else None


def planned_range(store, entry: dict) -> tuple[int, int] | None:
    """The rep range the plan of that day gave the exercise, or None (his own exercise)."""
    session = store.plan_session(entry["date"]) or {}
    k = _key(entry["exercise"])
    for ex in session.get("exercises") or []:
        if _key(str(ex.get("name", ""))) == k and "rep_low" in ex and "rep_high" in ex:
            return int(ex["rep_low"]), int(ex["rep_high"])
    return None
