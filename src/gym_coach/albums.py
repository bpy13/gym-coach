"""The photos of a session's machines, shrunk and ready to send as one album."""

from __future__ import annotations

import io
import logging
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from gym_coach.context import DEFAULT_EQUIPMENT, DEFAULT_PHOTOS, equipment_photo_ids, photo_file

log = logging.getLogger(__name__)
MAX_EDGE = 1280


def shrink(data: bytes, max_edge: int = MAX_EDGE) -> bytes:
    """JPEG bytes of the image with its long edge at most `max_edge` px."""
    with Image.open(io.BytesIO(data)) as img:
        img = img.convert("RGB")
        img.thumbnail((max_edge, max_edge))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=85)
    return out.getvalue()


def _illustration(ex: dict, illustrations) -> list[tuple[bytes, str]]:
    """The start and end images of a free-weight or cable exercise; the first carries the
    exercise name and a form cue. [] when there is none (the exercise still goes in the text)."""
    ex_id = ex.get("illustration")
    if not ex_id or illustrations is None:
        return []
    try:
        images = [shrink(data) for data in illustrations.images(ex_id)]
        cue = illustrations.cue(ex_id)
    except (OSError, UnidentifiedImageError):
        log.warning("illustration %s could not be read; skipped", ex_id)
        return []
    caption = f"{ex['name']}\n{cue}" if cue else str(ex["name"])
    return [(img, caption if i == 0 else "") for i, img in enumerate(images)]


def session_album(session: dict, equipment_path=None, photos_dir=None,
                  illustrations=None) -> list[tuple[bytes, str]]:
    """(jpeg bytes, caption) per image: Brian's photo of the machine for an exercise that has
    one, else the exercise's two illustrations. [] on cardio days.

    An exercise without either, a missing file or an unreadable image is skipped.
    """
    if session["kind"] == "cardio":
        return []
    ids = equipment_photo_ids(session["gym"], equipment_path or DEFAULT_EQUIPMENT)
    album: list[tuple[bytes, str]] = []
    for ex in session["exercises"]:
        photo_id = ids.get(str(ex.get("equipment", "")).strip().lower())
        found = photo_file(session["gym"], photo_id, photos_dir or DEFAULT_PHOTOS) if photo_id else None
        if found is None:
            album.extend(_illustration(ex, illustrations))
            continue
        try:
            album.append((shrink(Path(found).read_bytes()), str(ex["name"])))
        except (OSError, UnidentifiedImageError):
            log.warning("photo %s could not be read; skipped", photo_id)
    return album
