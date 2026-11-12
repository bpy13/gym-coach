"""Which gym a day uses, what equipment it has, and the profile text for the coach."""

import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HK = ZoneInfo("Asia/Hong_Kong")
DEFAULT_EQUIPMENT = Path("data/equipment.md")
DEFAULT_PROFILE = Path("data/profile.md")
DEFAULT_PHOTOS = Path("photos")

_HEADINGS = {"home": "home gym", "parents": "parents' gym"}


def gym_for(when: date | datetime) -> str:
    """'home' Monday-Friday, 'parents' Saturday-Sunday (Hong Kong time for aware datetimes)."""
    if isinstance(when, datetime):
        if when.tzinfo is not None:
            when = when.astimezone(HK)
        when = when.date()
    return "home" if when.weekday() < 5 else "parents"


def _item_name(text: str) -> str:
    return re.split(r"[:,.]", text, maxsplit=1)[0].strip().lower()


def equipment_for(gym: str, path: Path | str = DEFAULT_EQUIPMENT) -> set[str]:
    """Names of the equipment available at `gym`, from the bullet lists in equipment.md.

    Items marked "unsure" (other than unsure dumbbell steps) and anything under a
    "Not seen" label do not count as available.
    """
    if gym not in _HEADINGS:
        raise ValueError(f"Unknown gym {gym!r}")
    items: set[str] = set()
    in_section = False
    skipping = False
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("## "):
            in_section = line[3:].lower().startswith(_HEADINGS[gym])
            skipping = False
            continue
        if not in_section or not line:
            if not line:
                skipping = False
            continue
        if not line.startswith("- "):
            skipping = line.lower().startswith("not seen")
            continue
        if skipping:
            continue
        text = line[2:].strip()
        low = text.lower()
        if "unsure" in low and "unsure of the steps" not in low:
            continue
        name = _item_name(text)
        if name:
            items.add(name)
    return items


def equipment_photo_ids(gym: str, path: Path | str = DEFAULT_EQUIPMENT) -> dict[str, str]:
    """Photo id beside each equipment item of `gym`, e.g. "Chest press: seen (IMG_1)"."""
    if gym not in _HEADINGS:
        raise ValueError(f"Unknown gym {gym!r}")
    ids: dict[str, str] = {}
    in_section = False
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("## "):
            in_section = line[3:].lower().startswith(_HEADINGS[gym])
        elif in_section and line.startswith("- "):
            found = re.search(r"\((IMG_[^)\s]+)\)", line)
            name = _item_name(line[2:])
            if found and name:
                ids.setdefault(name, found.group(1))
    return ids


def photo_file(gym: str, photo_id: str, photos_dir: Path | str = DEFAULT_PHOTOS) -> Path | None:
    """The file photos/<gym>/<photo_id>.<ext>, or None when it is not there."""
    folder = Path(photos_dir) / gym
    if not folder.is_dir():
        return None
    for f in sorted(folder.iterdir()):
        if f.stem == photo_id and f.is_file():
            return f
    return None


def profile_text(path: Path | str = DEFAULT_PROFILE) -> str:
    return Path(path).read_text(encoding="utf-8")
