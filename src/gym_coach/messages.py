"""Text of the messages the bot sends on its own."""

from datetime import date

CLOSING = "Reply with what you did, and how hard each set felt."
GYM_NAMES = {"home": "Home gym", "parents": "Parents' gym"}

# Task 14j. The warm-up before every strength session (Brian: "include warm up exercises such
# as bear walk"): no equipment, two rounds, about 8 minutes. Change it here.
WARM_UP = [
    ("Jumping jacks", "1 min"),
    ("Arm circles", "30 s forward, 30 s back"),
    ("High knees", "45 s"),
    ("Bodyweight squats", "15 reps"),
    ("Bear crawl", "30 s forward, 30 s back"),
]
# Stretches after the last exercise: one per muscle group the day's exercise names match
# (first match wins per exercise), plus the two that always come; about 1 minute each, so
# 4 to 7 minutes in all.
STRETCHES = [
    (("leg curl", "deadlift", "hamstring", "rdl"), "Standing hamstring stretch: 30 s each leg"),
    (("leg ext", "leg press", "squat", "lunge"), "Standing quad stretch: 30 s each leg"),
    (("chest", "bench", "fly", "push"), "Doorway chest stretch: 30 s each side"),
    (("shoulder", "lateral", "raise", "halo"), "Cross-body shoulder stretch: 30 s each arm"),
    (("pulldown", "row", "pull"), "Lat stretch, hands on a post, hips back: 30 s each side"),
    (("biceps", "triceps", "arm"), "Overhead triceps stretch: 30 s each arm"),
]
ALWAYS_STRETCH = ["Hip flexor lunge stretch: 30 s each side", "Child's pose: 1 min"]


def warm_up_message() -> str:
    lines = [f"- {name}: {amount}" for name, amount in WARM_UP]
    return ("Warm-up first (about 8 minutes, no equipment), 2 rounds:\n" + "\n".join(lines)
            + "\nSay \"done\" when you finish it and I'll send the first exercise.")


def stretch_message(session: dict) -> str:
    """The stretches for the day's exercises, then the ones that always come."""
    picked = []
    for ex in session.get("exercises", []):
        name = ex["name"].lower()
        line = next((s for keys, s in STRETCHES if any(k in name for k in keys)), None)
        if line and line not in picked:
            picked.append(line)
    lines = [f"- {s}" for s in picked + ALWAYS_STRETCH]  # about 1 minute each
    return (f"Stretch now (about {len(lines)} minutes):\n" + "\n".join(lines)
            + "\nTap \"Finish session\" when you are done.")


def _weight(kg) -> str:
    return f"{kg:g} kg" if isinstance(kg, (int, float)) else "light weight"


def head(session: dict) -> str:
    day = date.fromisoformat(session["date"])
    return f"{GYM_NAMES.get(session['gym'], session['gym'])}, {day:%a} {day.day} {day:%b}"


def exercise_line(e: dict) -> str:
    return f"{e['name']}: {e['sets']} x {e['rep_low']}-{e['rep_high']} at {_weight(e.get('weight_kg'))}"


def _lines(session: dict) -> list[str]:
    return [exercise_line(e) for e in session["exercises"]]


def session_message(session: dict) -> str:
    """The day's session: gym and date on the first line, then one line per exercise."""
    title = head(session)
    if session["kind"] == "cardio":
        return f"{title}\nCardio today at a heart rate of about 130."
    return "\n".join([title, *_lines(session), CLOSING])


def list_message(session: dict) -> str:
    """The day's session as a plain list (no pictures); the exercises follow one by one."""
    if session["kind"] == "cardio":
        return session_message(session)
    return "\n".join([head(session), *_lines(session)])


def proposal_message(intro: str, sessions: list[dict]) -> str:
    """The coach's introduction, then every day of the proposed week with its exercises."""
    blocks = []
    for s in sessions:
        if s["kind"] == "cardio":
            blocks.append(f"{head(s)}: cardio at a heart rate of about 130.")
        else:
            blocks.append("\n".join([f"{head(s)}: strength", *_lines(s)]))
    return "\n\n".join([intro, *blocks]) if blocks else intro
