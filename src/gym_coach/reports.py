"""Log the sets Brian reports, format the log back to him, and apply corrections."""

from __future__ import annotations


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
    """Replace the day's logged sets with `sets`, numbering them per exercise."""
    store.clear_logged_sets(day)
    counts: dict[str, int] = {}
    for s in sets:
        k = _key(s["exercise"])
        counts[k] = counts.get(k, 0) + 1
        store.add_logged_set(day, s["exercise"], counts[k], s["weight_kg"], s["reps"], s["effort"])


def log_report(store, day: str, raw_sets) -> list[dict]:
    """Add the reported sets to `day` (set numbers continue after any already logged)."""
    sets = _clean(raw_sets)
    if sets:
        _rewrite(store, day, store.logged_sets(day) + sets)
        session = store.plan_session(day)
        if session and session["status"] in ("proposed", "approved"):
            store.set_plan_status(day, "done")
    return sets


def correct(store, day: str, raw_sets) -> list[dict]:
    """Replace the day's sets for every exercise named in the correction."""
    sets = _clean(raw_sets)
    if sets:
        named = {_key(s["exercise"]) for s in sets}
        kept = [r for r in store.logged_sets(day) if _key(r["exercise"]) not in named]
        _rewrite(store, day, kept + sets)
    return sets


def format_log(store, day: str, header: str = "Logged:") -> str:
    """The day's sets, one line per exercise, e.g. 'Chest press: 35 kg x 10, 10, 8'."""
    groups: dict[str, list[dict]] = {}
    for r in store.logged_sets(day):
        groups.setdefault(r["exercise"], []).append(r)
    if not groups:
        return "Nothing logged yet today."
    lines = [header]
    for name, rows in groups.items():
        parts, i = [], 0
        while i < len(rows):  # group consecutive sets with the same weight
            w, reps = rows[i]["weight_kg"], []
            while i < len(rows) and rows[i]["weight_kg"] == w:
                reps.append(str(rows[i]["reps"]))
                i += 1
            parts.append((f"{w:g} kg x " if w is not None else "x ") + ", ".join(reps))
        lines.append(f"{name}: " + "; ".join(parts))
    return "\n".join(lines)
