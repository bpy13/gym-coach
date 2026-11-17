import json
from datetime import datetime

import pytest

from fakes import FakeClaude, FakeTelegram
from gym_coach.app import App
from gym_coach.llm import HK, Claude
from gym_coach.router import Router
from gym_coach.store import Store
from gym_coach.telegram import Incoming

NOON = datetime(2026, 11, 17, 12, 30, tzinfo=HK)
DAY = "2026-11-17"
JPEG = b"\xff\xd8fake-image-bytes"


def meal(description="chicken rice", kcal=650, protein=35):
    return json.dumps({"description": description, "kcal": kcal, "protein_g": protein})


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def make(store, replies):
    fake = FakeClaude(replies)
    router = Router(store, Claude(fake, store, 5.0, now=lambda: NOON),
                    "claude-haiku-5-5", "claude-opus-5-5", now=lambda: NOON,
                    profile_path="examples/profile.md", equipment_path="examples/equipment.md")
    return router, fake


def test_photo_makes_one_call_with_image_and_one_meal_row(store):
    router, fake = make(store, [meal()])
    reply = router.handle_photo(JPEG, None)
    assert len(fake.calls) == 1
    blocks = fake.calls[0]["messages"][0]["content"]
    assert blocks[0]["type"] == "image"
    rows = store.meals_on(DAY)
    assert [(r["description"], r["kcal"], r["protein_g"]) for r in rows] == [("chicken rice", 650, 35)]
    assert reply.startswith("About 650 kcal, 35 g protein (chicken rice).")
    # example profile: 70 kg -> 1,588 kcal and 126 g protein a day
    assert "Today: 650 of 1,588 kcal, 35 of 126 g protein." in reply
    assert "rough" in reply


def test_running_total_adds_up(store):
    router, _ = make(store, [meal(), meal("eggs", 200, 13)])
    router.handle_photo(JPEG, None)
    reply = router.handle_photo(JPEG, None)
    assert "Today: 850 of 1,588 kcal, 48 of 126 g protein." in reply


def test_caption_goes_to_the_model(store):
    router, fake = make(store, [json.dumps({"intent": "meal"}), meal("half chicken rice", 325, 18)])
    router.handle_photo(JPEG, "half portion")
    blocks = fake.calls[1]["messages"][0]["content"]
    assert "half portion" in blocks[-1]["text"]


def test_text_meal_is_logged_through_the_classifier(store):
    router, fake = make(store, [json.dumps({"intent": "meal"}), meal("eggs and toast", 350, 18)])
    reply = router.handle("had two eggs and toast")
    assert "had two eggs and toast" in fake.calls[1]["messages"][0]["content"][-1]["text"]
    assert reply.startswith("About 350 kcal, 18 g protein (eggs and toast).")
    assert len(store.meals_on(DAY)) == 1


def test_correction_changes_the_last_meal(store):
    router, _ = make(store, [meal("old", 100, 5), meal(), json.dumps(
        {"intent": "meal_correction", "kcal": 400, "protein_g": None})])
    router.handle_photo(JPEG, None)
    router.handle_photo(JPEG, None)
    reply = router.handle("that was 400 kcal")
    rows = store.meals_on(DAY)
    assert [r["kcal"] for r in rows] == [100, 400]
    assert rows[1]["protein_g"] == 35  # protein kept when not given
    assert reply.startswith("Corrected the last meal.") and "Today: 500 of" in reply


def test_correction_without_a_meal(store):
    router, _ = make(store, [json.dumps({"intent": "meal_correction", "kcal": 400})])
    assert "could not tell" in router.handle("that was 400 kcal")


def test_unusable_estimate_stores_nothing(store):
    router, _ = make(store, [json.dumps({"description": "x", "kcal": "lots", "protein_g": 3})])
    assert "Sorry" in router.handle_photo(JPEG, None)
    assert store.meals_on(DAY) == []


def test_photo_through_the_app_writes_no_image_to_disk(store, tmp_path, monkeypatch):
    router, _ = make(store, [meal()])
    tg = FakeTelegram(files={"f1": JPEG})
    work = tmp_path / "cwd"
    work.mkdir()
    monkeypatch.chdir(work)
    before = set(tmp_path.rglob("*"))
    App(tg, router, store).handle(Incoming(1, 5, photo_file_id="f1", caption=None))
    assert tg.sent[0][1].startswith("About 650 kcal")
    assert set(tmp_path.rglob("*")) - before == set()
