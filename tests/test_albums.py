import io
import json
from datetime import datetime

import httpx
import pytest
from PIL import Image

from fakes import FakeClaude, FakeTelegram
from gym_coach.albums import session_album, shrink
from gym_coach.app import App
from gym_coach.context import equipment_photo_ids, photo_file
from gym_coach.llm import HK, Claude
from gym_coach.messages import proposal_message
from gym_coach.router import Router
from gym_coach.scheduler import Scheduler
from gym_coach.store import Store
from gym_coach.telegram import Incoming, TelegramClient, TelegramError

EQUIPMENT = """# Equipment (made up)

## Home gym (weekdays)

- Chest press: seen (IMG_A1)
- Lat pulldown, fixed arms: seen (IMG_A2)
- Leg extension: seen
- Shoulder press: seen (IMG_MISSING)

## Parents' gym (weekends)

- Chest press: seen (IMG_B1)
"""


def jpeg(w, h, color="red"):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "JPEG")
    return buf.getvalue()


def ex(name, equipment):
    return {"name": name, "equipment": equipment, "sets": 3, "rep_low": 8, "rep_high": 12,
            "weight_kg": 20}


@pytest.fixture
def setup(tmp_path):
    eq = tmp_path / "equipment.md"
    eq.write_text(EQUIPMENT, encoding="utf-8")
    photos = tmp_path / "photos"
    (photos / "home").mkdir(parents=True)
    (photos / "parents").mkdir()
    (photos / "home" / "IMG_A1.jpg").write_bytes(jpeg(3000, 2000))
    (photos / "home" / "IMG_A2.jpg").write_bytes(jpeg(800, 600))
    (photos / "parents" / "IMG_B1.jpg").write_bytes(jpeg(500, 500))
    return eq, photos


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def strength(day="2026-11-17", gym="home", exercises=None):
    return {"date": day, "gym": gym, "kind": "strength", "status": "approved",
            "exercises": exercises or [ex("Press", "Chest press"),
                                       ex("Pulldown", "lat pulldown"),
                                       ex("Leg ext", "leg extension"),
                                       ex("Shoulders", "shoulder press")]}


def test_photo_ids_and_lookup(setup):
    eq, photos = setup
    assert equipment_photo_ids("home", eq) == {
        "chest press": "IMG_A1", "lat pulldown": "IMG_A2", "shoulder press": "IMG_MISSING"}
    assert equipment_photo_ids("parents", eq) == {"chest press": "IMG_B1"}
    assert photo_file("home", "IMG_A1", photos).name == "IMG_A1.jpg"
    assert photo_file("home", "IMG_MISSING", photos) is None


def test_shrink_limits_long_edge():
    out = Image.open(io.BytesIO(shrink(jpeg(3000, 2000))))
    assert max(out.size) == 1280
    small = Image.open(io.BytesIO(shrink(jpeg(300, 200))))
    assert small.size == (300, 200)


def test_album_has_one_photo_per_exercise_and_skips_missing(setup):
    eq, photos = setup
    album = session_album(strength(), eq, photos)
    assert [caption for _, caption in album] == ["Press", "Pulldown"]
    assert max(Image.open(io.BytesIO(album[0][0])).size) == 1280


def test_no_album_on_cardio_day(setup):
    eq, photos = setup
    cardio = {"date": "2026-11-18", "gym": "home", "kind": "cardio", "status": "approved",
              "exercises": []}
    assert session_album(cardio, eq, photos) == []


def test_unreadable_image_skipped(setup):
    eq, photos = setup
    (photos / "home" / "IMG_A1.jpg").write_bytes(b"not an image")
    assert [c for _, c in session_album(strength(), eq, photos)] == ["Pulldown"]


def test_scheduler_sends_album_then_text(store, setup):
    eq, photos = setup
    store.add_plan_session("2026-11-17", "home", "strength", "approved", strength()["exercises"])
    events = []
    sch = Scheduler(store, lambda t: events.append(("text", t)),
                    now=lambda: datetime(2026, 11, 17, 7, 0, tzinfo=HK),
                    album_for=lambda s: session_album(s, eq, photos),
                    send_album=lambda a: events.append(("album", [c for _, c in a])))
    sch.tick()
    assert [e[0] for e in events] == ["album", "text"]
    assert events[0][1] == ["Press", "Pulldown"]
    assert "Leg ext: 3 x 8-12 at 20 kg" in events[1][1]


def test_scheduler_album_failure_still_sends_text(store):
    store.add_plan_session("2026-11-17", "home", "strength", "approved", strength()["exercises"])
    texts = []

    def boom(_):
        raise RuntimeError("no photos")

    Scheduler(store, texts.append, now=lambda: datetime(2026, 11, 17, 7, 0, tzinfo=HK),
              album_for=boom, send_album=lambda a: None).tick()
    assert len(texts) == 1


def test_proposal_message_lists_every_day():
    cardio = {"date": "2026-11-24", "gym": "home", "kind": "cardio", "status": "proposed",
              "exercises": []}
    text = proposal_message("Here is your week.", [strength("2026-11-23"), cardio])
    assert text.startswith("Here is your week.")
    assert "Home gym, Mon 23 Nov: strength" in text
    assert "Leg ext: 3 x 8-12 at 20 kg" in text
    assert "Home gym, Tue 24 Nov: cardio" in text


def test_proposal_sends_album_for_first_session_then_full_text(store, setup):
    eq, photos = setup
    now = datetime(2026, 11, 17, 18, 0, tzinfo=HK)
    days = ("2026-11-23", "2026-11-25", "2026-11-27")
    sessions = [{"date": d, "kind": "strength", "exercises": [ex("Press", "Chest press")]}
                for d in days]
    sessions.append({"date": "2026-11-24", "kind": "cardio", "exercises": []})
    fake = FakeClaude([json.dumps({"message": "Your week.", "sessions": sessions})])
    router = Router(store, Claude(fake, store, 5.0, now=lambda: now), "claude-haiku-5-5", "claude-opus-5-5", now=lambda: now,
                    profile_path="examples/profile.md", equipment_path="examples/equipment.md")
    tg = FakeTelegram()
    app = App(tg, router, store, album_for=lambda s: session_album(s, eq, photos))
    app.handle(Incoming(1, 5, text="/propose"))
    assert len(tg.albums) == 1 and [c for _, c in tg.albums[0][1]] == ["Press"]
    text = tg.sent[0][1]
    assert "Your week." in text and "Press: 3 x 8-12 at 20 kg" in text
    assert "Tue 24 Nov: cardio" in text
    app.handle(Incoming(2, 5, text="/today"))
    assert len(tg.albums) == 1  # only a proposal sends photos


def test_send_album_posts_media_group_and_single_photo():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"ok": True, "result": []})

    tg = TelegramClient("TOKEN", 1, client=httpx.Client(transport=httpx.MockTransport(handler)))
    tg.send_album(5, [(b"a", "One"), (b"b", "Two")])
    tg.send_album(5, [(b"a", "One")])
    tg.send_album(5, [])
    assert [c.url.path.rsplit("/", 1)[1] for c in calls] == ["sendMediaGroup", "sendPhoto"]
    assert b"attach://p1" in calls[0].content and b"Two" in calls[0].content


def test_send_album_error_hides_token():
    def handler(request):
        return httpx.Response(500)

    tg = TelegramClient("TOKEN", 1, client=httpx.Client(transport=httpx.MockTransport(handler)))
    with pytest.raises(TelegramError) as err:
        tg.send_album(5, [(b"a", "One")])
    assert "TOKEN" not in str(err.value)
