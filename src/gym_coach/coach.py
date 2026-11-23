"""The coach chat (Task 15c): one fast-model conversation per message leads the chat with
tools. The tools change the records through the router's helpers and enforce the hard rules
(equipment on that day's gym list, positive numbers, exercise names in today's session); a
refused call raises `ToolRefused`, whose message gives the reason and the valid choices, and
goes back to the model so it can fix its own call."""

from __future__ import annotations

from gym_coach import meals, reports, targets
from gym_coach.context import DEFAULT_PROFILE, profile_text
from gym_coach.llm import HK

FLOW_KEY = "flow:"  # + day: index of the exercise shown now (kv); absent = not started

SYSTEM = """You are Brian's personal gym coach, chatting with him on Telegram. Talk like a good
personal trainer standing next to him: warm, direct, brief.
- During sets reply in 1-3 short sentences that react to what he just did and say what comes
  next. Answer a form question with one or two cues.
- Change records only through the tools, and always state the numbers you logged or changed.
- Identical numbers after a bot reply that was delivered are a NEW set: log them again. A bot
  line marked NOT delivered means he never saw it; numbers he repeats after such a line may be
  the same set, so check the sets already logged before logging again.
- A set he reports belongs to the exercise shown now unless he names another one of today's
  session. A set of an exercise not in today's session is his own exercise: log it with
  "own": true. Use today's exercise names and the gym's equipment names exactly as listed.
- A short correction ("x12, typo", "that was 37.5") fixes the last set he reported: use fix_set.
- Cardio he did (jog, run, bike...): save it with log_cardio, with the minutes and any
  distance or heart rate he gives. If he gave no time, ask once how many minutes; when he
  says he is done with cardio, log it before you call finish_workout.
- "next", "done" or "skip" during the session means show_exercise with "next"; after the
  warm-up it ends the warm-up and the first exercise follows.
- When a tool refuses, read why and fix your call with one of the valid choices it lists.
- Never ask the same question twice: when his answer is still unclear, make the sensible
  choice, say what you did, and let him correct it.
- Say plainly when a photo is unclear.
- Speak as his coach. Never mention tools, the code, "the system", queues or set numbering
  mix-ups; if something went wrong, just say what is logged now.
- When he names a set ("3rd set ...") that is already saved with those numbers, it is the same
  set: don't log it again, just confirm it.
- Vary your wording like a person does: don't open every reply with "Logged". He ramps the
  weight up across sets; that is normal, so never question a number unless a tool result says
  it is far off, and then ask once, briefly.
- The code sends the exercise cards, the stretch list, the Finish session button and the
  summary itself; tool results say what was queued. Never repeat those, just refer to them.
- You give general fitness guidance, not medical advice. English only, weights in kg."""

BODY_JUMP_KG = 5.0  # kg from his last weight: log_body asks first

_EX = {"type": "string", "description": "Exercise name exactly as in today's session"}
_KG = {"type": "number", "description": "kg, more than 0"}


def _tool(name: str, description: str, props: dict | None = None,
          required: list[str] | None = None) -> dict:
    return {"name": name, "description": description,
            "input_schema": {"type": "object", "properties": props or {},
                             "required": required or []}}


TOOLS = [
    _tool("log_sets", "Save sets he did today, one entry per set (3x10 is three entries).",
          {"sets": {"type": "array", "items": {"type": "object", "properties": {
              "exercise": _EX, "weight_kg": {"type": "number",
                                             "description": "kg; leave out for bodyweight"},
              "reps": {"type": "integer"},
              "effort": {"type": "string", "description": "how hard it felt, if he says"},
              "own": {"type": "boolean",
                      "description": "true for his own exercise, not in today's session"}},
              "required": ["exercise", "reps"]}}}, ["sets"]),
    _tool("fix_set", "Change the weight and/or reps of one set already saved today.",
          {"exercise": _EX, "set_no": {"type": "integer"}, "weight_kg": _KG,
           "reps": {"type": "integer"}}, ["exercise", "set_no"]),
    _tool("remove_set", "Delete one set saved today by mistake.",
          {"exercise": _EX, "set_no": {"type": "integer"}}, ["exercise", "set_no"]),
    _tool("show_exercise", "Show an exercise of today's session now (its card is sent after "
          "your reply). \"next\" means the next open one; this also ends the warm-up.",
          {"exercise": {"type": "string", "description": "a name from today's session, or "
                        "\"next\""}}, ["exercise"]),
    _tool("swap_exercise", "Replace an exercise of TODAY's session (his logged sets stay).",
          {"exercise": _EX, "new_exercise": {"type": "string"},
           "equipment": {"type": "string",
                         "description": "exactly a name from that day's gym equipment list"},
           "weight_kg": _KG}, ["exercise", "new_exercise", "equipment"]),
    _tool("drop_exercise", "Drop an exercise from TODAY's session.", {"exercise": _EX},
          ["exercise"]),
    _tool("set_weight", "Change the planned weight of an exercise for TODAY.",
          {"exercise": _EX, "weight_kg": _KG}, ["exercise", "weight_kg"]),
    _tool("log_cardio", "Save cardio he did today (jog, run, bike, rower...); this marks "
          "today's session done.",
          {"activity": {"type": "string", "description": "e.g. jogging, cycling"},
           "minutes": {"type": "number", "description": "how long, more than 0"},
           "distance_km": {"type": "number", "description": "km, if he says"},
           "avg_hr": {"type": "integer", "description": "average heart rate, if he says"}},
          ["activity", "minutes"]),
    _tool("finish_workout", "Close today's workout; the code sends the summary."),
    _tool("skip_today", "He skips today's whole session."),
    _tool("log_meal", "Estimate and save a meal he ate.",
          {"description": {"type": "string"},
           "use_photo": {"type": "boolean",
                         "description": "true when the attached photo shows the food"}},
          ["description", "use_photo"]),
    _tool("correct_meal", "Fix the calories and/or protein of today's last meal.",
          {"kcal": {"type": "number"}, "protein_g": {"type": "number"}}),
    _tool("log_body", "Save his body weight (and waist if he gives it).",
          {"weight_kg": _KG, "waist_cm": {"type": "number"},
           "confirmed": {"type": "boolean",
                         "description": "true once he confirmed a weight far from the last"}},
          ["weight_kg", "confirmed"]),
    _tool("note_plan_change", "Keep a change he wants for a FUTURE week's plan as a note.",
          {"change": {"type": "string"}}, ["change"]),
    _tool("revise_proposed_week", "Write the next week's plan now with this change (only "
          "once this week's sessions are over; he said yes to it).",
          {"change": {"type": "string"}}, ["change"]),
    _tool("approve_plan", "He approves the proposed week."),
]


class ToolRefused(Exception):
    """A tool call broke a hard rule; the message gives the reason and the valid choices."""


def key(name) -> str:
    """A name compared ignoring case and spaces only."""
    return "".join(str(name or "").lower().split())


def _positive(value, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise ToolRefused(f"{field} must be a number more than 0, not {value!r}.")
    return float(value)


def _positive_int(value, field: str) -> int:
    number = _positive(value, field)
    if number != int(number):
        raise ToolRefused(f"{field} must be a whole number more than 0, not {value!r}.")
    return int(number)


def _changed(result: str) -> bool:
    """False for a tool result that says nothing was saved or changed."""
    low = result.lower()
    return not (low.startswith(("not saved", "no change")) or "nothing changed" in low
                or "; nothing logged" in low)


def _optional(data: dict, field: str) -> float | None:
    return None if data.get(field) is None else _positive(data[field], field)


class Coach:
    """One message's conversation: builds the prompt, runs the tools, keeps their trace."""

    def __init__(self, router, day: str, jpeg: bytes | None = None, caption: bool = False):
        self.r = router
        self.day = day
        self.jpeg = jpeg
        self.caption = caption
        self.calls: list[dict] = []  # {tool, input, result[:200]} for the trace
        self.last_result = ""  # the last tool result without its queue notes
        # results of the tools that changed something: the reply when the model call fails
        # after them (Task 15f)
        self.done: list[str] = []
        # the flow pointer and the queued texts at the start, so show_exercise "next" can tell
        # whether an earlier tool in this message already moved on (Task 15f: not the queued
        # card, which a first set that ends the warm-up queues without moving on)
        self._flow_at_start = router.store.get(FLOW_KEY + day)
        self._tail_at_start = len(router.tail)
        self._shown_here = False  # a show_exercise in this message already showed one

    def reply(self, text: str) -> str:
        r = self.r
        return r.claude.converse(r.fast, SYSTEM, [{"role": "user", "content": self.prompt(text)}],
                                 TOOLS, self.run_tool, jpeg=self.jpeg)

    def prompt(self, text: str) -> str:
        r = self.r
        try:
            profile = profile_text(r._profile_path or DEFAULT_PROFILE)
        except OSError:
            profile = "(no profile)"
        now = r._now().astimezone(HK)
        if self.jpeg is None:
            lead = "New message from Brian"
        elif self.caption:
            lead = "New message from Brian (sent with the attached photo; this text is its caption)"
        else:
            lead = "New message from Brian (the attached photo, no caption)"
        return (f"Now: {now:%a} {now.day} {now:%b %H:%M}.\n\nProfile:\n{profile}\n\n"
                f"{r.context(self.day)}\n\n{lead}: {text}")

    def run_tool(self, name: str, data) -> str:
        r = self.r
        data = data if isinstance(data, dict) else {}
        card, queued = r.exercise_to_send, len(r.tail)
        try:
            fn = getattr(self, "t_" + name, None)
            if fn is None:
                raise ToolRefused(f"There is no tool {name}.")
            result = fn(data)
        except Exception as exc:
            kind = "refused" if isinstance(exc, ToolRefused) else "error"
            self.calls.append({"tool": name, "input": data, "result": f"{kind}: {exc}"[:200]})
            raise
        self.last_result = result
        if _changed(result):
            self.done.append(result)
        self.calls.append({"tool": name, "input": data, "result": result[:200]})
        notes = []
        if r.exercise_to_send is not None and r.exercise_to_send is not card:
            session, index = r.exercise_to_send
            notes.append(f"Queued: the code sends the card for {session['exercises'][index]['name']}"
                         " (sets, reps, weight, pictures) after your reply; do not repeat it.")
        for label, _ in r.tail[queued:]:
            notes.append(f"Queued: the code sends {label} after your reply; do not repeat it.")
        return "\n".join([result, *notes])

    # helpers
    def _strength(self) -> dict:
        session = self.r.store.plan_session(self.day)
        if not session or session["kind"] != "strength":
            raise ToolRefused("There is no strength session today.")
        return session

    def _index(self, session: dict, name) -> int:
        names = [e["name"] for e in session["exercises"]]
        found = next((i for i, n in enumerate(names) if key(n) == key(name)), None)
        if found is None:
            raise ToolRefused(f"\"{name}\" is not in today's session. Today's exercises: "
                              f"{', '.join(names)}.")
        return found

    def _logged_row(self, data: dict) -> dict:
        rows = self.r.store.logged_sets(self.day)
        name = data.get("exercise")
        mine = [r for r in rows if key(r["exercise"]) == key(name)]
        if not mine:
            have = sorted({r["exercise"] for r in rows})
            raise ToolRefused(f"No sets of \"{name}\" are saved today. Exercises with sets "
                              f"today: {', '.join(have) or 'none'}. Today's exercises: "
                              f"{self._names()}.")
        try:
            set_no = int(data.get("set_no"))
        except (TypeError, ValueError):
            set_no = None
        row = next((r for r in mine if r["set_no"] == set_no), None)
        if row is None:
            raise ToolRefused(f"{mine[0]['exercise']} has sets 1 to {len(mine)} saved today, "
                              f"not set {data.get('set_no')!r}.")
        return row

    def _names(self) -> str:
        session = self.r.store.plan_session(self.day) or {}
        return ", ".join(e["name"] for e in session.get("exercises", [])) or "none"

    # tools that change today's strength session or its sets (they open the workout)
    def t_log_sets(self, data: dict) -> str:
        raw = data.get("sets")
        if not isinstance(raw, list) or not raw:
            raise ToolRefused("sets must list at least one set.")
        session = self.r.store.plan_session(self.day)
        strength = bool(session and session["kind"] == "strength")
        names = {key(e["name"]): e["name"] for e in session["exercises"]} if strength else {}
        sets = []
        for s in raw:
            if not isinstance(s, dict) or not str(s.get("exercise", "")).strip():
                raise ToolRefused("Each set needs an exercise name and reps.")
            name = str(s["exercise"]).strip()
            reps = _positive_int(s.get("reps"), "reps")
            weight = _optional(s, "weight_kg")
            own = s.get("own") is True
            if key(name) in names:
                name = names[key(name)]
            elif strength and not own:
                raise ToolRefused(f"\"{name}\" is not in today's session. Today's exercises: "
                                  f"{', '.join(names.values())}. For his own exercise that is "
                                  "not in the list, set own true.")
            sets.append({"exercise": name, "weight_kg": weight, "reps": reps,
                         "effort": s.get("effort") or None, "own": own})
        if strength:
            self.r._open(self.day)
        return self.r._log(self.day, sets)

    def t_fix_set(self, data: dict) -> str:
        row = self._logged_row(data)
        weight, reps = _optional(data, "weight_kg"), data.get("reps")
        if reps is not None:
            reps = _positive_int(reps, "reps")
        if weight is None and reps is None:
            raise ToolRefused("Give weight_kg or reps (or both) for the set.")
        r = self.r
        r._open(self.day)
        others = [x for x in r.store.logged_sets(self.day) if x["id"] != row["id"]]
        line = r._fix_set(self.day, {"exercise": row["exercise"], "set_no": row["set_no"],
                                     "weight_kg": weight, "reps": reps})
        if line is None:
            return (f"No change: {row['exercise']} set {row['set_no']} is already "
                    f"{reports.sets_text([row])}.")
        far = (r._typo(self.day, [{"exercise": row["exercise"], "weight_kg": weight}], others)
               if weight else "")
        return (f"{line}. Today's log: {reports.format_exercise(r.store, self.day, row['exercise'])}."
                + far)

    def t_remove_set(self, data: dict) -> str:
        row = self._logged_row(data)
        self.r._open(self.day)
        reports.remove(self.r.store, self.day, row["id"])
        return (f"Removed {row['exercise']} set {row['set_no']} ({reports.sets_text([row])}). "
                f"Today's log: {reports.format_exercise(self.r.store, self.day, row['exercise'])}.")

    def t_show_exercise(self, data: dict) -> str:
        session = self._strength()
        wanted = str(data.get("exercise") or "next").strip()
        index = None if key(wanted) in ("next", "") else self._index(session, wanted)
        moved = (self._shown_here or len(self.r.tail) > self._tail_at_start
                 or self.r.store.get(FLOW_KEY + self.day) != self._flow_at_start)
        if index is None and moved:
            # an earlier tool in this message already moved on; a second "next" would skip
            # an exercise (replay of 22 Nov)
            return "Already moved on in this message; nothing changed."
        self.r._open(self.day)
        result = self.r._show(self.day, session, index)
        self._shown_here = True
        return result

    def t_swap_exercise(self, data: dict) -> str:
        r = self.r
        session = self._strength()
        index = self._index(session, data.get("exercise"))
        new = str(data.get("new_exercise") or "").strip()
        if not new:
            raise ToolRefused("Give new_exercise, the name of the exercise he does instead.")
        gear_list = r._equipment(session["gym"])
        gear = next((g for g in gear_list if key(g) == key(data.get("equipment"))), None)
        if gear is None:
            raise ToolRefused(f"\"{data.get('equipment')}\" is not on the {session['gym']} gym "
                              "list. Use one of these names exactly:\n"
                              + "\n".join(f"- {g}" for g in gear_list))
        weight = _optional(data, "weight_kg")
        r._open(self.day)
        done = reports.sets_done(r.store, self.day, session["exercises"][index]["name"])
        return r._swap(session, index, done, new, gear, weight, self.day)

    def t_drop_exercise(self, data: dict) -> str:
        session = self._strength()
        index = self._index(session, data.get("exercise"))
        self.r._open(self.day)
        return self.r._drop(session, index, self.day)

    def t_set_weight(self, data: dict) -> str:
        session = self._strength()
        index = self._index(session, data.get("exercise"))
        weight = _positive(data.get("weight_kg"), "weight_kg")
        r = self.r
        r._open(self.day)
        ex = session["exercises"][index]
        far = r._typo(self.day, [{"exercise": ex["name"], "weight_kg": weight}],
                      r.store.logged_sets(self.day))
        ex["weight_kg"] = weight
        r._save(session)
        return f"{ex['name']} today: {weight:g} kg." + far

    def t_log_cardio(self, data: dict) -> str:
        activity = str(data.get("activity") or "").strip()
        if not activity:
            raise ToolRefused("Give the activity, e.g. jogging.")
        minutes = _positive(data.get("minutes"), "minutes")
        distance = _optional(data, "distance_km")
        hr = None if data.get("avg_hr") is None else _positive_int(data["avg_hr"], "avg_hr")
        r = self.r
        now = r._now().astimezone(HK).isoformat(timespec="seconds")
        r.store.add_cardio(self.day, activity, minutes, distance, hr, now)
        reports.mark_done(r.store, self.day)
        row = r.store.cardio_on(self.day)[-1]
        return f"Saved cardio: {reports.cardio_text(row)}."

    def t_finish_workout(self, data: dict) -> str:
        self.r.tail.append(("the summary of today's workout", self.r._end(self.day)))
        return "Workout closed (the day is marked done when sets or cardio are logged)."

    # the rest
    def t_skip_today(self, data: dict) -> str:
        if not self.r.store.plan_session(self.day):
            return "There is no session planned today; nothing changed."
        self.r.store.set_plan_status(self.day, "skipped")
        reports.close_workout(self.r.store, self.day)
        return "Skipped today's session."

    def t_log_meal(self, data: dict) -> str:
        r = self.r
        description = str(data.get("description") or "").strip()
        use_photo = data.get("use_photo") is True
        if use_photo and self.jpeg is None:
            raise ToolRefused("No photo came with this message; set use_photo false.")
        if use_photo and r._workout_since(self.day) is not None:
            raise ToolRefused("A photo sent during the workout is never a meal; nothing logged. "
                              "Answer it as a question about the workout.")
        if not description and not use_photo:
            raise ToolRefused("Give a description of the meal.")
        now = r._now().astimezone(HK)
        meal = meals.log_meal(r.store, r.claude, r.fast, now, description or None,
                              self.jpeg if use_photo else None)
        if meal.get("meal") is False:
            return f"The photo shows {meal['what']}, not food; nothing logged."
        return meals.reply(r.store, self.day, meal, r._profile())

    def t_correct_meal(self, data: dict) -> str:
        r = self.r
        kcal, protein = _optional(data, "kcal"), _optional(data, "protein_g")
        if kcal is None and protein is None:
            raise ToolRefused("Give kcal or protein_g (or both).")
        today = r.store.meals_on(self.day)
        if not today:
            raise ToolRefused("No meal is logged today, so there is nothing to correct.")
        r.store.update_last_meal(self.day, round(kcal) if kcal is not None
                                 else today[-1]["kcal"],
                                 None if protein is None else round(protein))
        return "Corrected the last meal. " + meals.total_line(r.store, self.day, r._profile())

    def t_log_body(self, data: dict) -> str:
        r = self.r
        weight = _positive(data.get("weight_kg"), "weight_kg")
        waist = _optional(data, "waist_cm")
        last = targets.current_targets(r.store, r._profile()).weight_kg
        if abs(weight - last) > BODY_JUMP_KG and data.get("confirmed") is not True:
            return (f"Not saved: {weight:g} kg is {abs(weight - last):.1f} kg "
                    f"{'above' if weight > last else 'below'} his last weight ({last:g} kg). "
                    "ask him if it is right; once he confirms, call log_body with confirmed "
                    "true.")
        return r._save_body(self.day, weight, waist)

    def t_note_plan_change(self, data: dict) -> str:
        change = str(data.get("change") or "").strip()
        if not change:
            raise ToolRefused("Give the change he wants.")
        return self.r._note_change(change)

    def t_revise_proposed_week(self, data: dict) -> str:
        r = self.r
        change = str(data.get("change") or "").strip()
        if not r._week_finished():
            if change:
                r._note_change(change)
            raise ToolRefused("Not revised: this week's sessions are not over yet (he asked to "
                              "plan only after the week). The change is kept as a note; the "
                              "bot asks about it once this week's last session is done.")
        r.tail.append(("the proposed week with every session", r._revise(change)))
        return "The proposed week is written."

    def t_approve_plan(self, data: dict) -> str:
        return self.r._approve()
