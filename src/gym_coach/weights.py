"""The weight to use for a planned exercise, from what he last lifted (Task 14l). No model call.

Rule (Task 14m, replacing 14k's): the last day's sets are labelled by `read_sets`. Too easy:
one step up from his last top weight. Steady: his last top weight, aim for one more rep.
Struggling: stay at the weight where it went wrong; one step under when the day before was
struggling at that same weight too.

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
TOO_EASY, STEADY, STRUGGLING = "too easy", "steady", "struggling"
FELL_REPS = 3  # reps lost from set to set at one weight, in total, that mean struggling
# his own word on effort (Task 14n): it beats the rep count. Negated words first; with both
# kinds of word, hard wins (the safer read)
NOT_EASY = ("not easy", "not that easy", "wasn't easy", "not light", "not too light")
NOT_HARD = ("not hard", "not that hard", "wasn't hard", "not heavy", "not tough")
HARD_WORDS = ("barely", "hard", "struggl", "tough", "heavy", "difficult", "grind", "fail",
              "exhaust", "brutal", "could not", "couldn't", "almost didn")
EASY_WORDS = ("easy", "light", "effortless", "comfortable")
SAID_HARD, SAID_EASY = "you said it was hard", "you said it was easy"
NO_RECORD = "no earlier record"


def effort_kind(text) -> str | None:
    """"hard", "easy" or None (no word, or a neutral one like "ok") from his effort words."""
    low = " ".join(str(text or "").lower().replace("’", "'").split())
    if any(w in low for w in NOT_EASY):
        return "hard"
    if any(w in low for w in NOT_HARD):
        return "easy"
    if any(w in low for w in HARD_WORDS):
        return "hard"
    if any(w in low for w in EASY_WORDS):
        return "easy"
    return None


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

    def last_time(self, ex: dict, gym: str) -> str:
        """What he did the last time, every set (Task 14o), e.g. "last time, 17 Nov: 21 kg x
        15, 28 kg x 12, 28 kg x 15"; a machine's last day at the other gym only is named with
        that gym; "no earlier record" when he never did it."""
        days = self.days_of(ex, gym)
        free = is_free(ex)
        here = [e for e in days if free or e["gym"] in (gym, None)]
        entry = here[0] if here else (days[0] if days else None)
        if entry is None:
            return NO_RECORD
        where = "" if here else f" ({GYM_LABELS.get(entry['gym'], str(entry['gym']))})"
        d = date.fromisoformat(entry["date"])
        return (f"last time{where}, {d.day} {d:%b}: "
                + ", ".join(reports.set_text(r) for r in entry["sets"]))

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
        rng = _range(last, ex)
        step = self.step(ex, gym, here, top)
        said = reports.day_text(last)
        label, why, at = read_sets(last["sets"], rng)
        if label == TOO_EASY:
            felt = "felt easy, you said" if why == SAID_EASY else "felt easy"
            weight, note = top + step, f"last time {top:g} kg {felt}: {said}"
        elif label == STRUGGLING:
            at = top if at is None else at
            before = (read_sets(here[1]["sets"], _range(here[1], ex))
                      if len(here) > 1 else (STEADY, "", None))
            if before[0] == STRUGGLING and before[2] == at and at - step > 0:
                weight, note = at - step, f"one step down, {why} twice in a row: {said}"
            else:
                weight, note = at, f"again, {why} last time: {said}"
        elif why:  # he said it was hard (Task 14n)
            weight, note = top, f"again, {why} last time: {said}"
        else:
            weight, note = top, f"again, aim for one more rep: {said}"
        if last["exercise"].strip().lower() != str(ex.get("name", "")).strip().lower():
            note += f" ({last['exercise']})"
        if other:
            note += f"; {other}"
        weight = round(weight, 2)
        return {"weight_kg": int(weight) if weight == int(weight) else weight, "note": note,
                "label": label}


def _range(entry: dict, ex: dict) -> tuple[int, int] | None:
    """The rep range planned the day the sets were logged, else today's."""
    if entry.get("range"):
        return entry["range"]
    if ex.get("rep_low") is not None and ex.get("rep_high") is not None:
        return int(ex["rep_low"]), int(ex["rep_high"])
    return None


def read_sets(sets: list[dict], rng: tuple[int, int] | None) -> tuple[str, str, float | None]:
    """How one day's sets of an exercise went, in logged order (Task 14m; thresholds are the
    orchestrator's call, 2026-11-24): (label, why, the weight where it went wrong or None).

    First, TOO_EASY when the last set was at the day's top weight and reached the top of the
    range (it wins over a fall of reps before it). Then
    STRUGGLING: reps fell from set to set at the same weight by FELL_REPS or more in total,
    or he lowered the weight during the day, or a set ended under the bottom of the range.
    TOO_EASY: he raised the weight and still reached the top of the range on the last set,
    or every set reached the top or more. STEADY otherwise.

    His own word wins over all of this (Task 14n): the last set with an effort word he gave
    decides. Easy: TOO_EASY. Hard: never TOO_EASY; STRUGGLING stays, the rest is STEADY
    ("you said it was hard": hold the weight)."""
    rows = [r for r in sets if r.get("reps") is not None]
    if not rows:
        return STEADY, "", None
    said = next((k for k in (effort_kind(r.get("effort")) for r in reversed(rows)) if k), None)
    if said == "easy":
        return TOO_EASY, SAID_EASY, None
    label, why, at = _by_reps(rows, rng)
    if said == "hard" and label != STRUGGLING:
        return STEADY, SAID_HARD, None
    return label, why, at


def _by_reps(rows: list[dict], rng: tuple[int, int] | None) -> tuple[str, str, float | None]:
    """The label from the reps and weights alone (Task 14m)."""
    known = [r["weight_kg"] for r in rows if r["weight_kg"] is not None]
    if rng and rows[-1]["reps"] >= rng[1] and rows[-1]["weight_kg"] == (
            max(known) if known else None):
        # the last set at the day's top weight reached the top: too easy wins (2026-11-24)
        return TOO_EASY, "felt easy", None
    pairs = list(pairwise(rows))
    same =[(a, b) for a, b in pairs if a["weight_kg"] == b["weight_kg"]]
    fell = sum(max(0, a["reps"] - b["reps"]) for a, b in same)
    if fell >= FELL_REPS:
        at = max((a["weight_kg"] for a, b in same if a["reps"] > b["reps"]
                  and a["weight_kg"] is not None), default=None)
        return STRUGGLING, "reps fell", at
    lowered = [a["weight_kg"] for a, b in pairs if a["weight_kg"] is not None
               and b["weight_kg"] is not None and b["weight_kg"] < a["weight_kg"]]
    if lowered:
        return STRUGGLING, "you lowered the weight", max(lowered)
    under = [r for r in rows if rng and r["reps"] < rng[0]]
    if under:
        at = max((r["weight_kg"] for r in under if r["weight_kg"] is not None), default=None)
        return STRUGGLING, f"a set under {rng[0]} reps", at
    raised = any(a["weight_kg"] is not None and b["weight_kg"] is not None
                 and b["weight_kg"] > a["weight_kg"] for a, b in pairs)
    if rng and ((raised and rows[-1]["reps"] >= rng[1])
                or all(r["reps"] >= rng[1] for r in rows)):
        return TOO_EASY, "felt easy", None
    return STEADY, "", None


ADVICE = {"too easy": "go up one step for the next set", "steady": "hold the weight",
          "struggling": "hold, or drop one step, for the next set"}


def today_text(sets: list[dict], rng: tuple[int, int] | None) -> str:
    """Today's sets so far, read the same way, for the coach (Task 14m), told only when he
    asks for advice (Task 14o). With no word from him on effort and the last set over the
    top of the range, the coach asks how it felt instead of calling it easy (Task 14n)."""
    label, why, _ = read_sets(sets, rng)
    rows = [r for r in sets if r.get("reps") is not None]
    if (label == TOO_EASY and rng and rows and rows[-1]["reps"] > rng[1]
            and not any(effort_kind(r.get("effort")) for r in rows)):
        return (f"over the {rng[0]}-{rng[1]} range and no word from him on effort: if he asks "
                "for advice, ask how it felt first (easy: up one step; hard: hold)")
    return f"{label}" + (f" ({why})" if why and why != "felt easy" else "") + f": {ADVICE[label]}"


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
        ex.pop("weight_label", None)
        if ex.get("own"):
            continue
        found = hist.weight_for(ex, session["gym"])
        if not found:
            continue
        if found["weight_kg"] is not None:
            ex["weight_kg"] = found["weight_kg"]
            ex["weight_label"] = found["label"]
        ex["weight_note"] = found["note"]
    return out


def with_last_time(store, session: dict | None) -> dict | None:
    """A copy of a strength session with each exercise's "last_time" (Task 14o: shown in
    place of a suggested weight); other sessions as they are."""
    if not session or session.get("kind") != "strength" or not session.get("exercises"):
        return session
    out = copy.deepcopy(session)
    hist = History(store, session["date"])
    for ex in out["exercises"]:
        ex["last_time"] = hist.last_time(ex, session["gym"])
    return out


def stored(exercises: list[dict]) -> list[dict]:
    """Exercises as they are saved: "last_time" is worked out each time, never stored."""
    return [{k: v for k, v in e.items() if k != "last_time"} for e in exercises]


def session(store, day: str, today: str) -> dict | None:
    """The plan of `day` as he should see it: a strength session not started (no set logged
    that day, today or later) gets the weights from his history. Today's is written into the
    stored session once, so a weight he changes before the first set stays. Stored sets are
    never changed. Every strength session carries "last_time" per exercise (Task 14o); the
    weight stays for when he asks what to lift."""
    s = store.plan_session(day)
    if (not s or s["kind"] != "strength" or day < today or store.logged_sets(day)
            or store.get(APPLIED_KEY + day) == "1"):
        return with_last_time(store, s)
    new = apply(store, s)
    if day == today:
        store.add_plan_session(new["date"], new["gym"], new["kind"], new["status"],
                               stored(new["exercises"]))
        store.set(APPLIED_KEY + day, "1")
    return with_last_time(store, new)
