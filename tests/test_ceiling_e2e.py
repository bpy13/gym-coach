from datetime import datetime

import pytest

from fakes import FakeClaude
from gym_coach.llm import HK, Claude
from gym_coach.router import Router
from gym_coach.store import Store

NOON = datetime(2026, 11, 17, 12, 30, tzinfo=HK)
DAY = "2026-11-17"


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


def test_at_the_ceiling_no_model_call_and_replies_state_the_limit(store):
    store.add_api_call(NOON.isoformat(), "claude-opus-5-5", 1, 1, 5.00)
    fake = FakeClaude()
    router = Router(store, Claude(fake, store, 5.0, now=lambda: NOON),
                    "claude-haiku-5-5", "claude-opus-5-5", now=lambda: NOON,
                    profile_path="examples/profile.md", equipment_path="examples/equipment.md")

    photo_reply = router.handle_photo(b"\xff\xd8fake", None)
    report_reply = router.handle("chest press 35 kg 10 10 8")

    assert fake.calls == []
    assert "limit" in photo_reply and "US$5" in photo_reply
    assert "limit" in report_reply and "US$5" in report_reply
    assert store.meals_on(DAY) == []
    assert "US$5.00 of US$5" in router.handle("/cost")
    assert fake.calls == []
