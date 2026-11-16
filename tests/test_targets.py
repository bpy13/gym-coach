from pathlib import Path

import pytest

from gym_coach.store import Store
from gym_coach.targets import (
    KCAL_PER_KG_FAT,
    Profile,
    compute_targets,
    current_targets,
    parse_profile,
    resting_energy,
)

PROFILE = Path(__file__).resolve().parent.parent / "examples" / "profile.md"


def example() -> Profile:
    return parse_profile(PROFILE.read_text(encoding="utf-8"))


def test_parse_example_profile():
    assert example() == Profile(30, "female", 165.0, 70.0)


def test_parse_missing_field():
    with pytest.raises(ValueError, match="height"):
        parse_profile("Age 30, female, 70 kg.")


def test_formula_on_example_profile():
    p = example()
    assert resting_energy(p) == pytest.approx(10 * 70 + 6.25 * 165 - 150 - 161)
    t = compute_targets(p)
    assert t.kcal == int(resting_energy(p) * 1.4 - 400)
    assert t.protein_g == 126  # 1.8 g/kg * 70


def test_male_offset():
    m = Profile(30, "male", 165.0, 70.0)
    assert resting_energy(m) - resting_energy(example()) == 166


def test_weekly_loss_never_over_one_percent():
    for w in (40, 50, 70, 90, 120):
        p = Profile(30, "female", 165.0, float(w))
        t = compute_targets(p)
        deficit = resting_energy(p) * 1.4 - t.kcal
        assert deficit * 7 / KCAL_PER_KG_FAT <= 0.01 * w + 1e-3


def test_deficit_capped_for_light_body():
    p = Profile(30, "female", 150.0, 30.0)  # 1% rule allows only about 330 kcal
    t = compute_targets(p)
    assert resting_energy(p) * 1.4 - t.kcal < 400


def test_targets_recompute_with_new_weight(tmp_path):
    store = Store(tmp_path / "t.db")
    before = current_targets(store, PROFILE)
    assert before.weight_kg == 70.0
    store.add_body("2026-11-16", 80.0, 90.0)
    after = current_targets(store, PROFILE)
    assert after.weight_kg == 80.0
    assert after.protein_g == 144
    assert after.kcal > before.kcal
    store.add_body("2026-11-23", None, 89.0)  # waist only: weight stays 80
    assert current_targets(store, PROFILE).weight_kg == 80.0
    store.close()
