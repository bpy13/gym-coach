from gym_coach.store import Store


def make(tmp_path):
    return Store(tmp_path / "gym.db")


def test_plan_sessions_roundtrip(tmp_path):
    s = make(tmp_path)
    ex = [{"name": "Goblet squat", "equipment": "dumbbell", "sets": 3,
           "rep_low": 8, "rep_high": 12, "weight_kg": 10.0}]
    s.add_plan_session("2026-11-16", "home", "strength", "proposed", ex)
    s.add_plan_session("2026-11-17", "home", "cardio", "proposed", [])
    s.set_plan_status("2026-11-16", "approved")
    got = s.plan_session("2026-11-16")
    assert got["gym"] == "home" and got["status"] == "approved"
    assert got["exercises"] == ex
    assert [r["date"] for r in s.plan_sessions("2026-11-16", "2026-11-17")] == [
        "2026-11-16", "2026-11-17"]
    assert s.plan_session("2030-01-01") is None


def test_logged_sets_and_replace(tmp_path):
    s = make(tmp_path)
    s.add_logged_set("2026-11-16", "Goblet squat", 1, 10.0, 12, "easy")
    s.add_logged_set("2026-11-16", "Goblet squat", 2, 10.0, 10)
    sets = s.logged_sets("2026-11-16")
    assert [(x["set_no"], x["reps"]) for x in sets] == [(1, 12), (2, 10)]
    assert sets[0]["effort"] == "easy"
    s.clear_logged_sets("2026-11-16")
    assert s.logged_sets("2026-11-16") == []


def test_meals_body(tmp_path):
    s = make(tmp_path)
    s.add_meal("2026-11-16T12:00:00", "two eggs", 160, 12.5)
    s.add_meal("2026-11-17T12:00:00", "rice", 300, 6)
    assert len(s.meals_on("2026-11-16")) == 1
    assert s.meals_on("2026-11-16")[0]["kcal"] == 160
    s.add_body("2026-11-16", 70.0, 80.0)
    assert s.body_entries()[0]["waist_cm"] == 80.0


def test_api_calls_cost_since(tmp_path):
    s = make(tmp_path)
    s.add_api_call("2026-11-02T10:00:00", "m", 10, 5, 0.25)
    s.add_api_call("2026-11-20T10:00:00", "m", 10, 5, 0.5)
    s.add_api_call("2026-12-01T10:00:00", "m", 10, 5, 9.0)
    assert s.cost_between("2026-11-01", "2026-12-01") == 0.75


def test_kv(tmp_path):
    s = make(tmp_path)
    assert s.get("offset") is None
    assert s.get("offset", "0") == "0"
    s.set("offset", "5")
    s.set("offset", "6")
    assert s.get("offset") == "6"


def test_reopen_keeps_data(tmp_path):
    s = make(tmp_path)
    s.set("k", "v")
    s.add_meal("2026-11-16T12:00:00", "egg", 80, 6)
    s.close()
    s2 = make(tmp_path)
    assert s2.get("k") == "v"
    assert len(s2.meals_on("2026-11-16")) == 1
