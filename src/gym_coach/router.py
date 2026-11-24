"""Turn one incoming message into a reply: slash commands, "start" and the "Finish session"
button are handled here; everything else goes to the coach chat with tools (Task 15c)."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from gym_coach import meals, planner, reports, targets
from gym_coach.albums import shrink
from gym_coach.coach import FLOW_KEY, Coach, ToolRefused
from gym_coach.context import DEFAULT_EQUIPMENT, DEFAULT_PROFILE, equipment_for
from gym_coach.llm import HK, CeilingReached, LLMError
from gym_coach.messages import proposal_message, stretch_message, warm_up_message, weight_text

PENDING_CHANGE = "pending:plan_change"  # a future-week change kept for the next /propose
CHAT_LINES = 12  # today's chat lines each model call sees outside a workout (Task 14g)
START_WORDS = {"start", "start workout", "start session"}  # open a workout (Task 14i)
FINISH_BUTTON = "finish session"  # the button shown after the last exercise (Task 14j)
FINISH_KEYBOARD = {"keyboard": [[{"text": "Finish session"}]], "resize_keyboard": True}
REMOVE_KEYBOARD = {"remove_keyboard": True}
WARMUP_KEY = "warmup:"  # + day: "1" while the warm-up is sent and not yet done (Task 14j)
PASSED_KEY = "passed:"  # + day: exercises he moved on from with "next", "|"-joined
PHOTO_EDGE = 1024  # px; his photos are shrunk to this before an image call (Task 14h)
TYPO_HIGH, TYPO_LOW = 1.5, 0.5  # a weight outside these times the plan or last set: "far"

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
        self.keyboard: dict | None = None  # reply_markup for the reply (Task 14j)
        # structured texts the code sends after the model's reply, exactly as written:
        # (what it is, for the tool result; the text)
        self.tail: list[tuple[str, str]] = []
        # for the app's trace of the last message: the coach call's tool calls as JSON, or
        # "local" when no model call read it; and the error that became a "Sorry" reply
        self.understood: str | None = None
        self.error: str | None = None
        # keyword arguments for planner.propose (it falls back to data\ when they are None)
        self._planner_kw = {k: v for k, v in
                            (("profile_path", profile_path), ("equipment_path", equipment_path),
                             ("illustrations", illustrations))
                            if v}

    def handle(self, text: str) -> str:
        """Reply text for one message from the allowed user."""
        self._reset()
        return self._guarded(self._handle, text.strip())

    def handle_photo(self, jpeg: bytes, caption: str | None = None) -> str:
        """Reply to a photo. In an open workout, or with a caption, the coach call gets the
        image and decides; outside a workout a photo without a caption is a meal estimate."""
        self._reset()
        try:
            jpeg = shrink(jpeg, PHOTO_EDGE)
        except (OSError, ValueError):
            pass  # not an image Pillow can read: sent as it came
        day = self._today().isoformat()
        if caption and caption.strip():
            return self._guarded(self._coach, day, caption.strip(), jpeg, True)
        if self._workout_since(day) is not None:
            # Brian: a photo in the gym session "is never a meal picture, always a query"
            return self._guarded(self._coach, day, "(a photo without a caption, sent during "
                                 "the workout)", jpeg, False)
        self.understood = "photo without caption: meal estimate"
        return self._guarded(self._meal, None, jpeg)

    def _reset(self) -> None:
        """Nothing from an earlier message (a card it queued, say) goes out with this one."""
        self.understood, self.error, self.keyboard, self.tail = "local", None, None, []
        self.exercise_to_send = None

    def _guarded(self, fn, *args) -> str:
        try:
            return fn(*args)
        except CeilingReached:
            self.error = "monthly ceiling reached"
            return self._ceiling_text()
        except (LLMError, planner.PlanError) as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            return f"Sorry, I could not do that ({exc}). Please try again."
        except Exception as exc:  # noqa: BLE001 - an SDK or network failure of a model call
            self.error = f"{type(exc).__name__}: {exc}"[:300]
            return "Sorry, I could not reach the coach just now. Please try again."

    def _ceiling_text(self) -> str:
        return (f"This month's US${self.claude.ceiling_usd:g} limit on AI calls is reached. "
                "I can't read new messages until next month; /today and /cost still work.")

    def _today(self) -> date:
        return self._now().astimezone(HK).date()

    def _handle(self, text: str) -> str:
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
        day = self._today().isoformat()
        word = text.lower().strip(" .!")
        if word in START_WORDS:
            return self._start(day)
        if word == FINISH_BUTTON:
            return self._end(day)
        return self._coach(day, text)

    def _coach(self, day: str, text: str, jpeg: bytes | None = None,
               caption: bool = False) -> str:
        """The coach call: the model reads the message with the chat and the session, calls
        tools, and writes the reply; the structured texts the tools queued follow it."""
        coach = Coach(self, day, jpeg, caption)
        try:
            reply = coach.reply(text).strip()
        except Exception as exc:
            if not coach.done:
                raise  # nothing changed: _guarded says sorry, and sending it again is safe
            # a tool already changed the records: say what changed, never "try again"
            # (sending the message again would log it twice)
            if isinstance(exc, CeilingReached):
                self.error, why = "monthly ceiling reached", self._ceiling_text()
            else:
                self.error = f"{type(exc).__name__}: {exc}"[:300]
                why = "My full reply did not come through."
            reply = (f"{why} This is saved, no need to send it again:\n"
                     + "\n".join(dict.fromkeys(coach.done)))
        finally:
            self.understood = json.dumps(coach.calls, ensure_ascii=False)
        reply = reply or coach.last_result or "Sorry, I have no answer to that."
        tail, self.tail = self.tail, []
        return "\n\n".join([reply, *(t for _, t in tail)])

    # what the tools do (coach.py checks the hard rules first)
    def _log(self, day: str, sets: list[dict]) -> str:
        """Save checked sets; the pointer follows him and a completed exercise shows the next
        one. Returns each exercise's log line, the sets left and any weight far off."""
        shown = self._shown(day)
        before = self.store.logged_sets(day)
        logged = reports.log_report(self.store, day, sets)
        if not logged:
            raise ToolRefused("No usable sets.")
        far = self._typo(day, logged, before)
        added = self._add_own(day, sets, logged)
        warm_up = self._warm_up_over(day)  # a first set ends the warm-up
        session = self.store.plan_session(day)
        new: dict[str, int] = {}
        for s in logged:
            new[s["exercise"]] = new.get(s["exercise"], 0) + 1
        lines = []
        for name, count in new.items():
            done = reports.sets_done(self.store, day, name)
            numbers = ", ".join(str(n) for n in range(done - count + 1, done + 1))
            line = (f"{reports.format_exercise(self.store, day, name)} "
                    f"(saved now: set{'s' if count > 1 else ''} {numbers})")
            if name.strip().lower() in added:
                line += " (his own exercise, added to today)"
            ex = next((e for e in (session or {}).get("exercises", [])
                       if e["name"].strip().lower() == name.strip().lower()), None)
            if ex is not None and not ex.get("own"):
                left = max(0, int(ex["sets"]) - done)
                line += f". {left} set{'s' if left != 1 else ''} left"
            lines.append(line + ".")
        if shown is not None:
            exercises = session["exercises"]
            index = shown[1]
            names = [e["name"].strip().lower() for e in exercises]
            later = [names.index(s["exercise"].lower()) for s in logged
                     if s["exercise"].lower() in names]
            later = [i for i in later if i > index and not exercises[i].get("own")]
            if later:  # he moved on: the pointer follows him
                index = max(later)
                self.store.set(FLOW_KEY + day, str(index))
            if self._next_open(session, day, index) != index:
                self._move_to(session, day, index, "", show=True)
            elif warm_up:
                self.exercise_to_send = (session, index)  # its card, never sent yet
            now = self._shown(day)
            if now is not None and self.exercise_to_send is None:
                lines.append(f"Shown now: {now[0]['exercises'][now[1]]['name']}.")
        return "\n".join(lines) + far

    def _show(self, day: str, session: dict, index: int | None) -> str:
        """Show the exercise at `index`, or with None the next open one (moving on from the
        one shown); a pending warm-up ends and its first exercise follows."""
        if self.store.get(FLOW_KEY + day) is None:
            self.store.set(FLOW_KEY + day, "0")
        warm_up = self._warm_up_over(day)
        if index is not None:
            name = session["exercises"][index]["name"]
            passed = (self.store.get(PASSED_KEY + day) or "").split("|")
            self.store.set(PASSED_KEY + day,
                           "|".join(p for p in passed if p != name.strip().lower()))
            self.store.set(FLOW_KEY + day, str(index))
            self.exercise_to_send = (session, index)
            return ("Warm-up over. " if warm_up else "") + f"Now: {name}."
        shown = self._shown(day)
        if shown is None:
            return "Every exercise of today's session is done or passed."
        index = shown[1]
        name = session["exercises"][index]["name"]
        if warm_up:
            self.exercise_to_send = shown
            return f"Warm-up over. First exercise: {name}."
        passed = self.store.get(PASSED_KEY + day) or ""  # not shown again before the end
        self.store.set(PASSED_KEY + day, f"{passed}|{name.strip().lower()}")
        if reports.sets_done(self.store, day, name):
            lead = f"Moved on from {reports.format_exercise(self.store, day, name)}."
        else:
            lead = f"Moved on from {name} (nothing logged for it)."
        self._move_to(session, day, index + 1, lead, show=True)
        return lead

    def _swap(self, session: dict, index: int, done: int, name: str, gear: str,
              weight: float | None, day: str) -> str:
        ex = session["exercises"][index]
        new = {"name": name, "equipment": gear, "sets": max(1, int(ex["sets"]) - done),
               "rep_low": ex["rep_low"], "rep_high": ex["rep_high"],
               "weight_kg": weight if weight is not None else ex["weight_kg"]}
        # the text is built before the save, so the tool never fails after the write (a
        # failure goes back to the model, which would swap again; Task 15f)
        lead = (f"Swapped {ex['name']} for {name} on {gear} today: {new['sets']} x "
                f"{new['rep_low']}-{new['rep_high']} at {weight_text(new['weight_kg'])}.")
        if done:
            ex["sets"] = done
            session["exercises"].insert(index + 1, new)
        else:
            session["exercises"][index] = new
        self._save(session)
        return self._after_change(session, day, index, done, 1 if done else 0, lead)

    def _drop(self, session: dict, index: int, day: str) -> str:
        ex = session["exercises"][index]
        done = reports.sets_done(self.store, day, ex["name"])
        if done:
            ex["sets"] = done
        else:
            session["exercises"].pop(index)
        self._save(session)
        return self._after_change(session, day, index, done, 0 if done else -1,
                                  f"Dropped {ex['name']} for today.")

    def _note_change(self, change: str) -> str:
        """Keep a future-week change as a note (never writes a week by itself, Task 14h)."""
        note = self.store.get(PENDING_CHANGE) or ""
        if change.lower() not in note.lower():
            note = "; ".join(c for c in (note, change) if c)
        self.store.set(PENDING_CHANGE, note)
        week = self._proposal_week()
        if self._week_finished():
            what = (f"the proposed week {_day_month(week)} to "
                    f"{_day_month(week + timedelta(days=6))}" if week else "next week's plan")
            return (f"Kept as a note: {note}. This week's sessions are over, so ask him whether "
                    f"to write {what} with it now (revise_proposed_week).")
        return (f"Kept as a note for next week's plan: {note}. Today's session stays. The bot "
                "asks about it once this week's last session is done; /propose works any time.")

    def _revise(self, change: str) -> str:
        """Write the proposed (or next) week with the kept note and this change."""
        note = self.store.get(PENDING_CHANGE) or ""
        both = note if change.lower() in note.lower() else "; ".join(
            c for c in (note, change) if c)
        reply = self._propose(both or None)
        self.store.set(PENDING_CHANGE, "")
        return reply

    def _add_own(self, day: str, raw_sets, logged: list[dict]) -> set[str]:
        """Add his own exercises (sets the model marked "own") to today's strength
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
        """A note when a weight is over 1.5 times or under half the last set of that
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
                               f"{'his last set' if last else 'the plan'} ({ref:g} kg)")
        if not flagged:
            return ""
        return ("\nSaved, but " + "; ".join(dict.fromkeys(flagged))
                + ": ask him if it is a typo.")

    def _fix_set(self, day: str, fix) -> str | None:
        """Change one saved set's weight and reps; a line saying how, or None."""
        if not isinstance(fix, dict):
            return None
        key = str(fix.get("exercise", "")).strip().lower()
        try:
            set_no = int(fix.get("set_no"))
            row = next(r for r in self.store.logged_sets(day)
                       if r["exercise"].strip().lower() == key and r["set_no"] == set_no)
            reps = int(fix["reps"]) if fix.get("reps") is not None else row["reps"]
            weight = (row["weight_kg"] if "weight_kg" not in fix or fix["weight_kg"] is None
                      else float(fix["weight_kg"]))
        except (StopIteration, TypeError, ValueError):
            return None
        if (weight, reps) == (row["weight_kg"], row["reps"]):
            return None
        self.store.update_logged_set(row["id"], weight, reps)
        new = {"weight_kg": weight, "reps": reps}
        return (f"Fixed: {row['exercise']} set {set_no} from {reports.sets_text([row])} "
                f"to {reports.sets_text([new])}")

    # a workout: opens on "start" or by itself, closes when nothing is left, on "end" or
    # at the 21:00 close (Task 14i); while open, model calls see its whole chat
    def _workout_since(self, day: str) -> int | None:
        """The last chat row before the open workout, or None when none is open."""
        value = self.store.get(reports.WORKOUT_KEY + day) or ""
        return int(value.split("|")[1]) if value.startswith("open|") else None

    def _open(self, day: str, auto: bool = True) -> None:
        """Open today's workout; by itself (`auto`) never again once it closed today."""
        value = self.store.get(reports.WORKOUT_KEY + day) or ""
        if value.startswith("open|") or (auto and value):
            return
        opened = self._now().astimezone(HK).isoformat(timespec="seconds")
        self.store.set(reports.WORKOUT_KEY + day, f"open|{self.store.last_chat_id()}|{opened}")

    def _start(self, day: str) -> str:
        self._open(day, auto=False)
        session = self.store.plan_session(day)
        if not session or session["kind"] != "strength" or not session["exercises"]:
            return "Workout started. Tell me what you do and I log it."
        if self.store.get(FLOW_KEY + day) is None:  # the morning message never went out
            self.store.set(FLOW_KEY + day, "0")
            self.store.set(WARMUP_KEY + day, "1")
        if self.store.get(WARMUP_KEY + day) == "1":
            return "Workout started.\n\n" + warm_up_message()
        shown = self._shown(day)
        if shown is None:
            return "Workout started. Every exercise of today's session is done."
        return f"Workout started. Now: {session['exercises'][shown[1]]['name']}."

    def _warm_up_over(self, day: str) -> bool:
        """End a pending warm-up; True when one was pending."""
        if self.store.get(WARMUP_KEY + day) != "1":
            return False
        self.store.set(WARMUP_KEY + day, "")
        return True

    def _end(self, day: str) -> str:
        """The "Finish session" button or finish_workout: close, remove the button."""
        session = self.store.plan_session(day)
        if session and session["kind"] == "strength":
            self.store.set(FLOW_KEY + day, str(len(session["exercises"])))  # no more exercises
        self._warm_up_over(day)
        self.keyboard = REMOVE_KEYBOARD
        return self._close(day, session, "Workout finished.")

    def pop_keyboard(self) -> dict | None:
        """The reply keyboard to send with the reply (once)."""
        keyboard, self.keyboard = self.keyboard, None
        return keyboard

    def _close(self, day: str, session: dict | None, lead: str) -> str:
        """Mark the day done (when sets are logged), close the workout, and send the summary,
        the missing sets and, once the week is over, the question about a kept week change."""
        reports.mark_done(self.store, day)
        reports.close_workout(self.store, day)
        text = f"{lead} " + reports.format_log(self.store, day, "Summary:")
        missing = (reports.missing(self.store, day, session)
                   if session and session["kind"] == "strength" else [])
        if missing:
            text += f"\nMissing: {', '.join(missing)}"
        return text + self._week_question()

    def current_exercise(self) -> str | None:
        """The exercise shown now as "index: name", for the trace; None when none is."""
        shown = self._shown(self._today().isoformat())
        if shown is None:
            return None
        return f"{shown[1]}: {shown[0]['exercises'][shown[1]]['name']}"

    # what each model call sees besides the message
    def context(self, day: str) -> str:
        """The chat (every line of the open workout, else today's last lines; bot lines
        marked delivered or not) and today's session with the sets logged per exercise and
        the exercise shown now."""
        since = self._workout_since(day)
        if since is None:
            rows, header = self.store.chat_lines(day, CHAT_LINES), "Today's chat so far"
        else:
            rows, header = self.store.chat_after(since), "The workout's chat since it opened"
        chat = []
        for r in rows:
            who = "Brian" if r["direction"] == "in" else (
                "Bot" if r["delivered"] else "Bot (NOT delivered)")
            chat.append(f"{r['timestamp'][11:16]} {who}: {_one_line(r['text'])}")
        parts = [f"{header}:\n" + ("\n".join(chat) if chat else "(none)")]
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
        if self.store.get(WARMUP_KEY + day) == "1":
            lines.append("- Warm-up: sent, not done yet (the first exercise follows it)")
        names = set()
        past = self.store.recent_sets(day, days=1)  # what he did last time (Task 14k)
        for i, ex in enumerate(session["exercises"]):
            name = ex["name"]
            names.add(name.strip().lower())
            done = reports.sets_done(self.store, day, name)
            if done:
                sets = "; ".join(f"{name} set {r['set_no']}: {reports.sets_text([r])}"
                                 for r in self.store.logged_sets(day)
                                 if r["exercise"].strip().lower() == name.strip().lower())
                line = f"- {name}: {done} of {ex['sets']} sets logged ({sets})"
            else:
                line = (f"- {name}: 0 of {ex['sets']} sets logged"
                        f" (plan {ex['rep_low']}-{ex['rep_high']} reps at {ex['weight_kg']} kg)")
            last = past.get(name.strip().lower())
            if last:
                line += f" | last: {reports.day_text(last[0])}"
            if shown is not None and shown[1] == i:
                line += " <- shown now"
            lines.append(line)
        others = [ln for ln in logged if ln.split(":")[0].strip().lower() not in names]
        if others:
            lines.append("Also logged: " + "; ".join(others))
        gear = self._equipment(session["gym"])
        if gear:  # for a swap; one per line so names cannot blend (Task 15c)
            lines.append(f"Equipment at the {session['gym']} gym (use these names exactly):\n"
                         + "\n".join(f"- {g}" for g in gear))
        return "\n".join(lines)

    def _equipment(self, gym: str) -> list[str]:
        try:
            return sorted(equipment_for(gym, self._equipment_path))
        except (OSError, ValueError):
            return []

    # changes to today's session (never a new week)
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

    def _week_finished(self) -> bool:
        """True when this week's last planned session is done or skipped, or its day has
        passed (Brian: ask to plan "AFTER the current week is completed"). A week still only
        proposed counts as over, so its proposal can be revised."""
        today = self._today()
        monday = today - timedelta(days=today.weekday())
        if self._proposal_week() == monday:
            return True
        rows = [r for r in self.store.plan_sessions(monday.isoformat(),
                                                    (monday + timedelta(days=6)).isoformat())
                if r["status"] != "proposed"]
        if not rows:
            return True
        last = rows[-1]
        return last["status"] in ("done", "skipped") or last["date"] < today.isoformat()

    def _week_question(self) -> str:
        """At a session's close: once the week is over, ask about the kept week change."""
        note = self.store.get(PENDING_CHANGE) or ""
        if not note or not self._week_finished():
            return ""
        week = self._proposal_week()
        if week is not None:
            return (f"\n\nRevise the proposed week {_day_month(week)} to "
                    f"{_day_month(week + timedelta(days=6))} with: {note}? Reply yes.")
        week = self._next_monday()
        return (f"\n\nPlan next week ({_day_month(week)} to "
                f"{_day_month(week + timedelta(days=6))}) with: {note}? Reply yes.")

    # one exercise at a time: the scheduler shows the first; a completing reply the next
    def _shown(self, day: str) -> tuple[dict, int] | None:
        """(today's strength session, index of the exercise shown now) while one is open."""
        raw = self.store.get(FLOW_KEY + day)
        session = self.store.plan_session(day)
        if raw is None or not session or session["kind"] != "strength":
            return None
        index = int(raw)
        return (session, index) if index < len(session["exercises"]) else None

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
        # every exercise done: stretching and the "Finish session" button (Task 14j); the
        # workout stays open until he taps it, says "end", or the 21:00 close
        reports.mark_done(self.store, day)
        missing = reports.missing(self.store, day, session)
        tail = f"\nMissing: {', '.join(missing)}" if missing else ""
        self.keyboard = FINISH_KEYBOARD
        label = "the stretch list and the Finish session button (every exercise is done)"
        self.tail.append((label, f"Session done.{tail}\n\n" + stretch_message(session)))
        return lead

    def pop_exercise(self) -> tuple[dict, int] | None:
        """The (session, index) whose exercise message goes out after the reply (once)."""
        shown, self.exercise_to_send = self.exercise_to_send, None
        return shown

    def _save_body(self, day: str, weight: float, waist: float | None) -> str:
        self.store.add_body(day, weight, waist)
        waist_part = "" if waist is None else f", waist {waist:g} cm"
        t = targets.current_targets(self.store, self._profile())
        return (f"Saved: {weight:g} kg{waist_part}. Daily targets now {t.kcal:,} kcal "
                f"and {t.protein_g} g protein.")

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


def _day_month(d: date) -> str:
    return f"{d.day} {d:%b}"  # "23 Nov"


def _one_line(text: str, limit: int = 300) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[:limit - 3] + "..."


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if value > 0 else None
