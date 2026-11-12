"""Text of the messages the bot sends on its own."""

from datetime import date

GYM_NAMES = {"home": "Home gym", "parents": "Parents' gym"}


def _weight(kg) -> str:
    return f"{kg:g} kg" if isinstance(kg, (int, float)) else "light weight"


def session_message(session: dict) -> str:
    """The day's session: gym and date on the first line, then one line per exercise."""
    day = date.fromisoformat(session["date"])
    head = f"{GYM_NAMES.get(session['gym'], session['gym'])}, {day:%a} {day.day} {day:%b}"
    if session["kind"] == "cardio":
        return f"{head}\nCardio today at a heart rate of about 130."
    lines = [
        f"{e['name']}: {e['sets']} x {e['rep_low']}-{e['rep_high']} at {_weight(e.get('weight_kg'))}"
        for e in session["exercises"]
    ]
    return "\n".join([head, *lines, "Reply with what you did, and how hard each set felt."])
