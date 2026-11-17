"""A session as Telegram messages: one per exercise, with its pictures shrunk and captioned."""

from __future__ import annotations

import io
import logging
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from gym_coach.context import DEFAULT_EQUIPMENT, DEFAULT_PHOTOS, equipment_photo_ids, photo_file
from gym_coach.messages import CLOSING, exercise_line, head, session_message

log = logging.getLogger(__name__)
MAX_EDGE = 1280
NL = chr(10)


def shrink(data: bytes, max_edge: int = MAX_EDGE) -> bytes:
    """JPEG bytes of the image with its long edge at most `max_edge` px."""
    with Image.open(io.BytesIO(data)) as img:
        img = img.convert("RGB")
        img.thumbnail((max_edge, max_edge))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=85)
    return out.getvalue()


def _pictures(ex: dict, ids: dict, photos_dir, gym: str, illustrations) -> tuple[list[bytes], str]:
    """(jpeg images, form cue) for one exercise: Brian's photo of the machine when it uses one,
    then the illustration of the movement when it has one."""
    images: list[bytes] = []
    cue = ""
    photo_id = ids.get(str(ex.get("equipment", "")).strip().lower())
    found = photo_file(gym, photo_id, photos_dir) if photo_id else None
    if found is not None:
        try:
            images.append(shrink(Path(found).read_bytes()))
        except (OSError, UnidentifiedImageError):
            log.warning("photo %s could not be read; skipped", photo_id)
    ex_id = ex.get("illustration")
    if ex_id and illustrations is not None:
        try:
            images.extend(shrink(data) for data in illustrations.images(ex_id))
            cue = illustrations.cue(ex_id)
        except (OSError, UnidentifiedImageError):
            log.warning("illustration %s could not be read; skipped", ex_id)
    return images, cue


def exercise_parts(session: dict, index: int, equipment_path=None, photos_dir=None,
                   illustrations=None, show_tip: bool = True) -> tuple[str, list[bytes]]:
    """The message of exercise number `index` of a strength session, as (caption, jpeg images):
    its pictures, if any, with ONE caption (name, sets x reps at weight; the form cue only when
    `show_tip` is on, default off)."""
    ids = equipment_photo_ids(session["gym"], equipment_path or DEFAULT_EQUIPMENT)
    ex = session["exercises"][index]
    images, cue = _pictures(ex, ids, photos_dir or DEFAULT_PHOTOS, session["gym"], illustrations)
    if not images:
        log.warning("exercise %r goes out without a picture", ex.get("name"))
    return exercise_line(ex) + (f"{NL}{cue}" if cue and show_tip else ""), images


def session_parts(session: dict, equipment_path=None, photos_dir=None, illustrations=None,
                  closing: bool = True, show_tip: bool = True) -> list[tuple[str, list[bytes]]]:
    """All messages of a session at once, in order, as (text, jpeg images). Used for the
    proposal's preview; the daily session goes out one exercise at a time (the router).

    Cardio is one text message. A strength session is a header (gym and date), one message
    per exercise (its pictures, if any, with ONE caption: name, sets x reps at weight, form
    cue; an exercise with no picture is text only), then the closing line.
    """
    if session["kind"] == "cardio":
        return [(session_message(session), [])]
    parts: list[tuple[str, list[bytes]]] = [(head(session), [])]
    for i in range(len(session["exercises"])):
        parts.append(exercise_parts(session, i, equipment_path, photos_dir, illustrations,
                                    show_tip))
    if closing:
        parts.append((CLOSING, []))
    return parts
