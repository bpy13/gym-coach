"""Task 15f: fixes from the end-of-run review of Task 15 (the coach chat). Made-up data."""

import copy

import pytest

from fakes import tool_use
from gym_coach import reports
from gym_coach.llm import MAX_TOOL_ROUNDS
from gym_coach.store import Store
from test_coach import DAY, EQUIPMENT, EXS, SUN, log, make, results, saved


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    s.add_plan_session(DAY, "parents", "strength", "approved", EXS)
    s.set(f"flow:{DAY}", "0")
    s.set("chat_id", "5")
    yield s
    s.close()


@pytest.fixture
def equipment(tmp_path):
    path = tmp_path / "equipment.md"
    path.write_text(EQUIPMENT, encoding="utf-8")
    return path


# finding 1: a failure after a tool already changed the records

def _no_retry(reply):
    assert "try again" not in reply.lower()


def test_llm_error_after_a_logged_set_replies_with_what_was_saved(store, equipment):
    rounds = [[log("Low row", (35, 12), (35, 12), (35, 12))]] + [
        [tool_use("show_exercise", {"exercise": "Chest press"})]] * (MAX_TOOL_ROUNDS - 1)
    router, _ = make(store, equipment, rounds)
    reply = router.handle("low row 35 12 12 12")
    _no_retry(reply)
    assert "Low row: 35 kg x 12, 12, 12" in reply and "saved" in reply.lower()
    assert saved(store) == [("Low row", n, 35, 12) for n in (1, 2, 3)]
    assert "LLMError" in router.error


def test_sdk_error_after_a_logged_set_replies_with_what_was_saved(store, equipment):
    router, _ = make(store, equipment, [[log("Low row", (35, 12))],
                                        RuntimeError("overloaded")])
    reply = router.handle("low row 35 12")
    _no_retry(reply)
    assert "Low row: 35 kg x 12" in reply
    assert "RuntimeError: overloaded" in router.error


def test_ceiling_after_a_logged_set_replies_with_what_was_saved(store, equipment):
    # one fake round costs US$0.0002, so the second round finds the US$5 ceiling reached
    store.add_api_call(SUN.isoformat(), "claude-opus-5-5", 1, 1, 4.9999)
    router, fake = make(store, equipment, [[log("Low row", (35, 12))], "Logged."])
    reply = router.handle("low row 35 12")
    _no_retry(reply)
    assert "Low row: 35 kg x 12" in reply and len(fake.calls) == 1
    assert router.error == "monthly ceiling reached"


def test_sdk_error_before_any_tool_says_sorry_and_records_it(store, equipment):
    router, _ = make(store, equipment, [ConnectionError("network down")])
    reply = router.handle("low row 35 12")
    assert reply.startswith("Sorry")
    assert "ConnectionError: network down" in router.error
    assert saved(store) == []


def test_a_card_left_from_an_earlier_message_is_not_sent_with_the_next_reply(store, equipment):
    router, _ = make(store, equipment, ["Hi.", "Nice lunch."])
    router.exercise_to_send = (store.plan_session(DAY), 2)
    router.handle("hello")
    assert router.pop_exercise() is None
    router.exercise_to_send = (store.plan_session(DAY), 2)
    router.handle_photo(b"not a jpeg", "what is this")
    assert router.pop_exercise() is None


# finding 2 and 8: swap and drop never fail after a write; the flow pointer follows

def _swap(name, new="DB fly", gear="Dumbbells on a rack", **extra):
    return tool_use("swap_exercise", {"exercise": name, "new_exercise": new,
                                      "equipment": gear, **extra})


def test_swap_of_an_exercise_without_a_planned_weight_saves_once_and_moves_on(tmp_path,
                                                                              equipment):
    s = Store(tmp_path / "b.db")
    exs = copy.deepcopy(EXS)
    exs[1]["weight_kg"] = None
    s.add_plan_session(DAY, "parents", "strength", "approved", exs)
    s.set(f"flow:{DAY}", "1")
    router, fake = make(s, equipment, [[_swap("Rear delt fly")], "Swapped."])
    router.handle("swap the rear delt")
    [res] = results(fake.calls[1])
    # Task 14o: no weight named when none was given
    assert not res.get("is_error") and "today: 3 x 10-12." in res["content"]
    assert [e["name"] for e in s.plan_session(DAY)["exercises"]] == [
        "Low row", "DB fly", "Seated leg curl", "Chest press"]
    assert s.get(f"flow:{DAY}") == "1" and router.pop_exercise()[1] == 1
    s.close()


def test_swap_after_sets_were_done_keeps_them_and_shows_the_new_exercise(store, equipment):
    store.set(f"flow:{DAY}", "1")
    reports.log_report(store, DAY, [{"exercise": "Rear delt fly", "weight_kg": 30,
                                     "reps": 10}] * 2)
    router, _ = make(store, equipment, [[_swap("Rear delt fly", weight_kg=8)], "Swapped."])
    router.handle("machine is taken, dumbbells for the last one")
    exs = store.plan_session(DAY)["exercises"]
    assert [e["name"] for e in exs] == ["Low row", "Rear delt fly", "DB fly",
                                        "Seated leg curl", "Chest press"]
    assert exs[1]["sets"] == 2 and exs[2]["sets"] == 1 and exs[2]["weight_kg"] == 8
    assert store.get(f"flow:{DAY}") == "2" and router.pop_exercise()[1] == 2
    assert [r["exercise"] for r in store.logged_sets(DAY)] == ["Rear delt fly"] * 2


def test_drop_before_the_shown_exercise_keeps_the_pointer_on_it(store, equipment):
    store.set(f"flow:{DAY}", "3")  # chest press shown
    router, _ = make(store, equipment, [[tool_use("drop_exercise",
                                                  {"exercise": "Rear delt fly"})], "Dropped."])
    router.handle("drop the rear delt today")
    exs = store.plan_session(DAY)["exercises"]
    assert store.get(f"flow:{DAY}") == "2" and exs[2]["name"] == "Chest press"
    assert router.pop_exercise() is None


def test_swap_with_sets_before_the_shown_exercise_keeps_the_pointer_on_it(store, equipment):
    store.set(f"flow:{DAY}", "3")  # chest press shown; the swap adds an exercise before it
    reports.log_report(store, DAY, [{"exercise": "Rear delt fly", "weight_kg": 30,
                                     "reps": 10}])
    router, _ = make(store, equipment, [[_swap("Rear delt fly")], "Swapped."])
    router.handle("do the rest of the rear delts with dumbbells later")
    exs = store.plan_session(DAY)["exercises"]
    assert store.get(f"flow:{DAY}") == "4" and exs[4]["name"] == "Chest press"
    assert router.pop_exercise() is None


# finding 5: "next" after a first set that ended the warm-up

def test_next_after_a_first_set_that_ended_the_warm_up_moves_on(store, equipment):
    store.set(f"warmup:{DAY}", "1")
    router, fake = make(store, equipment, [[log("Low row", (35, 12))],
                                           [tool_use("show_exercise", {"exercise": "next"})],
                                           "Rear delts next."])
    router.handle("warm-up done, low row 35x12, that's enough, next")
    [res] = results(fake.calls[2])
    assert "nothing changed" not in res["content"].lower()
    assert store.get(f"flow:{DAY}") == "1" and router.pop_exercise()[1] == 1


def test_a_second_next_after_the_warm_up_ended_changes_nothing(store, equipment):
    store.set(f"warmup:{DAY}", "1")
    nxt = {"exercise": "next"}
    router, fake = make(store, equipment, [[tool_use("show_exercise", nxt)],
                                           [tool_use("show_exercise", nxt)], "Low row first."])
    router.handle("done")
    [res] = results(fake.calls[2])
    assert "nothing changed" in res["content"].lower()
    assert store.get(f"flow:{DAY}") == "0" and router.pop_exercise()[1] == 0
