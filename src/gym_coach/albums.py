"""The photos of a session's machines, shrunk and ready to send as one album."""

from __future__ import annotations

import io
import logging
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from gym_coach.context import DEFAULT_EQUIPMENT, DEFAULT_PHOTOS, equipment_photo_ids, photo_file

log = logging.getLogger(__name__)
MAX_EDGE = 1280
MAX_ALBUM = 10  # Telegram's limit for one media group


def shrink(data: bytes, max_edge: int = MAX_EDGE) -> bytes:
    """JPEG bytes of the image with its long edge at most `max_edge` px."""
    with Image.open(io.BytesIO(data)) as img:
        img = img.convert("RGB")
        img.thumbnail((max_edge, max_edge))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=85)
    return out.getvalue()


def session_album(session: dict, equipment_path=None, photos_dir=None) -> list[tuple[bytes, str]]:
    """(jpeg bytes, exercise name) per exercise whose machine has a photo; [] on cardio days.

    An exercise without a photo id, a missing file or an unreadable image is skipped.
    """
    if session["kind"] == "cardio":
        return []
    ids = equipment_photo_ids(session["gym"], equipment_path or DEFAULT_EQUIPMENT)
    album: list[tuple[bytes, str]] = []
    for ex in session["exercises"]:
        photo_id = ids.get(str(ex.get("equipment", "")).strip().lower())
        found = photo_file(session["gym"], photo_id, photos_dir or DEFAULT_PHOTOS) if photo_id else None
        if found is None:
            continue
        try:
            album.append((shrink(Path(found).read_bytes()), str(ex["name"])))
        except (OSError, UnidentifiedImageError):
            log.warning("photo %s could not be read; skipped", photo_id)
        if len(album) == MAX_ALBUM:
            break
    return album
