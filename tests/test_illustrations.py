import io
import json
from datetime import date, datetime

import httpx
import pytest
from PIL import Image

from fakes import FakeClaude
from gym_coach.albums import session_album
from gym_coach.illustrations import Illustrations
from gym_coach.llm import HK, Claude
from gym_coach.planner import propose
from gym_coach.store import Store

CATALOG = [
    {"id": "Goblet_Squat", "name": "Goblet Squat", "equipment": "dumbbell", "level": "beginner",
     "category": "strength", "images": ["Goblet_Squat/0.jpg", "Goblet_Squat/1.jpg"],
     "instructions": ["Hold one dumbbell at your chest. " + "Keep your back straight. " * 20,
                      "Squat."]},
    {"id": "Cable_Row", "name": "Cable Row", "equipment": "cable", "level": "beginner",
     "category": "strength", "images": ["Cable_Row/0.jpg", "Cable_Row/1.jpg"],
     "instructions": ["Pull the handle to your waist."]},
    {"id": "Heavy_Snatch", "name": "Snatch", "equipment": "dumbbell", "level": "expert",
     "category": "strength", "images": [], "instructions": []},
    {"id": "Barbell_Curl", "name": "Barbell Curl", "equipment": "barbell", "level": "beginner",
     "category": "strength", "images": [], "instructions": []},
]


def jpeg():
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "blue").save(buf, "JPEG")
    return buf.getvalue()


class Net:
    """Fake download function: counts calls per url."""

    def __init__(self, fail=False):
        self.urls, self.fail = [], fail

    def __call__(self, url):
        self.urls.append(url)
        if self.fail:
            raise httpx.ConnectError("down")
        return json.dumps(CATALOG).encode() if url.endswith(".json") else jpeg()


@pytest.fixture
def ill(tmp_path):
    net = Net()
    return Illustrations(tmp_path / "ill", http_get=net), net


def test_catalog_downloaded_once_and_cached(ill, tmp_path):
    i, net = ill
    assert "Goblet_Squat" in i.catalog()
    again = Illustrations(tmp_path / "ill", http_get=Net(fail=True))
    assert "Cable_Row" in again.catalog()  # read from disk, no download
    assert len(net.urls) == 1


def test_allowed_filters_by_gym_equipment_and_level(ill):
    i, _ = ill
    assert set(i.allowed({"dumbbells on a two-shelf rack", "dual adjustable cable machine"})) \
        == {"Goblet_Squat", "Cable_Row"}
    assert set(i.allowed({"dumbbells on a rack"})) == {"Goblet_Squat"}
    assert i.allowed({"chest press"}) == {}


def test_images_fetched_on_demand_only_for_that_exercise(ill):
    i, net = ill
    assert len(i.images("Goblet_Squat")) == 2
    i.images("Goblet_Squat")  # cached
    assert [u for u in net.urls if u.endswith(".jpg")] == [
        u for u in net.urls if "Goblet_Squat" in u]
    assert len(net.urls) == 3  # catalog + two images
    assert i.images("Nope") == []


def test_unreachable_network_gives_no_images_and_no_catalog(tmp_path):
    i = Illustrations(tmp_path / "x", http_get=Net(fail=True))
    assert i.catalog() == {} and i.allowed({"dumbbell"}) == {} and i.images("Goblet_Squat") == []


def test_cue_is_short(ill):
    i, _ = ill
    cue = i.cue("Goblet_Squat")
    assert cue.startswith("Hold one dumbbell") and len(cue) <= 170 and cue.endswith("...")


EQUIPMENT = """## Home gym (weekdays)

- Chest press: seen (IMG_A1)
- Dumbbells on a rack: seen

## Parents' gym (weekends)

- Chest press: seen
"""


def ex(name, equipment, **kw):
    return {"name": name, "equipment": equipment, "sets": 3, "rep_low": 8, "rep_high": 12,
            "weight_kg": 10, **kw}


@pytest.fixture
def gym_files(tmp_path):
    eq = tmp_path / "eq.md"
    eq.write_text(EQUIPMENT, encoding="utf-8")
    photos = tmp_path / "photos" / "home"
    photos.mkdir(parents=True)
    (photos / "IMG_A1.jpg").write_bytes(jpeg())
    return eq, tmp_path / "photos"


def test_album_has_machine_photo_and_two_illustrations(ill, gym_files):
    i, _ = ill
    eq, photos = gym_files
    session = {"date": "2026-11-17", "gym": "home", "kind": "strength", "exercises": [
        ex("Chest press", "chest press"),
        ex("Goblet squat", "dumbbells on a rack", illustration="Goblet_Squat"),
        ex("Mystery", "dumbbells on a rack", illustration="Not_In_Db"),
        ex("Plain", "dumbbells on a rack")]}
    album = session_album(session, eq, photos, illustrations=i)
    assert [c.split("\n")[0] for _, c in album] == ["Chest press", "Goblet squat", ""]
    assert "Hold one dumbbell" in album[1][1]


def test_album_without_illustrations_unchanged(gym_files):
    eq, photos = gym_files
    session = {"date": "2026-11-17", "gym": "home", "kind": "strength", "exercises": [
        ex("Squat", "dumbbells on a rack", illustration="Goblet_Squat")]}
    assert session_album(session, eq, photos) == []


def test_album_survives_unreachable_images(gym_files, tmp_path):
    eq, photos = gym_files
    down = Illustrations(tmp_path / "d", http_get=Net(fail=True))
    session = {"date": "2026-11-17", "gym": "home", "kind": "strength", "exercises": [
        ex("Squat", "dumbbells on a rack", illustration="Goblet_Squat")]}
    assert session_album(session, eq, photos, illustrations=down) == []


def test_proposal_keeps_only_listed_illustration_ids(ill, tmp_path):
    i, _ = ill
    store = Store(tmp_path / "t.db")
    days = ("2026-11-16", "2026-11-18", "2026-11-20")
    sessions = [{"date": d, "kind": "strength", "exercises": [
        ex("Squat", "dumbbells on a rack", illustration="Goblet_Squat"),
        ex("Odd", "dumbbells on a rack", illustration="Made_Up")]} for d in days]
    fake = FakeClaude([json.dumps({"message": "x", "sessions": sessions})])
    now = datetime(2026, 11, 13, tzinfo=HK)
    claude = Claude(fake, store, 5.0, now=lambda: now)
    propose(claude, store, "claude-opus-5-5", date(2026, 11, 16),
            profile_path="examples/profile.md", equipment_path="examples/equipment.md",
            illustrations=i)
    saved = store.plan_sessions("2026-11-16", "2026-11-22")
    assert [e.get("illustration") for e in saved[0]["exercises"]] == ["Goblet_Squat", None]
    assert "Goblet_Squat: Goblet Squat" in str(fake.calls[0])
    store.close()


def test_send_album_splits_into_groups_of_ten():
    from gym_coach.telegram import TelegramClient
    calls = []

    def handler(request):
        calls.append(request.url.path.rsplit("/", 1)[1])
        return httpx.Response(200, json={"ok": True, "result": []})

    tg = TelegramClient("TOKEN", 1, client=httpx.Client(transport=httpx.MockTransport(handler)))
    tg.send_album(5, [(b"a", "x")] * 11)
    assert calls == ["sendMediaGroup", "sendPhoto"]
