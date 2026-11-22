"""Task 15c: the coach chat with tools. The model (scripted here) calls tools; the tools change
the records and refuse calls that break a hard rule, listing the valid choices. Made-up data."""

import json
from datetime import datetime

import pytest

from fakes import FakeClaude, FakeTelegram, tool_use
from gym_coach import reports
from gym_coach.app import App
from gym_coach.coach import SYSTEM, TOOLS
from gym_coach.llm import HK, Claude
from gym_coach.router import Router
from gym_coach.store import Store
from gym_coach.telegram import Incoming

SUN = datetime(2026, 11, 22, 18, 0, tzinfo=HK)
DAY = "2026-11-22"
EQUIPMENT = """# Equipment (made-up)

## Home gym (weekdays)
- Chest press: seen

## Parents' gym (weekends)
- Chest press: seen
- Lat pulldown with low row (one tower, high bar and low handle): seen
- Leg extension (seated) and lying leg curl, one combined machine: seen
- Rear delt fly machine: seen
- Dumbbells on a rack, 2 to 24 kg.
"""
EXS = [
    {"name": "Low row", "equipment": "lat pulldown with low row (one tower, high bar and low "
     "handle)", "sets": 3, "rep_low": 10, "rep_high": 12, "weight_kg": 35},
    {"name": "Rear delt fly", "equipment": "rear delt fly machine", "sets": 3, "rep_low": 10,
     "rep_high": 12, "weight_kg": 30},
    {"name": "Seated leg curl", "equipment": "leg extension (seated) and lying leg curl",
     "sets": 3, "rep_low": 10, "rep_high": 12, "weight_kg": 25},
    {"name": "Chest press", "equipment": "chest press", "sets": 2, "rep_low": 8, "rep_high": 12,
     "weight_kg": 30},
]
NAMES = [e["name"] for e in EXS]


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


def make(store, equipment, replies, clock=SUN):
    fake = FakeClaude(replies)
    router = Router(store, Claude(fake, store, 5.0, now=lambda: clock), "claude-haiku-5-5",
                    "claude-opus-5-5", now=lambda: clock, profile_path="examples/profile.md",
                    equipment_path=equipment)
    return router, fake


def results(call) -> list[dict]:
    """The tool results sent back to the model in this call (its last user turn)."""
    last = call["messages"][-1]["content"]
    return [b for b in last if isinstance(b, dict) and b.get("type") == "tool_result"]


def prompt(call) -> str:
    content = call["messages"][0]["content"]
    return content if isinstance(content, str) else json.dumps(content)


def log(name, *sets, own=None):
    out = []
    for weight, reps in sets:
        s = {"exercise": name, "weight_kg": weight, "reps": reps}
        if own is not None:
            s["own"] = own
        out.append(s)
    return tool_use("log_sets", {"sets": out})


def saved(store):
    return [(r["exercise"], r["set_no"], r["weight_kg"], r["reps"])
            for r in store.logged_sets(DAY)]


def workout(store):
    return store.get(f"workout:{DAY}") or ""


# the three Sunday conversations

def test_swap_with_a_wrong_machine_name_is_corrected_by_the_model_after_the_refusal(
        store, equipment):
    store.set(f"flow:{DAY}", "2")
    router, fake = make(store, equipment, [
        [tool_use("swap_exercise", {"exercise": "Seated leg curl",
                                    "new_exercise": "Lying leg curl",
                                    "equipment": "leg extension and leg curl"})],
        [tool_use("swap_exercise", {"exercise": "Seated leg curl",
                                    "new_exercise": "Lying leg curl",
                                    "equipment": "Leg extension (seated) and lying leg curl"})],
        "Done, lying leg curl it is. Card coming up.",
    ])
    reply = router.handle("it is a lying leg curl, not seated")
    [refused] = results(fake.calls[1])
    assert refused.get("is_error") is True
    assert "leg extension (seated) and lying leg curl" in refused["content"]
    assert "lat pulldown with low row (one tower, high bar and low handle)" in refused["content"]
    ex = store.plan_session(DAY)["exercises"][2]
    assert ex["name"] == "Lying leg curl"
    assert ex["equipment"] == "leg extension (seated) and lying leg curl"
    assert router.pop_exercise()[1] == 2
    assert reply == "Done, lying leg curl it is. Card coming up."
    assert len(fake.calls) == 3  # no fixed question: one message, one conversation


def test_identical_set_after_a_delivered_reply_is_a_new_set(store, equipment):
    reports.log_report(store, DAY, [{"exercise": "Low row", "weight_kg": 35, "reps": 12}] * 2)
    store.add_chat("2026-11-22T18:07:00+08:00", "in", "35kg x12")
    store.add_chat("2026-11-22T18:07:05+08:00", "out", "Low row: 35 kg x 12, 12. 1 set left.")
    router, fake = make(store, equipment, [[log("Low row", (35, 12))],
                                           "Third set 35 kg x 12, low row done."])
    router.handle("35kg x12")
    assert saved(store)[-1] == ("Low row", 3, 35, 12)
    assert "Bot: Low row: 35 kg x 12, 12. 1 set left." in prompt(fake.calls[0])
    assert "new set" in SYSTEM.lower()
    assert router.pop_exercise()[1] == 1  # low row complete: the rear delt card follows


def test_x12_typo_fixes_the_last_set(store, equipment):
    store.set(f"flow:{DAY}", "1")
    reports.log_report(store, DAY, [{"exercise": "Rear delt fly", "weight_kg": 30, "reps": r}
                                    for r in (12, 12, 13)])
    router, fake = make(store, equipment, [
        [tool_use("fix_set", {"exercise": "Rear delt fly", "set_no": 3, "reps": 12})],
        "Fixed: set 3 is 30 kg x 12."])
    router.handle("X12, typo")
    assert [r["reps"] for r in store.logged_sets(DAY)] == [12, 12, 12]
    [res] = results(fake.calls[1])
    assert "from 30 kg x 13 to 30 kg x 12" in res["content"]
    assert "Rear delt fly set 3" in prompt(fake.calls[0])  # numbered sets in the state


# refusals (acceptance criterion 3)

def test_equipment_not_on_the_gym_list_is_refused_with_the_list(store, equipment):
    router, fake = make(store, equipment, [
        [tool_use("swap_exercise", {"exercise": "Low row", "new_exercise": "Cable row",
                                    "equipment": "dual adjustable cable machine"})], "Hm."])
    router.handle("cable row instead")
    [res] = results(fake.calls[1])
    assert res["is_error"] and "not on the parents gym list" in res["content"]
    assert "- rear delt fly machine" in res["content"]
    assert store.plan_session(DAY)["exercises"] == EXS


@pytest.mark.parametrize("bad", [{"weight_kg": 0, "reps": 10}, {"weight_kg": 35, "reps": 0},
                                 {"weight_kg": -5, "reps": 10}, {"weight_kg": 35, "reps": -1}])
def test_zero_or_negative_numbers_are_refused(store, equipment, bad):
    router, fake = make(store, equipment, [
        [tool_use("log_sets", {"sets": [{"exercise": "Low row", **bad}]}),
         tool_use("fix_set", {"exercise": "Low row", "set_no": 1, **bad}),
         tool_use("set_weight", {"exercise": "Low row", "weight_kg": -1}),
         tool_use("swap_exercise", {"exercise": "Low row", "new_exercise": "DB row",
                                    "equipment": "dumbbells on a rack", "weight_kg": 0})],
        "Hm."])
    reports.log_report(store, DAY, [{"exercise": "Low row", "weight_kg": 35, "reps": 12}])
    router.handle("low row")
    res = results(fake.calls[1])
    assert all(r["is_error"] for r in res)
    assert all("more than 0" in r["content"] for r in res)
    assert saved(store) == [("Low row", 1, 35, 12)]
    assert store.plan_session(DAY)["exercises"] == EXS


@pytest.mark.parametrize("tool,extra", [
    ("log_sets", None), ("fix_set", {"set_no": 1, "reps": 10}), ("remove_set", {"set_no": 1}),
    ("show_exercise", {}), ("swap_exercise", {"new_exercise": "X",
                                              "equipment": "chest press"}),
    ("drop_exercise", {}), ("set_weight", {"weight_kg": 20})])
def test_an_unknown_exercise_name_is_refused_with_todays_names(store, equipment, tool, extra):
    call = (log("Zercher squat", (40, 5)) if extra is None
            else tool_use(tool, {"exercise": "Zercher squat", **extra}))
    reports.log_report(store, DAY, [{"exercise": "Low row", "weight_kg": 35, "reps": 12}])
    router, fake = make(store, equipment, [[call], "Hm."])
    router.handle("zercher squat")
    [res] = results(fake.calls[1])
    assert res["is_error"] and "Zercher squat" in res["content"]
    assert all(n in res["content"] for n in ("Low row", "Rear delt fly"))
    assert saved(store) == [("Low row", 1, 35, 12)]
    assert store.plan_session(DAY)["exercises"] == EXS


def test_the_ceiling_stops_the_coach_call(store, equipment):
    store.add_api_call(SUN.isoformat(), "claude-opus-5-5", 1, 1, 5.0)
    router, fake = make(store, equipment, [])
    assert "US$5 limit" in router.handle("35 12") and fake.calls == []
    assert "US$5 limit" in router.handle_photo(b"\xff\xd8x", "lunch") and fake.calls == []


# each tool's happy path

def test_log_sets_saves_opens_the_workout_and_states_what_is_left(store, equipment):
    router, fake = make(store, equipment, [[log("Low row", (35, 12), (35, 11))], ""])
    reply = router.handle("low row 35 12 11")
    assert saved(store) == [("Low row", 1, 35, 12), ("Low row", 2, 35, 11)]
    assert workout(store).startswith("open|")
    assert reply.startswith("Low row: 35 kg x 12, 11") and "1 set left" in reply  # fallback
    assert json.loads(router.understood)[0]["tool"] == "log_sets"
    assert fake.calls[0]["model"] == "claude-haiku-5-5"
    assert [t["name"] for t in fake.calls[0]["tools"]] == [t["name"] for t in TOOLS]


def test_log_sets_own_exercise_is_added_to_today(store, equipment):
    router, _ = make(store, equipment, [[log("Plate halo", (10, 10), own=True)], "Nice."])
    router.handle("plate halo 10kg 10")
    added = store.plan_session(DAY)["exercises"][-1]
    assert added["name"] == "Plate halo" and added["own"] is True
    assert store.get(f"flow:{DAY}") == "0"


def test_log_sets_far_weight_saves_and_says_to_ask(store, equipment):
    router, fake = make(store, equipment, [[log("Low row", (350, 12))], "350? Typo?"])
    router.handle("low row 350 12")
    [res] = results(fake.calls[1])
    assert "far from" in res["content"] and "typo" in res["content"]
    assert saved(store) == [("Low row", 1, 350, 12)]


def test_log_sets_completing_the_last_exercise_appends_the_stretches(store, equipment):
    store.set(f"flow:{DAY}", "3")
    for e in EXS[:3]:
        reports.log_report(store, DAY, [{"exercise": e["name"], "weight_kg": 20, "reps": 10}]
                           * 3)
    tg = FakeTelegram()
    router, fake = make(store, equipment, [[log("Chest press", (30, 10), (30, 10))],
                                           "Great work, all done."])
    App(tg, router, store).handle(Incoming(1, 5, text="chest press 30 10 10"))
    text = tg.sent[-1][1]
    assert text.startswith("Great work, all done.\n\nSession done.")
    assert "Stretch now" in text and tg.markups[-1]["keyboard"][0][0]["text"] == "Finish session"
    [res] = results(fake.calls[1])
    assert "stretch" in res["content"].lower() and "do not repeat" in res["content"]


def test_fix_set_changes_weight_only(store, equipment):
    reports.log_report(store, DAY, [{"exercise": "Low row", "weight_kg": 35, "reps": 12}])
    router, _ = make(store, equipment, [
        [tool_use("fix_set", {"exercise": "low row", "set_no": 1, "weight_kg": 37.5})], "Ok."])
    router.handle("that was 37.5")
    assert saved(store) == [("Low row", 1, 37.5, 12)]


def test_remove_set_renumbers(store, equipment):
    reports.log_report(store, DAY, [{"exercise": "Low row", "weight_kg": 35, "reps": r}
                                    for r in (12, 11, 10)])
    router, _ = make(store, equipment, [
        [tool_use("remove_set", {"exercise": "Low row", "set_no": 2})], "Removed."])
    router.handle("delete the second low row set")
    assert saved(store) == [("Low row", 1, 35, 12), ("Low row", 2, 35, 10)]


def test_show_exercise_by_name_and_next(store, equipment):
    router, _ = make(store, equipment, [
        [tool_use("show_exercise", {"exercise": "chest press"})], "Chest press next.",
        [tool_use("show_exercise", {"exercise": "next"})], "Moving on."])
    router.handle("can I do chest press now")
    assert store.get(f"flow:{DAY}") == "3" and router.pop_exercise()[1] == 3
    router.handle("next")
    assert router.pop_exercise()[1] == 0  # back to the first open one
    assert workout(store).startswith("open|")


def test_next_after_a_set_that_already_moved_on_changes_nothing(store, equipment):
    # replay of 22 Nov: the third set queued the next card, then the model also called
    # show_exercise "next", which skipped an exercise
    reports.log_report(store, DAY, [{"exercise": "Low row", "weight_kg": 35, "reps": 12}] * 2)
    router, fake = make(store, equipment, [[log("Low row", (35, 12))],
                                           [tool_use("show_exercise", {"exercise": "next"})],
                                           "Low row done. Rear delts next."])
    router.handle("35kg x12")
    assert store.get(f"flow:{DAY}") == "1" and router.pop_exercise()[1] == 1
    [res] = results(fake.calls[2])
    assert "nothing changed" in res["content"].lower()


def test_show_exercise_after_the_warm_up_ends_it(store, equipment):
    store.set(f"warmup:{DAY}", "1")
    router, _ = make(store, equipment, [[tool_use("show_exercise", {"exercise": "next"})],
                                        "Warm-up done, here is the first one."])
    router.handle("done")
    assert store.get(f"warmup:{DAY}") == "" and router.pop_exercise()[1] == 0
    assert store.get(f"flow:{DAY}") == "0"


def test_drop_and_set_weight(store, equipment):
    router, _ = make(store, equipment, [
        [tool_use("set_weight", {"exercise": "Chest press", "weight_kg": 27.5}),
         tool_use("drop_exercise", {"exercise": "Rear delt fly"})], "Done."])
    router.handle("chest press 27.5 today and drop the rear delt")
    exs = store.plan_session(DAY)["exercises"]
    assert [e["name"] for e in exs] == ["Low row", "Seated leg curl", "Chest press"]
    assert exs[2]["weight_kg"] == 27.5


def test_finish_workout_appends_the_summary_and_removes_the_button(store, equipment):
    reports.log_report(store, DAY, [{"exercise": "Low row", "weight_kg": 35, "reps": 12}])
    router, _ = make(store, equipment, [[tool_use("finish_workout", {})], "Good session."])
    router._open(DAY)
    reply = router.handle("end")
    assert reply.startswith("Good session.\n\nWorkout finished. Summary:")
    assert "Low row: 35 kg x 12" in reply and workout(store).startswith("closed|")
    assert router.pop_keyboard() == {"remove_keyboard": True}


def test_skip_today(store, equipment):
    router, _ = make(store, equipment, [[tool_use("skip_today", {})], "Rest well."])
    router.handle("skipping today")
    assert store.plan_session(DAY)["status"] == "skipped"


def test_log_meal_from_text_and_from_the_photo(store, equipment):
    estimate = json.dumps({"meal": True, "what": "rice", "description": "chicken rice",
                           "kcal": 650, "protein_g": 35})
    router, fake = make(store, equipment, [
        [tool_use("log_meal", {"description": "two eggs", "use_photo": False})],
        json.dumps({"description": "two eggs", "kcal": 150, "protein_g": 12}), "Logged.",
        [tool_use("log_meal", {"description": "lunch", "use_photo": True})], estimate,
        "Logged lunch."])
    router.handle("had two eggs")
    router.handle_photo(b"\xff\xd8x", "lunch")
    assert [m["kcal"] for m in store.meals_on(DAY)] == [150, 650]
    assert fake.calls[3]["messages"][0]["content"][0]["type"] == "image"  # coach sees it
    assert fake.calls[4]["messages"][0]["content"][0]["type"] == "image"  # estimate too


def test_a_photo_in_a_workout_is_never_a_meal(store, equipment):
    router, fake = make(store, equipment, [
        [tool_use("log_meal", {"description": "plate", "use_photo": True})], "That's a plate."])
    router._open(DAY)
    router.handle_photo(b"\xff\xd8x", None)
    [res] = results(fake.calls[1])
    assert res["is_error"] and store.meals_on(DAY) == []
    assert fake.calls[0]["messages"][0]["content"][0]["type"] == "image"


def test_correct_meal(store, equipment):
    store.add_meal("2026-11-22T12:00:00+08:00", "rice", 650, 35)
    router, _ = make(store, equipment, [[tool_use("correct_meal", {"protein_g": 40})], "Ok."])
    router.handle("protein was 40")
    [m] = store.meals_on(DAY)
    assert (m["kcal"], m["protein_g"]) == (650, 40)


def test_log_body_jump_needs_confirmation(store, equipment):
    router, fake = make(store, equipment, [
        [tool_use("log_body", {"weight_kg": 81.6, "confirmed": False})], "81.6? Sure?",
        [tool_use("log_body", {"weight_kg": 81.6, "confirmed": True})], "Saved."])
    router.handle("81.6")
    assert store.body_entries() == [] and "ask him" in results(fake.calls[1])[0]["content"]
    router.handle("yes")
    assert [r["weight_kg"] for r in store.body_entries()] == [81.6]


def test_note_plan_change_keeps_a_note_and_writes_no_week(store, equipment):
    router, _ = make(store, equipment, [
        [tool_use("note_plan_change", {"change": "less leg work"})], "Noted."])
    router.handle("less leg work next week")
    assert store.get("pending:plan_change") == "less leg work"
    assert store.plan_sessions("2026-11-23", "2026-12-31") == []


def test_revise_waits_for_the_week_then_proposes(store, equipment):
    week = [{"date": d, "kind": "strength", "exercises": [
        {**EXS[3], "equipment": "Chest press"}]} for d in ("2026-11-24", "2026-11-26", "2026-11-29")]
    router, fake = make(store, equipment, [
        [tool_use("revise_proposed_week", {"change": "more rows"})], "Not yet.",
        [tool_use("revise_proposed_week", {"change": "more rows"})],
        json.dumps({"message": "Here is your week.", "sessions": week}), "New week below."])
    router.handle("more rows next week")
    assert results(fake.calls[1])[0]["is_error"]
    assert "more rows" in store.get("pending:plan_change")
    store.set_plan_status(DAY, "done")
    reply = router.handle("revise it")
    assert "Here is your week." in reply and fake.calls[3]["model"] == "claude-opus-5-5"
    assert store.get("pending:plan_change") == ""


def test_approve_plan(store, equipment):
    store.add_plan_session("2026-11-24", "home", "strength", "proposed", EXS[3:])
    router, _ = make(store, equipment, [[tool_use("approve_plan", {})], "Approved."])
    router.handle("looks good")
    assert store.plan_session("2026-11-24")["status"] == "approved"


# what the model sees and how the reply is built

def test_prompt_has_profile_session_and_one_equipment_item_per_line(store, equipment):
    router, fake = make(store, equipment, ["Rest 90 s."])
    assert router.handle("how long do I rest?") == "Rest 90 s."
    text = prompt(fake.calls[0])
    assert "Profile:" in text and "Low row: 0 of 3 sets logged" in text
    assert "<- shown now" in text and "how long do I rest?" in text
    assert "\n- leg extension (seated) and lying leg curl\n" in text
    assert router.understood == "[]" and workout(store) == ""  # a question opens nothing


def test_empty_final_text_falls_back_to_the_last_tool_result(store, equipment):
    router, _ = make(store, equipment, [[tool_use("skip_today", {})], ""])
    assert router.handle("skip today") == "Skipped today's session."


def test_trace_holds_tool_calls_and_results(store, equipment):
    router, _ = make(store, equipment, [[log("Low row", (35, 12))], "Logged."])
    App(FakeTelegram(), router, store).handle(Incoming(1, 5, text="low row 35 12"))
    [t] = store._rows("SELECT * FROM trace")
    [call] = json.loads(t["understood"])
    assert call["tool"] == "log_sets" and call["input"]["sets"][0]["reps"] == 12
    assert call["result"].startswith("Low row: 35 kg x 12") and len(call["result"]) <= 200


def test_finish_session_button_and_start_stay_local(store, equipment):
    router, fake = make(store, equipment, [])
    router.handle("start")
    assert workout(store).startswith("open|")
    assert "Workout finished." in router.handle("Finish session")
    assert fake.calls == []
