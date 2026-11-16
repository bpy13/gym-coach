"""First schedule and plan proposal. Code, not the model, enforces equipment and the gym."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from gym_coach.context import (
    DEFAULT_EQUIPMENT,
    DEFAULT_PHOTOS,
    equipment_for,
    equipment_photo_ids,
    gym_for,
    photo_file,
    profile_text,
)
from gym_coach.llm import LLMError
from gym_coach.prompts import CARDIO_SENTENCE, PLAN_SYSTEM, plan_prompt

log = logging.getLogger(__name__)
STRENGTH_PER_WEEK = 3
STRENGTH_WEEKDAYS = (1, 3, 6)  # Tuesday, Thursday (home), Sunday (parents')


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
            if date.fromisoformat(day).weekday() in STRENGTH_WEEKDAYS:
                raise PlanError(f"{day} is a strength day: no cardio session on it")
            exercises = []
        else:
            if date.fromisoformat(day).weekday() not in STRENGTH_WEEKDAYS:
                raise PlanError(f"{day} is not a strength day: strength is Tuesday, Thursday, Sunday")
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


def _has_machine_photo(gym, ex, ids, photos_dir) -> bool:
    photo_id = ids.get(str(ex.get("equipment", "")).strip().lower())
    return bool(photo_id and photo_file(gym, photo_id, photos_dir))


def ensure_pictures(sessions: list[dict], illustrations, allowed: dict[str, dict[str, str]],
                    equipment: dict[str, set[str]], claude=None, model: str | None = None,
                    equipment_path=None, photos_dir=None,
                    allow_replace: bool = True) -> list[str]:
    """Make every strength exercise carry Brian's machine photo or a valid illustration id.

    First by matching the exercise name against the gym's catalogue (code); what still has
    nothing is put to the model once (an id, or a replacement exercise that has one).
    Edits `sessions` in place; returns the names that still have no picture.
    """
    photos_dir = photos_dir or DEFAULT_PHOTOS
    photo_ids = {g: equipment_photo_ids(g, equipment_path or DEFAULT_EQUIPMENT)
                 for g in equipment}
    missing = []  # (session, exercise)
    for s in sessions:
        if s["kind"] != "strength":
            continue
        gym = s["gym"]
        for ex in s["exercises"]:
            if _has_machine_photo(gym, ex, photo_ids[gym], photos_dir):
                ex.pop("illustration", None)
                continue
            if ex.get("illustration") in allowed.get(gym, {}):
                continue
            ex.pop("illustration", None)
            found = illustrations.match(ex.get("name", ""), ex.get("equipment", ""),
                                        allowed.get(gym, {}))
            if found:
                ex["illustration"] = found
            else:
                missing.append((s, ex))
    if missing and claude is not None and any(allowed.values()):
        _ask_for_pictures(missing, allowed, equipment, claude, model, allow_replace)
    left = [ex.get("name", "?") for s, ex in missing
            if not ex.get("illustration")
            and not _has_machine_photo(s["gym"], ex, photo_ids[s["gym"]], photos_dir)]
    for name in left:
        log.warning("exercise %r has no picture", name)
    return left


def _ask_for_pictures(missing, allowed, equipment, claude, model, allow_replace=True) -> None:
    lines = [f"{n}. {ex.get('name')} ({ex.get('equipment')}) at the {s['gym']} gym"
             for n, (s, ex) in enumerate(missing)]
    lists = "\n\n".join(
        f"{g} gym illustration ids (id: exercise):\n"
        + "\n".join(f"{i}: {n}" for i, n in allowed[g].items())
        for g in sorted({s["gym"] for s, _ in missing}) if allowed.get(g))
    prompt = (
        "These exercises have no picture. For each, give the id of an illustration of that "
        "same exercise from its gym's list, or, when none shows it, a replacement exercise "
        "that has one (same muscle group, equipment from that gym's list).\n"
        + "\n".join(lines) + "\n\n" + lists + "\n\nAnswer with JSON only: "
        '{"fixes": [{"n": 0, "illustration": "<id>"} or {"n": 1, "replace": {"name": "...", '
        '"equipment": "...", "illustration": "<id>"}}]}'
    )
    try:
        data = claude.json(model, prompt, system="You are a careful personal gym coach.")
        fixes = data.get("fixes") or []
    except (LLMError, AttributeError) as exc:  # the picture is a nicety: never block the proposal
        log.warning("asking for exercise pictures failed: %s", exc)
        return
    for fix in fixes if isinstance(fixes, list) else []:
        try:
            s, ex = missing[int(fix["n"])]
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        gym = s["gym"]
        if allow_replace and isinstance(fix.get("replace"), dict):
            rep = fix["replace"]
            eq = str(rep.get("equipment", "")).strip().lower()
            if rep.get("illustration") in allowed.get(gym, {}) and eq in equipment[gym]                     and rep.get("name"):
                ex.update(name=str(rep["name"]), equipment=rep["equipment"],
                          illustration=rep["illustration"])
        elif fix.get("illustration") in allowed.get(gym, {}):
            ex["illustration"] = fix["illustration"]


def propose(claude, store, model: str, week_start: date, change: str | None = None,
            profile_path=None, equipment_path=None, illustrations=None,
            photos_dir=None) -> str:
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
    if illustrations is not None:  # code makes sure every exercise has a picture
        ensure_pictures(sessions, illustrations, ids, equipment, claude, model,
                        equipment_path, photos_dir)
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
