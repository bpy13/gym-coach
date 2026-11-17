"""Turn one incoming text into a reply: commands skip the model, the rest are classified."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from gym_coach import meals, planner, reports, targets
from gym_coach.albums import shrink
from gym_coach.context import DEFAULT_EQUIPMENT, DEFAULT_PROFILE, equipment_for, profile_text
from gym_coach.llm import HK, CeilingReached, LLMError
from gym_coach.messages import proposal_message

CLASSIFY_SYSTEM = """You read the new message from Brian, a gym-goer, to his coach bot and classify
it. You also get today's chat so far (each bot line says whether it reached him) and today's
session with the sets logged per exercise and the exercise shown now. Read a short message
("35 12", "the other one", "I already told you") against those lines.
Intents: report (he reports sets he did), correction (he fixes a set he already reported),
repeat (he repeats a report whose sets are already logged, e.g. after a bot reply that was NOT
delivered: never report it again), change_today (he asks to swap, drop or change the weight of
an exercise of TODAY's session), approve (he accepts the proposed plan), change_plan (he asks
to change a future week's plan), skip (he skips today's whole session), body (body weight; a
waist he mentions is still stored), progress (asks for his numbers), meal (he says what he
ate, or the photo with this caption is food he ate), meal_correction (he fixes the calories or
protein of the last meal), log_check (he says sets are missing from the log or the log is
wrong, without giving the right numbers, e.g. "X and Y now missing"), unclear (a short message
you cannot place against the chat and session), question (anything else, including a question
about a photo of gym equipment).
Answer JSON: {"intent": "<one intent>", "sets": [{"exercise": "...", "weight_kg": 35,
"reps": 10, "effort": null, "own": false}], "change": "<the requested change, for change_plan>",
"today": {"action": "swap|drop|weight", "exercise": "<name in today's session>",
"new_exercise": "<for swap>", "equipment": "<for swap: exactly as in today's gym list>",
"weight_kg": <number or null>}, "question": "<one short question, for unclear>",
"kcal": <number, for meal_correction>, "protein_g": <number or null, for meal_correction>,
"weight_kg": <number or null, for body>, "waist_cm": <number or null, for body>}
"sets" has one entry per set: expand "3x10 at 40 kg" into three entries and "35kg 10 10 8" into
three entries. Use the exercise names of today's session. A set of an exercise that is not in
today's session and is not a clear match for one of them is his own exercise: keep his name
for it and set "own": true. For a correction list every set of each exercise he corrects, with
the corrected values. Use an empty list when there are no sets.
A change to an exercise while today's session is on is change_today, never change_plan. A
message about missing or wrong sets is log_check, never change_plan."""

BODY_JUMP_KG = 5.0
PENDING_BODY = "pending:body"
PENDING_CHANGE = "pending:plan_change"  # a future-week change kept for the next /propose
PENDING_REVISE = "pending:revise"  # a change to the proposed week, waiting for his yes
SAME_AGAIN = {"same again", "same", "again", "same as before", "same as last"}
CHAT_LINES = 12  # today's chat lines each model call sees (Task 14g)
FLOW_KEY = "flow:"  # + day: index of the exercise shown now (kv); absent = not started
PASSED_KEY = "passed:"  # + day: exercises he moved on from with next/done/skip, "|"-joined
PHOTO_EDGE = 1024  # px; his photos are shrunk to this before an image call (Task 14h)
TYPO_HIGH, TYPO_LOW = 1.5, 0.5  # a weight outside these times the plan or last set: "Typo?"
NEXT_WORDS = {"next", "done", "skip"}  # orchestrator's call, 2026-11-16; Brian may change it
YES = {"yes", "y", "yep", "yeah", "ok", "correct", "right", "confirm"}

HELP = ("Hi! I'm your gym coach. I send the day's session; reply with what you did "
        "(e.g. \"chest press 35 kg 10 10 8\"). Commands: /today, /progress, /cost. "
        "I give general fitness guidance, not medical advice.")


class Router:
    def __init__(self, store, claude, model_fast: str, model_coach: str, now=None,
                 profile_path=None, equipment_path=None, illustrations=None):
        self.store = store
        self.claude = claude
        self.fast = model_fast
        self.coach = model_coach
        self._now = now or (lambda: datetime.now(HK))
        self._profile_path = profile_path
        self._equipment_path = equipment_path or DEFAULT_EQUIPMENT
        self.album_session: dict | None = None  # first session of the last proposal
        self.exercise_to_send: tuple[dict, int] | None = None  # (session, index) to show next
        # for the app's trace of the last message: the sorting call's JSON, or "local" when
        # no model call sorted it; and the error that became a "Sorry" reply, if any
        self.understood: str | None = None
        self.error: str | None = None
        # keyword arguments for planner.propose (it falls back to data\ when they are None)
        self._planner_kw = {k: v for k, v in
                            (("profile_path", profile_path), ("equipment_path", equipment_path),
                             ("illustrations", illustrations))
                            if v}

    def handle(self, text: str) -> str:
        """Reply text for one message from the allowed user."""
        self.understood, self.error = "local", None
        return self._guarded(self._handle, text.strip())

    def handle_photo(self, jpeg: bytes, caption: str | None = None) -> str:
        """Reply to a photo. A caption is read like a text (only a meal sends the image to the
        meal estimate); without one, the image call says whether it is a meal at all."""
        self.understood, self.error = "local", None
        try:
            jpeg = shrink(jpeg, PHOTO_EDGE)
        except (OSError, ValueError):
            pass  # not an image Pillow can read: sent as it came
        if caption and caption.strip():
            return self._guarded(self._handle, caption.strip(), jpeg)
        self.understood = "photo without caption: meal estimate"
        return self._guarded(self._meal, None, jpeg)

    def _guarded(self, fn, *args) -> str:
        try:
            return fn(*args)
        except CeilingReached:
            self.error = "monthly ceiling reached"
            return (f"This month's US${self.claude.ceiling_usd:g} limit on AI calls is reached. "
                    "I can't read new messages until next month; /today and /cost still work.")
        except (LLMError, planner.PlanError) as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            return f"Sorry, I could not do that ({exc}). Please try again."

    def _today(self) -> date:
        return self._now().astimezone(HK).date()

    def _handle(self, text: str, jpeg: bytes | None = None) -> str:
        """`jpeg`: the photo this text came with as its caption."""
        command = text.split()[0].lower() if text.startswith("/") else None
        if command == "/start":
            return HELP
        if command == "/today":
            return self._today_text()
        if command == "/propose":
            note = self.store.get(PENDING_CHANGE) or None
            reply = self._propose(note)
            self.store.set(PENDING_CHANGE, "")
            return reply
        if command == "/progress":
            return "Progress numbers are coming soon."
        if command == "/cost":
            return (f"This month: US${self.claude.month_cost():.2f} "
                    f"of US${self.claude.ceiling_usd:g}.")
        pending = self._pending_body(text)
        if pending is None:
            pending = self._pending_revise(text)
        if pending is not None:
            return pending
        flow = self._flow_reply(text)
        if flow is not None:
            return flow
        day = self._today().isoformat()
        if text.lower().strip(" .!") in SAME_AGAIN:
            again = self._same_again(day)
            if again is not None:
                return again
        context = self.context(day)
        lead = ("New message from Brian (sent with a photo; this text is its caption)"
                if jpeg is not None else "New message from Brian")
        data = self.claude.json(self.fast, f"{context}\n\n{lead}: {text}",
                                system=CLASSIFY_SYSTEM)
        if not isinstance(data, dict):
            data = {}
        self.understood = json.dumps(data, ensure_ascii=False)
        intent = data.get("intent")
        if intent == "report" and self._repeats_undelivered(day, text):
            intent = "repeat"
        if intent == "repeat":
            return self._state_reply(day)
        if intent == "unclear":
            question = str(data.get("question") or "").strip()
            return question or "Sorry, I could not place that. Which exercise do you mean?"
        if intent == "report":
            return self._report(day, data.get("sets"))
        if intent == "change_today":
            return self._change_today(day, data.get("today"))
        if intent == "correction":
            if not reports.correct(self.store, day, data.get("sets")):
                return "I could not tell what to correct. Say e.g. \"chest press was 30 kg\"."
            return reports.format_log(self.store, day, "Corrected:")
        if intent == "log_check":
            return self._state_reply(day, "Today's log, nothing changed:")
        if intent == "approve":
            return self._approve()
        if intent == "change_plan":
            return self._change_plan(day, str(data.get("change") or text))
        if intent == "skip":
            if not self.store.plan_session(day):
                return "There is no session planned today."
            self.store.set_plan_status(day, "skipped")
            return "Skipped today's session."
        if intent == "meal":
            return self._meal(text, jpeg)
        if intent == "meal_correction":
            try:
                fixed = meals.correct_last(self.store, day, data.get("kcal"),
                                           data.get("protein_g"))
            except LLMError:
                fixed = False
            if not fixed:
                return "I could not tell what to correct. Say e.g. \"that was 400 kcal\"."
            return "Corrected the last meal. " + meals.total_line(self.store, day, self._profile())
        if intent == "body":
            return self._body(day, data.get("weight_kg"), data.get("waist_cm"))
        if intent == "progress":
            return "That is coming soon."
        return self._answer(text, context, jpeg)

    # reports during a session
    def _report(self, day: str, raw_sets, remap: bool = True) -> str:
        shown = self._shown(day)
        raw = self._to_shown(raw_sets, shown) if remap else raw_sets
        before = self.store.logged_sets(day)
        logged = reports.log_report(self.store, day, raw)
        if not logged:
            return "I could not find any sets in that. Try \"chest press 35 kg 10 10 8\"."
        typo = self._typo(day, logged, before)
        added = self._add_own(day, raw, logged)
        if shown is None:
            return reports.format_log(self.store, day) + typo
        index = shown[1]
        session = self.store.plan_session(day)  # with his own exercises added
        exercises = session["exercises"]
        names = [e["name"].strip().lower() for e in exercises]
        reported = {names.index(s["exercise"].lower()) for s in logged
                    if s["exercise"].lower() in names}
        later = [i for i in reported if i > index and not exercises[i].get("own")]
        if later:  # he moved on: the pointer follows him
            index = max(later)
            self.store.set(FLOW_KEY + day, str(index))
        others = sorted(reported - {index})
        if not others:
            return self._after_report(session, index, day) + typo
        # sets for exercises other than the one shown: name them, then what is shown now
        lines = [reports.format_exercise(self.store, day, exercises[i]["name"])
                 + (" (your own exercise, added to today)" if names[i] in added else "")
                 for i in others]
        if index in reported:
            lines.append(self._after_report(session, index, day))
            return "\n".join(lines) + typo
        nxt = self._next_open(session, day, index)
        if nxt == index:
            return "\n".join(lines + [f"Now: {exercises[index]['name']}."]) + typo
        return self._move_to(session, day, index, "\n".join(lines), show=True) + typo

    def _add_own(self, day: str, raw_sets, logged: list[dict]) -> set[str]:
        """Add his own exercises (sets the sorting call marked "own") to today's strength
        session, marked "own": true, with the sets he did. Returns the names (lower case)
        added now."""
        own = {str(s.get("exercise", "")).strip().lower() for s in raw_sets or []
               if isinstance(s, dict) and s.get("own") is True}
        session = self.store.plan_session(day)
        if not own or not session or session["kind"] != "strength":
            return set()
        by_name = {e["name"].strip().lower(): e for e in session["exercises"]}
        added = set()
        for s in logged:
            key = s["exercise"].strip().lower()
            if key not in own:
                continue
            if key not in by_name:
                by_name[key] = {"name": s["exercise"], "equipment": "", "sets": 0,
                                "rep_low": s["reps"], "rep_high": s["reps"],
                                "weight_kg": s["weight_kg"] or 0, "own": True}
                session["exercises"].append(by_name[key])
                added.add(key)
            ex = by_name[key]
            ex["sets"] = max(int(ex["sets"]), reports.sets_done(self.store, day, ex["name"]))
        self._save(session)
        return added

    def _typo(self, day: str, logged: list[dict], before: list[dict]) -> str:
        """"Typo? ..." when a weight is over 1.5 times or under half the last set of that
        exercise (or, with none today, its planned weight); else ""."""
        session = self.store.plan_session(day)
        plan = {e["name"].strip().lower(): e.get("weight_kg")
                for e in (session or {}).get("exercises", [])}
        flagged = []
        for s in logged:
            key, weight = s["exercise"].strip().lower(), s["weight_kg"]
            last = [r["weight_kg"] for r in before
                    if r["exercise"].strip().lower() == key and r["weight_kg"]]
            ref = last[-1] if last else _number(plan.get(key))
            if weight and ref and not TYPO_LOW * ref <= weight <= TYPO_HIGH * ref:
                flagged.append(f"{weight:g} kg for {s['exercise']} is far from "
                               f"{'your last set' if last else 'the plan'} ({ref:g} kg)")
        if not flagged:
            return ""
        return "\nTypo? " + "; ".join(dict.fromkeys(flagged)) + ". Reply with the right number."

    def _same_again(self, day: str) -> str | None:
        """Log today's last set once more; None when nothing is logged yet today."""
        rows = self.store.logged_sets(day)
        if not rows:
            return None
        last = rows[-1]
        return self._report(day, [{"exercise": last["exercise"], "weight_kg": last["weight_kg"],
                                   "reps": last["reps"], "effort": last["effort"]}], remap=False)

    def _repeats_undelivered(self, day: str, text: str) -> bool:
        """True when his previous message was this same text and no reply to it got through."""
        lines = self.store.chat_lines(day, CHAT_LINES)
        last_in = max((i for i, r in enumerate(lines) if r["direction"] == "in"), default=None)
        if last_in is None or _norm(lines[last_in]["text"]) != _norm(text):
            return False
        replies = [r for r in lines[last_in + 1:] if r["direction"] == "out"]
        return bool(replies) and not any(r["delivered"] for r in replies)

    def _state_reply(self, day: str, header: str = "Already logged, nothing added:") -> str:
        """What is logged, what is missing and what comes next, changing nothing."""
        lines = [reports.format_log(self.store, day, header)]
        session = self.store.plan_session(day)
        if session and session["kind"] == "strength":
            missing = reports.missing(self.store, day, session)
            if missing:
                lines.append("Missing: " + ", ".join(missing))
        shown = self._shown(day)
        if shown is not None:
            lines.append(f"Now: {shown[0]['exercises'][shown[1]]['name']}.")
        return "\n".join(lines)

    # what each model call sees besides the message
    def context(self, day: str) -> str:
        """Today's last chat lines (bot lines marked delivered or not) and today's session
        with the sets logged per exercise and the exercise shown now."""
        chat = []
        for r in self.store.chat_lines(day, CHAT_LINES):
            who = "Brian" if r["direction"] == "in" else (
                "Bot" if r["delivered"] else "Bot (NOT delivered)")
            chat.append(f"{r['timestamp'][11:16]} {who}: {_one_line(r['text'])}")
        parts = ["Today's chat so far:\n" + ("\n".join(chat) if chat else "(none)")]
        parts.append(self._session_state(day))
        return "\n\n".join(parts)

    def _session_state(self, day: str) -> str:
        session = self.store.plan_session(day)
        logged = reports.format_log(self.store, day).splitlines()[1:]
        if not session or session["kind"] != "strength":
            kind = session["kind"] if session else "nothing"
            extra = ("\nLogged today:\n" + "\n".join(logged)) if logged else ""
            return f"Today's session: {kind} planned.{extra}"
        shown = self._shown(day)
        lines = [f"Today's session ({session['gym']} gym, {session['status']}):"]
        names = set()
        for i, ex in enumerate(session["exercises"]):
            name = ex["name"]
            names.add(name.strip().lower())
            done = reports.sets_done(self.store, day, name)
            if done:
                sets = reports.format_exercise(self.store, day, name).split(": ", 1)[1]
                line = f"- {name}: {done} of {ex['sets']} sets logged ({sets})"
            else:
                line = (f"- {name}: 0 of {ex['sets']} sets logged"
                        f" (plan {ex['rep_low']}-{ex['rep_high']} reps at {ex['weight_kg']} kg)")
            if shown is not None and shown[1] == i:
                line += " <- shown now"
            lines.append(line)
        others = [ln for ln in logged if ln.split(":")[0].strip().lower() not in names]
        if others:
            lines.append("Also logged: " + "; ".join(others))
        if session["status"] in ("proposed", "approved"):  # for a swap
            gear = self._equipment(session["gym"])
            if gear:
                lines.append(f"Equipment at the {session['gym']} gym: " + ", ".join(gear))
        return "\n".join(lines)

    def _equipment(self, gym: str) -> list[str]:
        try:
            return sorted(equipment_for(gym, self._equipment_path))
        except (OSError, ValueError):
            return []

    # changes to today's session (never a new week)
    def _change_today(self, day: str, change) -> str:
        session = self.store.plan_session(day)
        if not session or session["kind"] != "strength":
            return "There is no strength session today to change."
        change = change if isinstance(change, dict) else {}
        exercises = session["exercises"]
        wanted = str(change.get("exercise") or "").strip().lower()
        index = next((i for i, e in enumerate(exercises)
                      if e["name"].strip().lower() == wanted), None)
        if index is None and wanted:
            index = next((i for i, e in enumerate(exercises)
                          if wanted in e["name"].lower() or e["name"].lower() in wanted), None)
        if index is None:
            return "Which exercise of today's session do you want to change?"
        ex = exercises[index]
        done = reports.sets_done(self.store, day, ex["name"])
        action = change.get("action")
        if action == "weight":
            weight = _number(change.get("weight_kg"))
            if weight is None:
                return f"What weight do you want for {ex['name']} today?"
            ex["weight_kg"] = weight
            self._save(session)
            return f"{ex['name']} today: {weight:g} kg."
        if action == "swap":
            return self._swap(session, index, done, change, day)
        if action == "drop":
            if done:
                ex["sets"] = done
            else:
                exercises.pop(index)
            self._save(session)
            return self._after_change(session, day, index, done, 0 if done else -1,
                                      f"Dropped {ex['name']} for today.")
        return "Do you want to swap, drop or change the weight of that exercise?"

    def _swap(self, session: dict, index: int, done: int, change: dict, day: str) -> str:
        ex = session["exercises"][index]
        name = str(change.get("new_exercise") or "").strip()
        gear = str(change.get("equipment") or "").strip()
        allowed = {g.lower() for g in self._equipment(session["gym"])}
        if not name or gear.lower() not in allowed:
            return (f"Which machine or weights at the {session['gym']} gym do you want to use "
                    f"instead of {ex['name']}?")
        weight = _number(change.get("weight_kg"))
        new = {"name": name, "equipment": gear, "sets": max(1, int(ex["sets"]) - done),
               "rep_low": ex["rep_low"], "rep_high": ex["rep_high"],
               "weight_kg": weight if weight is not None else ex["weight_kg"]}
        if done:
            ex["sets"] = done
            session["exercises"].insert(index + 1, new)
        else:
            session["exercises"][index] = new
        self._save(session)
        lead = (f"Swapped {ex['name']} for {name} today: {new['sets']} x "
                f"{new['rep_low']}-{new['rep_high']} at {new['weight_kg']:g} kg.")
        return self._after_change(session, day, index, done, 1 if done else 0, lead)

    def _after_change(self, session: dict, day: str, index: int, done: int, shift: int,
                      lead: str) -> str:
        """After an edit at `index` that added (`shift` 1) or removed (-1) an exercise:
        when it was the exercise shown, show the next open one (the new one after a swap);
        otherwise keep the pointer on the same exercise."""
        raw = self.store.get(FLOW_KEY + day)
        if raw is None or int(raw) >= len(session["exercises"]) - shift:
            return lead  # no session flow open today
        pointer = int(raw)
        if pointer == index:
            return self._move_to(session, day, index + 1 if done else index, lead, show=True)
        if pointer > index:
            self.store.set(FLOW_KEY + day, str(pointer + shift))
        return lead

    def _save(self, session: dict) -> None:
        self.store.add_plan_session(session["date"], session["gym"], session["kind"],
                                    session["status"], session["exercises"])

    def _change_plan(self, day: str, change: str) -> str:
        """Never writes a week by itself (Task 14h). With a proposed week waiting and no
        strength session open today, ask before revising it; otherwise keep the change as a
        note for the next /propose."""
        note = self.store.get(PENDING_CHANGE) or ""
        both = "; ".join(c for c in (note, change) if c)
        week = self._proposal_week()
        today = self.store.plan_session(day)
        session_open = bool(today and today["kind"] == "strength"
                            and today["status"] == "approved")
        if week is not None and not session_open:
            self.store.set(PENDING_REVISE, both)
            return (f"Revise the proposed week {_day_month(week)} to "
                    f"{_day_month(week + timedelta(days=6))} with: {both}? Reply yes.")
        self.store.set(PENDING_CHANGE, both)
        return (f"Noted for next week's plan: {change}. Today's session stays as it is. "
                "Send /propose when you want the new week.")

    def _pending_revise(self, text: str) -> str | None:
        """Answer to "Revise the proposed week ...?": yes revises it; anything else drops the
        question and the message is read as usual."""
        change = self.store.get(PENDING_REVISE)
        if not change:
            return None
        self.store.set(PENDING_REVISE, "")
        if text.lower().strip(" .!") not in YES:
            return None
        reply = self._propose(change)
        self.store.set(PENDING_CHANGE, "")
        return reply

    # one exercise at a time: the scheduler shows the first; a completing reply the next
    def _shown(self, day: str) -> tuple[dict, int] | None:
        """(today's strength session, index of the exercise shown now) while one is open."""
        raw = self.store.get(FLOW_KEY + day)
        session = self.store.plan_session(day)
        if raw is None or not session or session["kind"] != "strength":
            return None
        index = int(raw)
        return (session, index) if index < len(session["exercises"]) else None

    @staticmethod
    def _to_shown(raw_sets, shown):
        """Log reported sets against the exercise now shown, unless the set names another
        exercise of today's session or is his own exercise (marked "own")."""
        if shown is None or not isinstance(raw_sets, list):
            return raw_sets
        names = {e["name"].strip().lower() for e in shown[0]["exercises"]}
        current = shown[0]["exercises"][shown[1]]["name"]
        out = []
        for s in raw_sets:
            if (isinstance(s, dict) and s.get("own") is not True
                    and str(s.get("exercise", "")).strip().lower() not in names):
                s = {**s, "exercise": current}
            out.append(s)
        return out

    def _flow_reply(self, text: str) -> str | None:
        """Handle next / done / skip while a strength session is on; else None."""
        word = text.lower().strip(" .!")
        day = self._today().isoformat()
        shown = self._shown(day) if word in NEXT_WORDS else None
        if shown is None:
            return None
        session, index = shown
        name = session["exercises"][index]["name"]
        passed = self.store.get(PASSED_KEY + day) or ""  # not shown again before the end
        self.store.set(PASSED_KEY + day, f"{passed}|{name.strip().lower()}")
        if word == "skip":
            lead = f"Skipped {name}."
        elif reports.sets_done(self.store, day, name):
            lead = reports.format_exercise(self.store, day, name)
        else:
            lead = f"Nothing logged for {name}."
        return self._advance(session, index, day, lead)

    def _after_report(self, session: dict, index: int, day: str) -> str:
        ex = session["exercises"][index]
        line = reports.format_exercise(self.store, day, ex["name"])
        left = int(ex["sets"]) - reports.sets_done(self.store, day, ex["name"])
        if left > 0:
            return f"{line}. {left} set{'s' if left != 1 else ''} left."
        return self._advance(session, index, day, line)

    def _advance(self, session: dict, index: int, day: str, lead: str) -> str:
        """Move to the next exercise and queue its message, or close the session."""
        return self._move_to(session, day, index + 1, lead, show=True)

    def _next_open(self, session: dict, day: str, start: int) -> int:
        """Index of the first exercise from `start` on, then from the top, with sets still to
        do and not passed over with next/done/skip; len(exercises) when there is none."""
        exercises = session["exercises"]
        passed = set((self.store.get(PASSED_KEY + day) or "").split("|"))
        for i in [*range(start, len(exercises)), *range(min(start, len(exercises)))]:
            ex = exercises[i]
            if (ex["name"].strip().lower() not in passed
                    and reports.sets_done(self.store, day, ex["name"]) < int(ex["sets"])):
                return i
        return len(exercises)

    def _move_to(self, session: dict, day: str, start: int, lead: str, show: bool) -> str:
        """Point at the next open exercise from `start` (going back to earlier ones with sets
        left) and queue its message; with none left, close the session (marked done, missing
        sets listed)."""
        exercises = session["exercises"]
        nxt = self._next_open(session, day, start)
        self.store.set(FLOW_KEY + day, str(nxt))
        if nxt < len(exercises):
            if show:
                self.exercise_to_send = (session, nxt)
            return lead
        reports.mark_done(self.store, day)
        missing = reports.missing(self.store, day, session)
        tail = f"\nMissing: {', '.join(missing)}" if missing else ""
        return (f"{lead}\n\nSession done. " + reports.format_log(self.store, day, "Summary:")
                + tail)

    def pop_exercise(self) -> tuple[dict, int] | None:
        """The (session, index) whose exercise message goes out after the reply (once)."""
        shown, self.exercise_to_send = self.exercise_to_send, None
        return shown

    def _body(self, day: str, weight, waist) -> str:
        """Store this week's weight and waist; a weight far from the last one is questioned."""
        weight = _number(weight)
        waist = _number(waist)
        if weight is None:
            return 'I did not catch your weight. Say e.g. "81.6 kg".'
        last = targets.current_targets(self.store, self._profile()).weight_kg
        if abs(weight - last) > BODY_JUMP_KG:
            self.store.set(PENDING_BODY, f"{weight}|{'' if waist is None else waist}")
            return (f"{weight:g} kg is {abs(weight - last):.1f} kg "
                    f"{'above' if weight > last else 'below'} your last weight ({last:g} kg). "
                    "Is that right? Reply yes to save it, or send the right number.")
        return self._save_body(day, weight, waist)

    def _save_body(self, day: str, weight: float, waist: float | None) -> str:
        self.store.set(PENDING_BODY, "")
        self.store.add_body(day, weight, waist)
        waist_part = "" if waist is None else f", waist {waist:g} cm"
        t = targets.current_targets(self.store, self._profile())
        return (f"Saved: {weight:g} kg{waist_part}. Daily targets now {t.kcal:,} kcal "
                f"and {t.protein_g} g protein.")

    def _pending_body(self, text: str) -> str | None:
        """Answer to the question about a far-off weight: yes saves it, anything else drops it."""
        value = self.store.get(PENDING_BODY)
        if not value:
            return None
        self.store.set(PENDING_BODY, "")
        if text.lower().strip(" .!") not in YES:
            return None  # a new message: classify it normally
        weight, _, waist = value.partition("|")
        return self._save_body(self._today().isoformat(), float(weight),
                               float(waist) if waist else None)

    def _profile(self):
        return self._profile_path or DEFAULT_PROFILE

    def _meal(self, text: str | None, jpeg: bytes | None = None) -> str:
        now = self._now().astimezone(HK)
        meal = meals.log_meal(self.store, self.claude, self.fast, now, text, jpeg)
        if meal.get("meal") is False:
            return (f"That looks like {meal['what']}, not a meal, so I logged nothing. What is "
                    "it? Send it again with a caption, e.g. \"can I use this for rows?\"")
        return meals.reply(self.store, now.date().isoformat(), meal, self._profile())

    def _propose(self, change: str | None = None) -> str:
        """Propose (or revise) the plan for the proposed week, else for next week."""
        week = self._proposal_week() or self._next_monday()
        intro = planner.propose(self.claude, self.store, self.coach, week,
                                change=change, **self._planner_kw)
        sessions = self.store.plan_sessions(week.isoformat(),
                                            (week + timedelta(days=6)).isoformat())
        self.album_session = next((s for s in sessions if s["kind"] == "strength"), None)
        return proposal_message(intro, sessions)

    def pop_album_session(self) -> dict | None:
        """The session whose machine photos go with the last proposal (once)."""
        session, self.album_session = self.album_session, None
        return session

    def _next_monday(self) -> date:
        today = self._today()
        return today + timedelta(days=7 - today.weekday())

    def _proposal_week(self) -> date | None:
        """Monday of the week holding the earliest proposed session from today on."""
        today = self._today()
        rows = self.store.plan_sessions(today.isoformat(),
                                        (today + timedelta(days=21)).isoformat())
        proposed = [r for r in rows if r["status"] == "proposed"]
        if not proposed:
            return None
        first = date.fromisoformat(proposed[0]["date"])
        return first - timedelta(days=first.weekday())

    def _approve(self) -> str:
        week = self._proposal_week()
        if week is None or planner.approve(self.store, week) == 0:
            return "There is no proposed plan waiting for approval."
        return "Approved. I will send each day's session at the usual time."

    def _today_text(self) -> str:
        s = self.store.plan_session(self._today().isoformat())
        if not s:
            return "Nothing planned today."
        if s["kind"] == "cardio":
            return f"Today ({s['status']}): cardio at about 130 bpm."
        lines = [f"Today at the {s['gym']} gym ({s['status']}):"] + [
            f"{e['name']}: {e['sets']} x {e['rep_low']}-{e['rep_high']} at {e['weight_kg']} kg"
            for e in s["exercises"]
        ]
        return "\n".join(lines)

    def _answer(self, text: str, context: str | None = None, jpeg: bytes | None = None) -> str:
        """The coach's answer; with `jpeg`, the photo he sent this text with is attached."""
        profile = profile_text(self._profile_path) if self._profile_path else profile_text()
        context = context or self.context(self._today().isoformat())
        photo = " (with the attached photo)" if jpeg is not None else ""
        prompt = f"Profile:\n{profile}\n\n{context}\n\nNew message from Brian{photo}: {text}"
        system = ("You are a concise gym coach. Answer in at most 5 sentences. General fitness "
                  "guidance, not medical advice.")
        if jpeg is not None:
            return self.claude.text_with_image(self.fast, prompt, jpeg, system=system)
        return self.claude.text(self.fast, prompt, system=system)


def _day_month(d: date) -> str:
    return f"{d.day} {d:%b}"  # "23 Nov"


def _norm(text: str) -> str:
    return " ".join(str(text).lower().split())


def _one_line(text: str, limit: int = 300) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[:limit - 3] + "..."


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value > 0 else None
