"""Turn one incoming text into a reply: commands skip the model, the rest are classified."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from gym_coach import planner, reports
from gym_coach.context import profile_text
from gym_coach.llm import HK, CeilingReached, LLMError
from gym_coach.messages import proposal_message

CLASSIFY_SYSTEM = """You read one message from a gym-goer to his coach bot and classify it.
Intents: report (he reports sets he did), correction (he fixes a set he already reported),
approve (he accepts the proposed plan), change_plan (he asks to change the proposed plan),
skip (he skips today's session), body (body weight or waist), progress (asks for his numbers),
question (anything else).
Answer JSON: {"intent": "<one intent>", "sets": [{"exercise": "...", "weight_kg": 35,
"reps": 10, "effort": null}], "change": "<the requested change, for change_plan>"}
"sets" has one entry per set: expand "3x10 at 40 kg" into three entries and "35kg 10 10 8" into
three entries. For a correction list every set of each exercise he corrects, with the corrected
values. Use an empty list when there are no sets."""

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
        # keyword arguments for planner.propose (it falls back to data\ when they are None)
        self._planner_kw = {k: v for k, v in
                            (("profile_path", profile_path), ("equipment_path", equipment_path),
                             ("illustrations", illustrations))
                            if v}

    def handle(self, text: str) -> str:
        """Reply text for one message from the allowed user."""
        try:
            return self._handle(text.strip())
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
        data = self.claude.json(self.fast, text, system=CLASSIFY_SYSTEM)
        if not isinstance(data, dict):
            data = {}
        intent = data.get("intent")
        day = self._today().isoformat()
        if intent == "report":
            if not reports.log_report(self.store, day, data.get("sets")):
                return "I could not find any sets in that. Try \"chest press 35 kg 10 10 8\"."
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
        if intent in ("body", "progress"):
            return "That is coming soon."
        return self._answer(text)

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
