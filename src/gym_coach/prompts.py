"""Fixed prompt text for the coach model."""

CARDIO_SENTENCE = (
    "I placed cardio on the days between strength sessions; tell me if you meant something else"
)

PLAN_SYSTEM = f"""You are a careful personal gym coach writing a one-week plan for a beginner.
You give general fitness guidance, not medical advice. Fixed rules:
- Exactly three strength sessions a week, in the late afternoon. Saturday is free in the morning
  only, so put no strength session on Saturday: use weekdays and Sunday.
- Cardio at a heart rate of about 130 bpm on days between the strength sessions.
- Full-body strength sessions: 5 to 7 exercises, 3 sets each, rep range 8 to 12.
- First-week weights are light (the first week is a test of working weights). Dumbbell weights
  are in 2 kg steps. Machines use whole pin steps.
- Weekdays are at the home gym, Saturday and Sunday at the parents' gym. Use ONLY equipment
  from that day's gym list, and write the equipment name exactly as it appears in the list.
- For dumbbell, cable and barbell exercises you may add "illustration": an id from that gym's
  illustration list below (the exercise it shows must match the exercise you chose); leave it
  out when none fits. Machine exercises need no illustration.
- The message to the user must contain this sentence: "{CARDIO_SENTENCE}". It must also ask
  how hard each set felt, and say this is general fitness guidance, not medical advice.

Answer with JSON only, in this shape:
{{"message": "<short text for the user>",
 "sessions": [
  {{"date": "YYYY-MM-DD", "kind": "strength",
   "exercises": [{{"name": "...", "equipment": "...", "sets": 3,
                  "rep_low": 8, "rep_high": 12, "weight_kg": 20,
                  "illustration": "<id or omit>"}}]}},
  {{"date": "YYYY-MM-DD", "kind": "cardio", "exercises": []}}]}}
"""


def plan_prompt(profile: str, home: set[str], parents: set[str], dates: list[str],
                previous: list[dict] | None = None, change: str | None = None,
                error: str | None = None,
                illustrations: dict[str, dict[str, str]] | None = None) -> str:
    parts = [
        "Profile:\n" + profile,
        "Home gym equipment (weekdays):\n" + "\n".join(f"- {e}" for e in sorted(home)),
        "Parents' gym equipment (weekends):\n" + "\n".join(f"- {e}" for e in sorted(parents)),
        "Dates of the week to plan: " + ", ".join(dates),
    ]
    for gym, label in (("home", "Home"), ("parents", "Parents'")):
        if illustrations and illustrations.get(gym):
            parts.append(f"{label} gym illustration ids (id: exercise):\n" + "\n".join(
                f"{i}: {n}" for i, n in illustrations[gym].items()))
    if previous:
        parts.append("Current proposal (JSON): " + str(previous))
    if change:
        parts.append(f"The user asks for this change to the proposal: {change}")
    if error:
        parts.append(f"Your previous answer was rejected: {error}\nFix it.")
    return "\n\n".join(parts)
