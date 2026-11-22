import io
import json
from datetime import date, datetime

import httpx
import pytest
from PIL import Image

from fakes import FakeClaude
from gym_coach.albums import session_parts
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
    assert cue == "Hold one dumbbell at your chest."


def test_cue_cut_at_word_end_to_60_chars_one_line(tmp_path):
    long = "Stand with your feet shoulder width apart and\nhold the bar low across your upper back. Then lift."
    cat = [{"id": "X", "name": "X", "equipment": "barbell", "level": "beginner",
            "category": "strength", "images": [], "instructions": [long]}]
    i = Illustrations(tmp_path / "c", http_get=lambda url: json.dumps(cat).encode())
    cue = i.cue("X")
    assert cue == "Stand with your feet shoulder width apart and hold the bar..."
    assert len(cue) <= 63 and chr(10) not in cue


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


def test_exercise_message_has_machine_photo_and_two_illustrations_under_one_caption(ill, gym_files):
    i, _ = ill
    eq, photos = gym_files
    session = {"date": "2026-11-17", "gym": "home", "kind": "strength", "exercises": [
        ex("Chest press", "chest press"),
        ex("Goblet squat", "dumbbells on a rack", illustration="Goblet_Squat"),
        ex("Mystery", "dumbbells on a rack", illustration="Not_In_Db"),
        ex("Plain", "dumbbells on a rack")]}
    parts = session_parts(session, eq, photos, illustrations=i, show_tip=True)
    assert len(parts) == 4 + 2
    body = parts[1:-1]
    assert [len(imgs) for _, imgs in body] == [1, 2, 0, 0]
    assert body[0][0] == "Chest press: 3 x 8-12 at 10 kg"
    first, cue = body[1][0].split(chr(10), 1)
    assert first == "Goblet squat: 3 x 8-12 at 10 kg" and cue.startswith("Hold one dumbbell")


def test_machine_with_illustration_gets_photo_and_illustration(ill, gym_files):
    i, _ = ill
    eq, photos = gym_files
    session = {"date": "2026-11-17", "gym": "home", "kind": "strength", "exercises": [
        ex("Chest press", "chest press", illustration="Goblet_Squat")]}
    (_, imgs), = session_parts(session, eq, photos, illustrations=i)[1:-1]
    assert len(imgs) == 3


def test_parts_without_illustrations_still_send_machine_photos(gym_files):
    eq, photos = gym_files
    session = {"date": "2026-11-17", "gym": "home", "kind": "strength", "exercises": [
        ex("Squat", "dumbbells on a rack", illustration="Goblet_Squat")]}
    parts = session_parts(session, eq, photos)
    assert [len(i) for _, i in parts] == [0, 0, 0]  # text only; the exercise is not lost


def test_parts_survive_unreachable_images(gym_files, tmp_path):
    eq, photos = gym_files
    down = Illustrations(tmp_path / "d", http_get=Net(fail=True))
    session = {"date": "2026-11-17", "gym": "home", "kind": "strength", "exercises": [
        ex("Squat", "dumbbells on a rack", illustration="Goblet_Squat")]}
    parts = session_parts(session, eq, photos, illustrations=down)
    assert len(parts) == 3 and parts[1][1] == []


def test_proposal_keeps_only_listed_illustration_ids(ill, tmp_path):
    i, _ = ill
    store = Store(tmp_path / "t.db")
    days = ("2026-11-17", "2026-11-19", "2026-11-22")
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


def _propose(ill, tmp_path, exercises, replies=()):
    i, _ = ill
    store = Store(tmp_path / "t.db")
    days = ("2026-11-17", "2026-11-19", "2026-11-22")
    # Sunday is the parents' gym, which has no cable machine: keep cable exercises on home days
    sessions = [{"date": d, "kind": "strength",
                 "exercises": exercises if d != "2026-11-22" else
                 [e for e in exercises if "cable" not in e["equipment"]] or exercises}
                for d in days]
    fake = FakeClaude([json.dumps({"message": "x", "sessions": sessions}), *replies])
    now = datetime(2026, 11, 13, tzinfo=HK)
    claude = Claude(fake, store, 5.0, now=lambda: now)
    propose(claude, store, "claude-opus-5-5", date(2026, 11, 16),
            profile_path="examples/profile.md", equipment_path="examples/equipment.md",
            illustrations=i, photos_dir=tmp_path / "no-photos")
    saved = store.plan_sessions("2026-11-16", "2026-11-22")
    store.close()
    return fake, saved


def test_proposal_without_ids_gets_them_by_name_without_asking(ill, tmp_path):
    fake, saved = _propose(ill, tmp_path, [
        ex("Goblet Squats", "dumbbells on a rack"),
        ex("cable row", "dual adjustable cable machine")])
    assert [e.get("illustration") for e in saved[0]["exercises"]] == ["Goblet_Squat", "Cable_Row"]
    assert len(fake.calls) == 1


def test_unmatched_exercise_asks_model_once_for_id_or_replacement(ill, tmp_path):
    reply = json.dumps({"fixes": [
        {"n": 0, "illustration": "Goblet_Squat"},
        {"n": 1, "replace": {"name": "Cable Row", "equipment": "dual adjustable cable machine",
                             "illustration": "Cable_Row"}},
        {"n": 2, "illustration": "Made_Up"}]})
    fake, saved = _propose(ill, tmp_path, [
        ex("Front loaded knee bend", "dumbbells on a rack"),
        ex("Pull thing", "dual adjustable cable machine"),
        ex("Odd", "dumbbells on a rack")], [reply])
    got = saved[0]["exercises"]
    assert [e.get("illustration") for e in got] == ["Goblet_Squat", "Cable_Row", None]
    assert got[1]["name"] == "Cable Row" and got[1]["sets"] == 3
    assert len(fake.calls) == 2


def test_machine_with_photo_needs_no_illustration(ill, tmp_path):
    i, _ = ill
    from gym_coach.planner import ensure_pictures
    eq, photos = tmp_path / "eq.md", tmp_path / "photos" / "home"
    eq.write_text(EQUIPMENT, encoding="utf-8")
    photos.mkdir(parents=True)
    (photos / "IMG_A1.jpg").write_bytes(jpeg())
    sessions = [{"date": "d", "gym": "home", "kind": "strength", "exercises": [
        ex("Chest press", "chest press")]}]
    left = ensure_pictures(sessions, i, {"home": {}, "parents": {}},
                           {"home": {"chest press"}, "parents": set()},
                           equipment_path=eq, photos_dir=tmp_path / "photos")
    assert left == [] and "illustration" not in sessions[0]["exercises"][0]  # none in catalogue


def test_match_ignores_equipment_words_and_extra_detail(ill):
    i, _ = ill
    allowed = i.allowed({"dumbbells on a rack", "dual adjustable cable machine"})
    assert i.match("Dumbbell goblet squat", "dumbbells on a rack", allowed) == "Goblet_Squat"
    assert i.match("Goblet squat at the wall", "dumbbells on a rack", allowed) == "Goblet_Squat"
    assert i.match("Goblet squat", "dual adjustable cable machine", allowed) is None
    assert i.match("Squat", "dumbbells on a rack", allowed) is None


def test_machine_exercises_match_machine_entries(tmp_path):
    cat = [{"id": "Leg_Press", "name": "Leg Press", "equipment": "machine", "level": "intermediate",
            "category": "strength", "images": [], "instructions": []},
           {"id": "Leg_Ext", "name": "Leg Extensions", "equipment": "machine",
            "level": "beginner", "category": "strength", "images": [], "instructions": []}]
    i = Illustrations(tmp_path / "m", http_get=lambda url: json.dumps(cat).encode())
    assert i.allowed({"leg press"}) == {}
    pool = i.allowed({"leg press"}, machines=True)
    assert set(pool) == {"Leg_Press", "Leg_Ext"}
    assert i.match("Leg extension", "leg extension", pool) == "Leg_Ext"
    assert i.match("Seated leg press", "seated leg press", pool) == "Leg_Press"
    assert i.fits("Leg_Press", "leg press") and not i.fits("Leg_Press", "dumbbells on a rack")


def test_match_needs_the_same_body_position(tmp_path):
    cat = [{"id": "Lat_Raise_Lying", "name": "Lateral Raise - Lying on Incline Bench",
            "equipment": "dumbbell", "level": "beginner", "category": "strength",
            "images": [], "instructions": []},
           {"id": "Inc_Press", "name": "Incline Dumbbell Press", "equipment": "dumbbell",
            "level": "beginner", "category": "strength", "images": [], "instructions": []},
           {"id": "Seated_Curl", "name": "Seated Dumbbell Curl", "equipment": "dumbbell",
            "level": "beginner", "category": "strength", "images": [], "instructions": []}]
    i = Illustrations(tmp_path / "p", http_get=lambda url: json.dumps(cat).encode())
    pool = i.allowed({"dumbbells"})
    assert i.match("Dumbbell lateral raise", "dumbbells", pool) is None
    assert i.match("Dumbbell press", "dumbbells", pool) is None
    assert i.match("Incline dumbbell press", "dumbbells", pool) == "Inc_Press"
    assert i.match("Seated curl", "dumbbells", pool) == "Seated_Curl"
    assert i.match("Standing dumbbell curl", "dumbbells", pool) is None
    assert i.match("Lying dumbbell curl", "dumbbells", pool) is None


def test_machine_exercise_with_photo_gets_an_illustration_by_name(tmp_path):
    from gym_coach.planner import ensure_pictures
    cat = [{"id": "Leg_Ext", "name": "Leg Extensions", "equipment": "machine",
            "level": "beginner", "category": "strength", "images": [], "instructions": []}]
    i = Illustrations(tmp_path / "m", http_get=lambda url: json.dumps(cat).encode())
    eq, photos = tmp_path / "eq.md", tmp_path / "photos" / "home"
    eq.write_text(EQUIPMENT.replace("Chest press", "Leg extension"), encoding="utf-8")
    photos.mkdir(parents=True)
    (photos / "IMG_A1.jpg").write_bytes(jpeg())
    sessions = [{"date": "d", "gym": "home", "kind": "strength", "exercises": [
        ex("Leg extension", "leg extension"), ex("Odd machine", "leg extension")]}]
    left = ensure_pictures(sessions, i, {"home": {}, "parents": {}},
                           {"home": {"leg extension"}, "parents": set()},
                           equipment_path=eq, photos_dir=tmp_path / "photos")
    assert left == []  # both have the machine photo
    assert [e.get("illustration") for e in sessions[0]["exercises"]] == ["Leg_Ext", None]


def test_caption_has_one_tip_line_by_default(ill, gym_files):
    i, _ = ill
    eq, photos = gym_files
    session = {"date": "2026-11-17", "gym": "home", "kind": "strength", "exercises": [
        ex("Goblet squat", "dumbbells on a rack", illustration="Goblet_Squat")]}
    (caption, imgs), = session_parts(session, eq, photos, illustrations=i)[1:-1]
    assert caption == "Goblet squat: 3 x 8-12 at 10 kg" + chr(10) + "Hold one dumbbell at your chest."
    assert len(imgs) == 2
    (caption, _), = session_parts(session, eq, photos, illustrations=i, show_tip=False)[1:-1]
    assert caption == "Goblet squat: 3 x 8-12 at 10 kg"


def test_pulldown_and_low_row_towers_use_the_cable_pictures(tmp_path):
    """Task 14f: the catalogue files lat pulldowns and low rows under cable."""
    def entry(i, name, level="beginner", equipment="cable"):
        return {"id": i, "name": name, "equipment": equipment, "level": level,
                "category": "strength", "images": [], "instructions": []}
    cat = [entry("Close_Front", "Close-Grip Front Lat Pulldown"),
           entry("One_Arm", "One Arm Lat Pulldown"),
           entry("Wide", "Wide-Grip Lat Pulldown"),
           entry("Seated_Rows", "Seated Cable Rows"),
           entry("Low_Neck", "Low Pulley Row To Neck"),
           entry("Iso_Row", "Leverage Iso Row", equipment="machine")]
    i = Illustrations(tmp_path / "c", http_get=lambda url: json.dumps(cat).encode())
    pool = i.allowed({"dual adjustable cable machine", "lat pulldown"}, machines=True)
    assert i.match("Lat pulldown", "lat pulldown", pool) == "Wide"
    assert i.match("Seated low row", "lat pulldown with low row (one tower, high bar and low handle)", pool) == "Seated_Rows"
    assert i.fits("Wide", "lat pulldown", "Lat pulldown")
    assert i.fits("Iso_Row", "lat pulldown with low row")  # still a machine too
    assert not i.fits("Wide", "chest press")


def test_lying_leg_curl_matches_the_combined_machine(tmp_path):
    """Task 15a: the parents' combined machine is a seated extension with a lying curl."""
    def entry(i, name):
        return {"id": i, "name": name, "equipment": "machine", "level": "beginner",
                "category": "strength", "images": [], "instructions": []}
    cat = [entry("Lying_Leg_Curls", "Lying Leg Curls"), entry("Seated_Leg_Curl", "Seated Leg Curl"),
           entry("Leg_Extensions", "Leg Extensions")]
    i = Illustrations(tmp_path / "c", http_get=lambda url: json.dumps(cat).encode())
    pool = i.allowed({"x"}, machines=True)
    machine = "leg extension (seated) and lying leg curl"
    assert i.match("Lying leg curl", machine, pool) == "Lying_Leg_Curls"
