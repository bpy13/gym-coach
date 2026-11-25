"""Meal estimates from a photo or a text, the daily total against targets, and corrections."""

from __future__ import annotations

from datetime import datetime

from gym_coach import targets
from gym_coach.llm import LLMError

ESTIMATE_SYSTEM = """You estimate one meal's calories and protein for a gym-goer's food log.
Answer JSON: {"meal": true, "what": "<what the photo shows, a few words>",
"description": "<short name of the meal>", "kcal": 650, "protein_g": 35}
Use the image and/or the text. A note such as "half portion" changes the amounts. Give your
best single number for each, never a range. A photo that shows no food or drink (gym
equipment, a weight plate, a screen) is not a meal: answer {"meal": false, "what": "..."}.
A running or workout app's summary picture (Strava, Nike Run Club, Garmin, a phone's fitness
app: a distance, a time, a pace, often a map, in any language) is a run, not a meal: answer
{"meal": false, "run": true, "what": "..."}."""


def _number(value) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        raise LLMError("The meal estimate had no usable numbers") from None
    if n < 0:
        raise LLMError("The meal estimate had no usable numbers")
    return n


def log_meal(store, claude, model: str, now: datetime, text: str | None = None,
             jpeg: bytes | None = None) -> dict:
    """Estimate one meal with the fast model, store the estimate (never the image), return it.
    A photo the model says is not a meal is stored as nothing: {"meal": False, "what": ...}."""
    prompt = text or "Estimate the meal in the photo."
    data = claude.json(model, prompt, system=ESTIMATE_SYSTEM, jpeg=jpeg)
    if not isinstance(data, dict):
        raise LLMError("The meal estimate was not an object")
    if data.get("meal") is False:
        return {"meal": False, "run": data.get("run") is True,
                "what": str(data.get("what") or "something else").strip()}
    meal = {"description": str(data.get("description") or text or "meal").strip(),
            "kcal": round(_number(data.get("kcal"))),
            "protein_g": round(_number(data.get("protein_g")))}
    store.add_meal(now.isoformat(), meal["description"], meal["kcal"], meal["protein_g"])
    return meal


def correct_last(store, day: str, kcal, protein_g=None) -> bool:
    """Replace the day's latest meal's numbers with the ones Brian gave."""
    k = _number(kcal)
    p = None if protein_g is None else _number(protein_g)
    return store.update_last_meal(day, round(k), None if p is None else round(p))


def day_total(store, day: str) -> tuple[int, int]:
    meals = store.meals_on(day)
    return round(sum(m["kcal"] for m in meals)), round(sum(m["protein_g"] for m in meals))


def total_line(store, day: str, profile_path) -> str:
    """'Today: 1,420 of 2,000 kcal, 78 of 130 g protein.' (without targets if no profile)."""
    kcal, protein = day_total(store, day)
    try:
        t = targets.current_targets(store, profile_path)
    except (ValueError, OSError):
        return f"Today: {kcal:,} kcal, {protein:,} g protein."
    return f"Today: {kcal:,} of {t.kcal:,} kcal, {protein:,} of {t.protein_g:,} g protein."


def reply(store, day: str, meal: dict, profile_path, header: str = "About") -> str:
    return (f"{header} {meal['kcal']:,} kcal, {meal['protein_g']:,} g protein "
            f"({meal['description']}). {total_line(store, day, profile_path)} "
            "Estimates from photos are rough; correct me by replying, e.g. \"that was 400 kcal\".")
