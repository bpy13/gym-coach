from datetime import UTC, date, datetime
from pathlib import Path

from gym_coach.context import equipment_for, gym_for, profile_text

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
EQUIPMENT = EXAMPLES / "equipment.md"


def test_weekdays_are_home():
    for day in range(9, 14):  # Mon 2026-11-09 .. Fri 2026-11-13
        assert gym_for(date(2026, 11, day)) == "home"


def test_weekend_is_parents():
    assert gym_for(date(2026, 11, 14)) == "parents"
    assert gym_for(date(2026, 11, 15)) == "parents"


def test_datetime_uses_hong_kong_time():
    # Friday 20:00 UTC is already Saturday 04:00 in Hong Kong.
    assert gym_for(datetime(2026, 11, 13, 20, 0, tzinfo=UTC)) == "parents"
    assert gym_for(datetime(2026, 11, 13, 10, 0, tzinfo=UTC)) == "home"


def test_home_equipment_parsed():
    items = equipment_for("home", EQUIPMENT)
    assert "chest press" in items
    assert "lat pulldown" in items
    assert "dual adjustable cable machine" in items
    assert "leg press" not in items  # under "Not seen"


def test_unsure_items_excluded():
    home = equipment_for("home", EQUIPMENT)
    assert not any("unsure" in i or "stack machine beside" in i for i in home)
    parents = equipment_for("parents", EQUIPMENT)
    assert "rear delt fly machine" not in parents
    assert "seated leg press" in parents
    assert "smith machine with plates" in parents


def test_gyms_are_separate():
    assert "dual adjustable cable machine" not in equipment_for("parents", EQUIPMENT)
    assert "smith machine with plates" not in equipment_for("home", EQUIPMENT)


def test_unknown_gym_rejected():
    import pytest

    with pytest.raises(ValueError):
        equipment_for("moon", EQUIPMENT)


def test_profile_text():
    assert "Goal: build muscle" in profile_text(EXAMPLES / "profile.md")
