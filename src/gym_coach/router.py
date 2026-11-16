"""Turn one incoming text into a reply: commands skip the model, the rest are classified."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from gym_coach import meals, planner, reports, targets
from gym_coach.context import DEFAULT_PROFILE, profile_text
from gym_coach.llm import HK, CeilingReached, LLMError
from gym_coach.messages import proposal_message

CLASSIFY_SYSTEM = """You read one message from a gym-goer to his coach bot and classify it.
Intents: report (he reports sets he did), correction (he fixes a set he already reported),
approve (he accepts the proposed plan), change_plan (he asks to change the proposed plan),
skip (he skips today's session), body (body weight; a waist he mentions is still stored), progress (asks for his numbers),
meal (he says what he ate), meal_correction (he fixes the calories or protein of the last meal),
question (anything else).
Answer JSON: {"intent": "<one intent>", "sets": [{"exercise": "...", "weight_kg": 35,
"reps": 10, "effort": null}], "change": "<the requested change, for change_plan>",
"kcal": <number, for meal_correction>, "protein_g": <number or null, for meal_correction>,
"weight_kg": <number or null, for body>, "waist_cm": <number or null, for body>}
"sets" has one entry per set: expand "3x10 at 40 kg" into three entries and "35kg 10 10 8" into
three entries. For a correction list every set of each exercise he corrects, with the corrected
values. Use an empty list when there are no sets."""

BODY_JUMP_KG = 5.0
PENDING_BODY = "pending:body"
FLOW_KEY = "flow:"  # + day: index of the exercise shown now (kv); absent = not started
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
        self.album_session: dict | None = None  # first session of the last proposal
        self.exercise_to_send: tuple[dict, int] | None = None  # (session, index) to show next
        # keyword arguments for planner.propose (it falls back to data\ when they are None)
        self._planner_kw = {k: v for k, v in
                            (("profile_path", profile_path), ("equipment_path", equipment_path),
                             ("illustrations", illustrations))
                            if v}

    def handle(self, text: str) -> str:
        """Reply text for one message from the allowed user."""
        return self._guarded(self._handle, text.strip())

    def handle_photo(self, jpeg: bytes, caption: str | None = None) -> str:
        """Reply to a meal photo (the caption, e.g. "half portion", goes to the model)."""
        return self._guarded(self._meal, caption, jpeg)

    def _guarded(self, fn, *args) -> str:
        try:
            return fn(*args)
        except CeilingReached:
            return (f"This month's US${self.claude.ceiling_usd:g} limit on AI calls is reached. "
                    "I can't read new messages until next month; /today and /cost still work.")
        except (LLMError, planner.PlanError) as exc:
            return f"Sorry, I could not do that ({exc}). Please try again."

    def _today(self) -> date:
        return self._now().astimezone(HK).date()

    def _handle(self, text: str) -> str:
        command = text.split()[0].lower() if text.startswith("/") else None
        if command == "/start":
            return HELP
        if command == "/today":
            return self._today_text()
        if command == "/propose":
            return self._propose()
        if command == "/progress":
            return "Progress numbers are coming soon."
        if command == "/cost":
            return (f"This month: US${self.claude.month_cost():.2f} "
                    f"of US${self.claude.ceiling_usd:g}.")
        pending = self._pending_body(text)
        if pending is not None:
            return pending
        flow = self._flow_reply(text)
        if flow is not None:
            return flow
        data = self.claude.json(self.fast, text, system=CLASSIFY_SYSTEM)
        if not isinstance(data, dict):
            data = {}
        intent = data.get("intent")
        day = self._today().isoformat()
        if intent == "report":
            shown = self._shown(day)
            raw = self._to_shown(data.get("sets"), shown)
            if not reports.log_report(self.store, day, raw):
                return "I could not find any sets in that. Try \"chest press 35 kg 10 10 8\"."
            if shown is not None:
                return self._after_report(shown[0], shown[1], day)
            return reports.format_log(self.store, day)
        if intent == "correction":
            if not reports.correct(self.store, day, data.get("sets")):
                return "I could not tell what to correct. Say e.g. \"chest press was 30 kg\"."
            return reports.format_log(self.store, day, "Corrected:")
        if intent == "approve":
            return self._approve()
        if intent == "change_plan":
            return self._propose(data.get("change") or text)
        if intent == "skip":
            if not self.store.plan_session(day):
                return "There is no session planned today."
            self.store.set_plan_status(day, "skipped")
            return "Skipped today's session."
        if intent == "meal":
            return self._meal(text)
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
        return self._answer(text)

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
        exercise of today's session."""
        if shown is None or not isinstance(raw_sets, list):
            return raw_sets
        names = {e["name"].strip().lower() for e in shown[0]["exercises"]}
        current = shown[0]["exercises"][shown[1]]["name"]
        out = []
        for s in raw_sets:
            if isinstance(s, dict) and str(s.get("exercise", "")).strip().lower() not in names:
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
        nxt = index + 1
        self.store.set(FLOW_KEY + day, str(nxt))
        if nxt < len(session["exercises"]):
            self.exercise_to_send = (session, nxt)
            return lead
        return f"{lead}\n\nSession done. " + reports.format_log(self.store, day, "Summary:")

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

    def _answer(self, text: str) -> str:
        profile = profile_text(self._profile_path) if self._profile_path else profile_text()
        prompt = f"Profile:\n{profile}\n\nToday's session:\n{self._today_text()}\n\nQuestion: {text}"
        return self.claude.text(
            self.fast, prompt,
            system="You are a concise gym coach. Answer in at most 5 sentences. General fitness "
                   "guidance, not medical advice.")


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value > 0 else None
