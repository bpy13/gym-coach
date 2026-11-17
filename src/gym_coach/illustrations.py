r"""Illustrations of free-weight and cable exercises, from the open free-exercise-db.

Source: https://github.com/yuhonas/free-exercise-db (Unlicense, public domain). The exercise
list is downloaded once into `data\illustrations\`; the two images of an exercise are
downloaded the first time that exercise is sent. Nothing here is ever committed.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import httpx

log = logging.getLogger(__name__)
BASE = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main"
DEFAULT_DIR = Path("data/illustrations")
CUE_CHARS = 60  # one line on a phone

# words in an equipment name -> the database's equipment value
_KINDS = (("dumbbell", "dumbbell"), ("cable", "cable"), ("ez curl", "e-z curl bar"),
          ("barbell", "barbell"))


_STOP = {"the", "a", "with", "to", "on", "of", "and", "dumbbell", "cable", "barbell", "ez", "bar",
         "machine"}
_LYING = {"lying", "prone", "supine", "incline", "decline", "flat"}
# Weight-stack pulldown and low-row towers: the catalogue files these exercises under cable.
_CABLE_TOWERS = ("pulldown", "pull-down", "low row")


def kinds_of(equipment: str) -> set[str]:
    """The database equipment values an exercise's equipment name stands for; a name with no
    free-weight or cable word is one of Brian's machines."""
    low = str(equipment).lower()
    kinds = {kind for word, kind in _KINDS if word in low} or {"machine"}
    if any(word in low for word in _CABLE_TOWERS):
        kinds.add("cable")
    return kinds


def position(name: str) -> str | None:
    """Body position an exercise name states: incline, decline, lying, seated, standing."""
    words = set("".join(c if c.isalnum() else " " for c in str(name).lower()).split())
    for w in ("incline", "decline"):
        if w in words:
            return w
    if words & _LYING:
        return "lying"
    if words & {"seated", "sitting"}:
        return "seated"
    return "standing" if "standing" in words else None


def positions_agree(a: str | None, b: str | None) -> bool:
    """Same position; or one side silent and the other only seated/standing (the usual way)."""
    if a == b:
        return True
    return (a is None and b in ("seated", "standing")) or (b is None and a in ("seated", "standing"))


def _words(text: str) -> set[str]:
    out = set()
    for w in "".join(c if c.isalnum() else " " for c in str(text).lower()).split():
        if w not in _STOP:
            out.add(w[:-1] if len(w) > 3 and w.endswith("s") else w)
    return out


def _http_get(url: str) -> bytes:
    resp = httpx.get(url, timeout=20, follow_redirects=True)
    resp.raise_for_status()
    return resp.content


class Illustrations:
    def __init__(self, folder: Path | str = DEFAULT_DIR, http_get=_http_get):
        self.folder = Path(folder)
        self._get = http_get
        self._catalog: dict[str, dict] | None = None

    def catalog(self) -> dict[str, dict]:
        """id -> database entry; {} when the list cannot be loaded (then no illustrations)."""
        if self._catalog is None:
            path = self.folder / "exercises.json"
            try:
                if not path.is_file():
                    data = self._get(f"{BASE}/dist/exercises.json")
                    json.loads(data)
                    self.folder.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
                self._catalog = {e["id"]: e for e in json.loads(path.read_text(encoding="utf-8"))}
            except (OSError, ValueError, KeyError, httpx.HTTPError):
                log.warning("exercise illustrations are not available")
                return {}
        return self._catalog

    def allowed(self, equipment: set[str], machines: bool = False) -> dict[str, str]:
        """id -> name of the beginner strength exercises that need only free weights or
        cables present in `equipment` (a set of equipment names at one gym). With `machines`,
        the catalogue's machine exercises of any level are listed too."""
        kinds = {kind for word, kind in _KINDS if any(word in name for name in equipment)}
        return {i: e["name"] for i, e in sorted(self.catalog().items())
                if e.get("category") == "strength"
                and ((e.get("equipment") in kinds and e.get("level") == "beginner")
                     or (machines and e.get("equipment") == "machine"))}

    def fits(self, ex_id: str, equipment: str, name: str | None = None) -> bool:
        """Whether the catalogue entry uses the kind of equipment the exercise uses and, when
        the exercise `name` is given, shows it in the same body position."""
        entry = self.catalog().get(ex_id) or {}
        return (entry.get("equipment") in kinds_of(equipment)
                and (name is None or positions_agree(position(name), position(entry.get("name", "")))))

    def cue(self, ex_id: str) -> str:
        """One short form cue: the first instruction sentence of the exercise."""
        steps = (self.catalog().get(ex_id) or {}).get("instructions") or []
        text = " ".join(str(steps[0]).split()) if steps else ""
        text = re.split(r"(?<=[.!?])\s", text, maxsplit=1)[0]
        return text if len(text) <= CUE_CHARS else text[:CUE_CHARS].rsplit(" ", 1)[0] + "..."

    def images(self, ex_id: str) -> list[bytes]:
        """The start and end images (bytes) of an exercise; [] when unknown or unreachable."""
        entry = self.catalog().get(ex_id)
        if not entry:
            return []
        out = []
        for rel in entry.get("images", [])[:2]:
            if ".." in rel or rel.startswith(("/", "\\")):
                continue
            cached = self.folder / "images" / rel
            try:
                if not cached.is_file():
                    data = self._get(f"{BASE}/exercises/{rel}")
                    cached.parent.mkdir(parents=True, exist_ok=True)
                    cached.write_bytes(data)
                out.append(cached.read_bytes())
            except (OSError, httpx.HTTPError):
                log.warning("illustration %s could not be fetched", ex_id)
                return []
        return out

    def match(self, name: str, equipment: str, allowed: dict[str, str]) -> str | None:
        """The id in `allowed` (id -> name) that shows the exercise `name`, or None.

        Only entries whose database equipment fits the exercise's equipment name are
        considered, and its body position (incline, lying, seated, standing) must agree
        with the exercise's; the name must match exactly (ignoring case, plurals, filler words) or
        share at least 70% of its words, or one name contains all words of the other (two or more).
        """
        kinds = kinds_of(equipment)
        want = _words(name)
        want_pos = position(name)
        best, best_score = None, (0.0,)
        for i, n in allowed.items():
            if (self.catalog().get(i) or {}).get("equipment") not in kinds:
                continue
            if not positions_agree(want_pos, position(n)):
                continue
            have = _words(n)
            if not want or not have:
                continue
            overlap = len(want & have) / len(want | have)
            score = overlap
            small, large = sorted((want, have), key=len)
            if len(small) >= 2 and small <= large:  # one name only adds detail to the other
                score = max(score, 0.7)
            # ties: the closer name, then a two-handed variant over a one-arm one
            one_arm = bool(have & {"one", "single"}) and not want & {"one", "single"}
            key = (score, overlap, not one_arm)
            if key > best_score:
                best, best_score = i, key
        return best if best_score[0] >= 0.7 else None
