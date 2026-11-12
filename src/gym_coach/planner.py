"""First schedule and plan proposal. Code, not the model, enforces equipment and the gym."""

from __future__ import annotations

from datetime import date, timedelta

from gym_coach.context import equipment_for, gym_for, profile_text
from gym_coach.prompts import CARDIO_SENTENCE, PLAN_SYSTEM, plan_prompt

STRENGTH_PER_WEEK = 3


class PlanError(Exception):
    """The model could not produce a valid plan."""


def week_dates(week_start: date) -> list[str]:
    return [(week_start + timedelta(days=i)).isoformat() for i in range(7)]


def validate(data, dates: list[str], equipment: dict[str, set[str]]) -> list[dict]:
    """Return clean sessions (gym set by code) or raise PlanError naming the problem."""
    if not isinstance(data, dict) or not isinstance(data.get("sessions"), list):
        raise PlanError("answer must be an object with a 'sessions' list")
    sessions, seen = [], set()
    for s in data["sessions"]:
        if not isinstance(s, dict):
            raise PlanError("each session must be an object")
        day, kind = s.get("date"), s.get("kind")
        if day not in dates:
            raise PlanError(f"date {day!r} is not in the planned week")
        if day in seen:
            raise PlanError(f"two sessions on {day}")
        seen.add(day)
        if kind not in ("strength", "cardio"):
            raise PlanError(f"kind {kind!r} on {day} must be strength or cardio")
        gym = gym_for(date.fromisoformat(day))
        exercises = s.get("exercises") or []
        if kind == "cardio":
            exercises = []
        else:
            if date.fromisoformat(day).weekday() == 5:
                raise PlanError(f"{day} is a Saturday: no late-afternoon strength session")
            if not exercises:
                raise PlanError(f"strength session on {day} has no exercises")
            for ex in exercises:
                name = str(ex.get("equipment", "")).strip().lower()
                if name not in equipment[gym]:
                    raise PlanError(
                        f"{ex.get('name')!r} on {day} uses {ex.get('equipment')!r}, "
                        f"which is not in the {gym} gym list"
                    )
        sessions.append({"date": day, "gym": gym, "kind": kind, "exercises": exercises})
    if sum(s["kind"] == "strength" for s in sessions) != STRENGTH_PER_WEEK:
        raise PlanError(f"need exactly {STRENGTH_PER_WEEK} strength sessions")
    return sorted(sessions, key=lambda s: s["date"])


def _message(data: dict) -> str:
    text = str(data.get("message") or "").strip()
    if CARDIO_SENTENCE not in text:
        text = (text + "\n\n" if text else "") + CARDIO_SENTENCE + "."
    return text


def propose(claude, store, model: str, week_start: date, change: str | None = None,
            profile_path=None, equipment_path=None, illustrations=None) -> str:
    """Ask the coach model for a week plan, validate it, store it as `proposed`.

    One regeneration is allowed after a rejected answer; a second rejection raises PlanError.
    Returns the message to show the user. With `change`, the stored proposal (if any) is revised.
    """
    ekw = {"path": equipment_path} if equipment_path else {}
    equipment = {g: equipment_for(g, **ekw) for g in ("home", "parents")}
    profile = profile_text(profile_path) if profile_path else profile_text()
    dates = week_dates(week_start)
    ids = {g: illustrations.allowed(equipment[g]) for g in equipment} if illustrations else None
    previous = store.plan_sessions(dates[0], dates[-1]) or None
    error = None
    for _ in range(2):
        data = claude.json(
            model,
            plan_prompt(profile, equipment["home"], equipment["parents"], dates,
                        previous, change, error, ids),
            system=PLAN_SYSTEM,
        )
        try:
            sessions = validate(data, dates, equipment)
            break
        except PlanError as exc:
            error = str(exc)
    else:
        raise PlanError(f"Plan rejected twice: {error}")
    for s in sessions:  # an illustration id that is not in the gym's list is dropped
        for ex in s["exercises"]:
            if ex.get("illustration") not in (ids or {}).get(s["gym"], ()):
                ex.pop("illustration", None)
    for d in dates:  # a new proposal replaces the old week
        store.delete_plan_session(d)
    for s in sessions:
        store.add_plan_session(s["date"], s["gym"], s["kind"], "proposed", s["exercises"])
    return _message(data)


def approve(store, week_start: date) -> int:
    """Mark the week's proposed sessions approved. Returns how many were approved."""
    dates = week_dates(week_start)
    n = 0
    for s in store.plan_sessions(dates[0], dates[-1]):
        if s["status"] == "proposed":
            store.set_plan_status(s["date"], "approved")
            n += 1
    return n
