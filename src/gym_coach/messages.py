"""Text of the messages the bot sends on its own."""

from datetime import date

CLOSING = "Reply with what you did, and how hard each set felt."
GYM_NAMES = {"home": "Home gym", "parents": "Parents' gym"}


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


def proposal_message(intro: str, sessions: list[dict]) -> str:
    """The coach's introduction, then every day of the proposed week with its exercises."""
    blocks = []
    for s in sessions:
        if s["kind"] == "cardio":
            blocks.append(f"{head(s)}: cardio at a heart rate of about 130.")
        else:
            blocks.append("\n".join([f"{head(s)}: strength", *_lines(s)]))
    return "\n\n".join([intro, *blocks]) if blocks else intro
