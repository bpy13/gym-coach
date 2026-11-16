"""Daily calorie and protein targets. Pure code, no model call."""

import re
from dataclasses import dataclass
from pathlib import Path

ACTIVITY_FACTOR = 1.4
DEFICIT_KCAL = 400
MAX_WEEKLY_LOSS_FRACTION = 0.01  # of body weight
KCAL_PER_KG_FAT = 7700
PROTEIN_G_PER_KG = 1.8


@dataclass(frozen=True)
class Profile:
    age: int
    sex: str  # "male" or "female"
    height_cm: float
    weight_kg: float


@dataclass(frozen=True)
class Targets:
    kcal: int
    protein_g: int
    weight_kg: float


def parse_profile(text: str) -> Profile:
    """Read age, sex, height and weight from the profile's first facts line.

    Expects words like "Age 30, female, 165 cm, 70 kg."
    """
    age = re.search(r"\bage\s+(\d{1,3})\b", text, re.IGNORECASE)
    sex = re.search(r"\b(female|male)\b", text, re.IGNORECASE)
    height = re.search(r"(\d{2,3}(?:\.\d+)?)\s*cm\b", text, re.IGNORECASE)
    weight = re.search(r"(\d{2,3}(?:\.\d+)?)\s*kg\b", text, re.IGNORECASE)
    missing = [
        n for n, m in (("age", age), ("sex", sex), ("height", height), ("weight", weight)) if not m
    ]
    if missing:
        raise ValueError(f"Profile is missing: {', '.join(missing)}")
    return Profile(int(age.group(1)), sex.group(1).lower(), float(height.group(1)),
                   float(weight.group(1)))


def resting_energy(profile: Profile, weight_kg: float | None = None) -> float:
    """Mifflin-St Jeor resting energy in kcal a day."""
    w = profile.weight_kg if weight_kg is None else weight_kg
    base = 10 * w + 6.25 * profile.height_cm - 5 * profile.age
    return base + (5 if profile.sex == "male" else -161)


def compute_targets(profile: Profile, weight_kg: float | None = None) -> Targets:
    """Targets for a given body weight (the profile's weight if none is given)."""
    w = profile.weight_kg if weight_kg is None else weight_kg
    maintenance = resting_energy(profile, w) * ACTIVITY_FACTOR
    max_deficit = MAX_WEEKLY_LOSS_FRACTION * w * KCAL_PER_KG_FAT / 7
    deficit = min(DEFICIT_KCAL, max_deficit)
    return Targets(kcal=int(maintenance - deficit), protein_g=round(PROTEIN_G_PER_KG * w), weight_kg=w)


def latest_weight(store) -> float | None:
    """Weight from the latest `body` row that has one, or None."""
    for row in reversed(store.body_entries()):
        if row["weight_kg"] is not None:
            return float(row["weight_kg"])
    return None


def current_targets(store, profile_path: Path | str) -> Targets:
    """Targets from the latest stored body weight, falling back to the profile's."""
    profile = parse_profile(Path(profile_path).read_text(encoding="utf-8"))
    return compute_targets(profile, latest_weight(store))
