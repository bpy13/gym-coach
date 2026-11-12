r"""Illustrations of free-weight and cable exercises, from the open free-exercise-db.

Source: https://github.com/yuhonas/free-exercise-db (Unlicense, public domain). The exercise
list is downloaded once into `data\illustrations\`; the two images of an exercise are
downloaded the first time that exercise is sent. Nothing here is ever committed.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx

log = logging.getLogger(__name__)
BASE = "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main"
DEFAULT_DIR = Path("data/illustrations")
CUE_CHARS = 160

# words in an equipment name -> the database's equipment value
_KINDS = (("dumbbell", "dumbbell"), ("cable", "cable"), ("ez curl", "e-z curl bar"),
          ("barbell", "barbell"))


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

    def allowed(self, equipment: set[str]) -> dict[str, str]:
        """id -> name of the beginner strength exercises that need only free weights or
        cables present in `equipment` (a set of equipment names at one gym)."""
        kinds = {kind for word, kind in _KINDS if any(word in name for name in equipment)}
        return {i: e["name"] for i, e in sorted(self.catalog().items())
                if e.get("equipment") in kinds and e.get("level") == "beginner"
                and e.get("category") == "strength"}

    def cue(self, ex_id: str) -> str:
        """One short form cue: the first instruction sentence of the exercise."""
        steps = (self.catalog().get(ex_id) or {}).get("instructions") or []
        text = str(steps[0]).strip() if steps else ""
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
