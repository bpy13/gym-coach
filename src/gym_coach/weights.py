"""The weight to use for a planned exercise, from what he last lifted (Task 14l). No model call.

Rule (Task 14k, orchestrator's call 2026-11-24): start from the last day's top weight; one step
up when every set of that day reached the top of the rep range or more; one step down when a
set missed the bottom; keep it otherwise.

History is matched by the exercise name first, then by the same equipment at the same gym
(the plan of the day the sets were logged names the equipment), so "Chest press" finds
"Machine chest press". A machine's history from the other gym is a note only; dumbbell and
barbell weights are the same at either gym.
"""

from __future__ import annotations

import copy
from collections import Counter
from datetime import date, timedelta
from itertools import pairwise

from gym_coach import reports

HISTORY_WEEKS = 8  # how far back history is read
MATCH_DAYS = 10  # per exercise, its last days read (some may be at the other gym)
APPLIED_KEY = "weights:"  # + day: today's weights were written into the stored session
DUMBBELL_STEP, OTHER_STEP = 2.0, 2.5
FREE_WORDS = ("dumbbell", "barbell", "kettlebell")
# words that say nothing about the movement: an equipment match needs another shared word
GENERIC = {"machine", "machines", "cable", "cables", "dumbbell", "dumbbells", "barbell",
           "seated", "standing", "with", "the", "a", "an", "on", "and", "of", "one-arm",
           "single-arm", "two-arm", "rope", "bar", "handle"}
GYM_LABELS = {"home": "home gym", "parents": "parents gym"}


def _words(name: str) -> set[str]:
    return {w for w in reports._key(name).replace("(", " ").replace(")", " ").split()
            if w not in GENERIC}


def _gear(text) -> str:
    return " ".join(str(text or "").lower().split())


def is_free(ex: dict) -> bool:
    """Dumbbell, barbell or kettlebell work: the weight means the same at either gym."""
    name = str(ex.get("name", "")).lower()
    return any(w in name for w in FREE_WORDS) or any(
        w in _gear(ex.get("equipment")) for w in ("dumbbell", "kettlebell"))


class History:
    """What he logged before `day` (HISTORY_WEEKS back), with each day's gym and equipment."""

    def __init__(self, store, day: str):
        self.store = store
        since = (date.fromisoformat(day) - timedelta(weeks=HISTORY_WEEKS)).isoformat()
        self.past = store.recent_sets(day, since, MATCH_DAYS)
        self._plans: dict[str, dict] = {}
        for days in self.past.values():
            for entry in days:
                plan = self._plan(entry["date"])
                entry["gym"] = plan.get("gym")
                mine = self._planned(entry)
                entry["equipment"] = _gear((mine or {}).get("equipment"))
                entry["range"] = ((int(mine["rep_low"]), int(mine["rep_high"]))
                                  if mine and not mine.get("own") and "rep_low" in mine
                                  and "rep_high" in mine else None)

    def _plan(self, day: str) -> dict:
        if day not in self._plans:
            self._plans[day] = self.store.plan_session(day) or {}
        return self._plans[day]

    def _planned(self, entry: dict) -> dict | None:
        k = reports._key(entry["exercise"])
        return next((e for e in self._plan(entry["date"]).get("exercises") or []
                     if reports._key(str(e.get("name", ""))) == k), None)

    def days_of(self, ex: dict, gym: str) -> list[dict]:
        """The exercise's earlier days, newest first: by name, else (a machine, not free
        weights: the dumbbell rack holds every dumbbell exercise) by the same equipment at the
        same gym with the most shared name words (a tie or no shared word: none)."""
        found = self.past.get(reports._key(str(ex.get("name", ""))))
        if found:
            return found
        gear = _gear(ex.get("equipment"))
        if not gear or is_free(ex):
            return []
        mine, best, ties = _words(str(ex.get("name", ""))), 0, []
        for days in self.past.values():
            if not any(e["gym"] == gym and e["equipment"] == gear for e in days):
                continue
            shared = len(mine & _words(days[0]["exercise"]))
            if shared > best:
                best, ties = shared, [days]
            elif shared == best and shared:
                ties.append(days)
        return ties[0] if best and len(ties) == 1 else []

    def step(self, ex: dict, gym: str, days: list[dict], last: float) -> float:
        """The smallest gap in the exercise's own weights; else the smallest gap of another
        exercise on the same equipment at that gym; else (a machine) the commonest gap of
        that gym's machines of its kind (cable or pin stack) that divides `last`; else 2 kg
        for dumbbells, 2.5 kg (orchestrator's call, 2026-11-24)."""
        own = _gap(r["weight_kg"] for e in days for r in e["sets"])
        if own:
            return own
        free = is_free(ex)
        gear = _gear(ex.get("equipment"))
        gaps_here = []  # (equipment, gap) per other exercise at this gym
        for d in self.past.values():
            mine = [e for e in d if e["gym"] == gym]
            g = _gap(r["weight_kg"] for e in mine for r in e["sets"])
            if mine and g and not is_free({"name": mine[0]["exercise"],
                                           "equipment": mine[0]["equipment"]}):
                gaps_here.append((mine[0]["equipment"], g))
        same = [g for e, g in gaps_here if gear and e == gear]
        if same:
            return min(same)
        if not free:
            cable = "cable" in gear
            gaps = Counter(g for e, g in gaps_here if ("cable" in e) == cable
                           and abs(last / g - round(last / g)) < 1e-6)
            if gaps:
                return min(gaps.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        name = str(ex.get("name", "")).lower() + " " + gear
        return DUMBBELL_STEP if "dumbbell" in name else OTHER_STEP

    def weight_for(self, ex: dict, gym: str) -> dict | None:
        """{"weight_kg": float or None, "note": text} for a planned exercise with history, or
        None. weight_kg is None when only the other gym's machine has history (a note)."""
        days = self.days_of(ex, gym)
        if not days:
            return None
        free = is_free(ex)
        # a day with no plan (gym unknown) counts as here
        here = [e for e in days if free or e["gym"] in (gym, None)]
        there = [e for e in days if not free and e["gym"] not in (gym, None)]
        other = (f"{GYM_LABELS.get(there[0]['gym'], str(there[0]['gym']) + ' gym')}: "
                 f"{reports.day_text(there[0])}") if there else None
        last = here[0] if here else None
        top = reports.top_weight(last) if last else None
        if top is None:
            return {"weight_kg": None, "note": other} if other else None
        rng = last["range"]
        if rng is None and ex.get("rep_low") is not None and ex.get("rep_high") is not None:
            rng = int(ex["rep_low"]), int(ex["rep_high"])
        reps = [r["reps"] for r in last["sets"] if r["reps"] is not None]
        step = self.step(ex, gym, here, top)
        said = reports.day_text(last)
        if rng and reps and min(reps) >= rng[1]:
            weight, note = top + step, f"up from {said}"
        elif rng and reps and min(reps) < rng[0] and top - step > 0:
            weight, note = top - step, f"down from {said}"
        else:
            weight, note = top, f"last time {said}"
        if last["exercise"].strip().lower() != str(ex.get("name", "")).strip().lower():
            note += f" ({last['exercise']})"
        if other:
            note += f"; {other}"
        weight = round(weight, 2)
        return {"weight_kg": int(weight) if weight == int(weight) else weight, "note": note}


def _gap(weights) -> float | None:
    seen = sorted({float(w) for w in weights if w})
    gaps = [round(b - a, 2) for a, b in pairwise(seen) if b - a > 1e-6]
    return min(gaps) if gaps else None


def apply(store, session: dict) -> dict:
    """A copy of a strength session with each planned exercise's weight from his history
    and its "weight_note" (where it came from); his own added exercises and exercises
    with no history keep the stored weight."""
    if not session or session.get("kind") != "strength" or not session.get("exercises"):
        return session
    out = copy.deepcopy(session)
    hist = History(store, session["date"])
    for ex in out["exercises"]:
        ex.pop("weight_note", None)
        if ex.get("own"):
            continue
        found = hist.weight_for(ex, session["gym"])
        if not found:
            continue
        if found["weight_kg"] is not None:
            ex["weight_kg"] = found["weight_kg"]
        ex["weight_note"] = found["note"]
    return out


def session(store, day: str, today: str) -> dict | None:
    """The plan of `day` as he should see it: a strength session not started (no set logged
    that day, today or later) gets the weights from his history. Today's is written into the
    stored session once, so a weight he changes before the first set stays. Stored sets are
    never changed."""
    s = store.plan_session(day)
    if (not s or s["kind"] != "strength" or day < today or store.logged_sets(day)
            or store.get(APPLIED_KEY + day) == "1"):
        return s
    new = apply(store, s)
    if day == today:
        store.add_plan_session(new["date"], new["gym"], new["kind"], new["status"],
                               new["exercises"])
        store.set(APPLIED_KEY + day, "1")
    return new
