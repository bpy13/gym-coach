"""Task 14n: the coach reports past sets exactly (one per set, numbered, with the count), and
his own word on effort beats the rep count. The 17 Nov chest press and the 35 kg x 15
"barely managed" cases follow the 24 Nov chat; the numbers are made up to match."""

from datetime import datetime

import pytest

from fakes import FakeClaude, tool_use
from gym_coach import reports, weights
from gym_coach.coach import SYSTEM, TOOLS
from gym_coach.llm import HK, Claude
from gym_coach.router import Router
from gym_coach.store import Store
from test_14l import EQ, MODEL, PROFILE, did, ex

DAY = "2026-11-24"  # Tuesday, home
LAST = "2026-11-17"
NOW = datetime(2026, 11, 24, 18, 45, tzinfo=HK)
PRESS = "Machine chest press"
THREE = "17 Nov, 3 sets: set 1 21 kg x 15, set 2 28 kg x 12, set 3 28 kg x 15"


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "t.db")
    yield s
    s.close()


@pytest.fixture
def workout(store):
    did(store, LAST, "home", [(PRESS, "chest press", [(21, 15), (28, 12), (28, 15)])])
    store.add_plan_session(DAY, "home", "strength", "approved",
                           [ex(PRESS, 35, "chest press"), ex("Lat pulldown", 42, "lat pulldown")])
    store.set(f"weights:{DAY}", "1")
    store.set(f"flow:{DAY}", "0")
    store.set("chat_id", "5")
    return store


def router_for(store, replies=()):
    fake = FakeClaude(list(replies))
    router = Router(store, Claude(fake, store, 5.0, now=lambda: NOW), "claude-haiku-5-5",
                    MODEL, now=lambda: NOW, profile_path=PROFILE, equipment_path=EQ)
    return router, fake


def prompt_of(fake, i=0):
    content = fake.calls[i]["messages"][0]["content"]
    return content if isinstance(content, str) else content[0]["text"]


def tool_result(fake):
    return str(fake.calls[-1]["messages"][-1]["content"][0]["content"])


def sets(*rows):
    return [{"weight_kg": w, "reps": r, "effort": e} for w, r, e in rows]


# (1) past sets one per set, numbered, with the count

def test_numbered_text_lists_every_set():
    entry = {"date": LAST, "sets": sets((21, 15, None), (28, 12, None), (28, 15, "hard"))}
    assert reports.numbered_text(entry) == THREE + " (hard)"


def test_context_holds_three_numbered_sets_for_17_nov(workout):
    router, fake = router_for(workout, ["On 17 Nov you did three sets."])
    router.handle("I mean how did last session chest press went")
    prompt = prompt_of(fake)
    line = next(ln for ln in prompt.splitlines() if ln.startswith(f"- {PRESS}:"))
    assert f"| last: {THREE}" in line
    assert "28 kg x 12, 15" not in line  # the grouped form the model misread


def test_past_sets_tool_lists_every_set_numbered(workout):
    did(workout, "2026-11-12", "home", [(PRESS, "chest press", [(21, 12), (21, 10)])])
    router, fake = router_for(workout, [[tool_use("past_sets", {"exercise": "machine chest "
                                                                "press"})], "Three sets."])
    router.handle("how did chest press go before?")
    result = tool_result(fake)
    assert THREE in result
    assert "12 Nov, 2 sets: set 1 21 kg x 12, set 2 21 kg x 10" in result


# (2) and (3) what the coach is told

def test_system_text_lists_every_set_and_checks_before_agreeing():
    low = " ".join(SYSTEM.lower().split())
    assert "list every set from the record" in low
    assert "never say a set count" in low
    assert "never agree that the record is different without reading it again" in low
    assert "ask whether to correct it" in low
    assert "first repeat that day's sets from the record" in low
    assert "a bare \"that's a mistake\" or \"wrong\" is not enough" in low


def test_system_text_last_session_means_the_exercise_in_progress():
    low = " ".join(SYSTEM.lower().split())
    assert "\"last session\" or \"last time\" means the exercise shown now" in low


# (4) his own word on effort wins

def test_effort_kind_reads_his_words():
    for word in ("barely", "barely managed", "hard", "struggled", "tough", "heavy",
                 "not easy", "Today is not easy, I barely managed"):
        assert weights.effort_kind(word) == "hard", word
    for word in ("easy", "too light", "light", "felt easy", "not hard"):
        assert weights.effort_kind(word) == "easy", word
    for word in (None, "", "ok", "fine"):
        assert weights.effort_kind(word) is None, word


def test_barely_managed_35_x_15_is_not_too_easy():
    label, why, _ = weights.read_sets(sets((35, 15, "barely managed")), (8, 12))
    assert label == "steady" and why == "you said it was hard"
    assert "hold" in weights.today_text(sets((35, 15, "barely managed")), (8, 12))


def test_his_easy_word_makes_it_too_easy_even_mid_range():
    assert weights.read_sets(sets((30, 10, None), (30, 10, "easy")), (8, 12))[0] == "too easy"


def test_hard_does_not_hide_struggling():
    label, why, _ = weights.read_sets(sets((30, 10, None), (30, 6, "hard")), (8, 12))
    assert (label, why) == ("struggling", "reps fell")


def test_no_word_and_reps_over_the_range_asks_how_it_felt():
    text = weights.today_text(sets((35, 15, None)), (8, 12))
    assert "ask how it felt first" in text and "go up" not in text
    # at the top of the range, not over: the 14m rule stands
    assert "go up one step" in weights.today_text(sets((35, 12, None)), (8, 12))


def test_log_sets_saves_his_effort_and_the_context_follows_it(workout):
    router, _ = router_for(workout, [
        [tool_use("log_sets", {"sets": [{"exercise": PRESS, "weight_kg": 35, "reps": 15,
                                         "effort": "barely managed"}]})],
        "Good fight. Hold 35 kg.", "ok"])
    router.handle("35kg x15 done, barely managed")
    row = workout.logged_sets(DAY)[0]
    assert (row["weight_kg"], row["reps"], row["effort"]) == (35, 15, "barely managed")
    ctx = router.context(DAY)
    assert "today so far: steady (you said it was hard): hold the weight" in ctx
    assert "too easy" not in next(ln for ln in ctx.splitlines() if ln.startswith(f"- {PRESS}"))


def test_fix_set_adds_his_effort_word_later(workout):
    reports.log_report(workout, DAY, [{"exercise": PRESS, "weight_kg": 35, "reps": 15}])
    router, fake = router_for(workout, [
        [tool_use("fix_set", {"exercise": PRESS, "set_no": 1, "effort": "barely managed"})],
        "Noted, that was a grind. Hold 35."])
    router.handle("Today is not easy, I barely managed, will probably only do 12")
    assert workout.logged_sets(DAY)[0]["effort"] == "barely managed"
    assert "barely managed" in tool_result(fake)


def test_saved_effort_feeds_the_next_session(store):
    did(store, LAST, "home", [(PRESS, "chest press", [(35, 15)])])
    store._run("UPDATE logged_sets SET effort='barely' WHERE date=?", (LAST,))
    got = weights.History(store, DAY).weight_for(ex(PRESS, 30, "chest press"), "home")
    assert got["label"] == "steady" and got["weight_kg"] == 35
    assert got["note"].startswith("again, you said it was hard last time: ")


def test_effort_tools_are_described():
    fix = next(t for t in TOOLS if t["name"] == "fix_set")
    assert "effort" in fix["input_schema"]["properties"]
    low = " ".join(SYSTEM.lower().split())
    assert "his own word on effort wins" in low


# (5) correct a set of an earlier day

def test_fix_past_set_changes_one_set_and_states_old_and_new(workout):
    router, fake = router_for(workout, [
        [tool_use("fix_past_set", {"date": LAST, "exercise": "machine chest press",
                                   "set_no": 2, "weight_kg": 28, "reps": 10})], "Fixed."])
    router.handle("17 Nov set 2 of chest press was 10 reps, please fix")
    rows = workout.logged_sets(LAST)
    assert [(r["set_no"], r["weight_kg"], r["reps"]) for r in rows] == [
        (1, 21, 15), (2, 28, 10), (3, 28, 15)]
    result = tool_result(fake)
    assert "set 2 was 28 kg x 12, now 28 kg x 10" in result
    assert "17 Nov, 3 sets: set 1 21 kg x 15, set 2 28 kg x 10, set 3 28 kg x 15" in result


def test_fix_past_set_adds_and_removes(workout):
    router, fake = router_for(workout, [
        [tool_use("fix_past_set", {"date": LAST, "exercise": PRESS, "action": "add",
                                   "set_no": 1, "weight_kg": 14, "reps": 15})], "Added."])
    router.handle("I also did 14 x 15 first on 17 Nov")
    rows = workout.logged_sets(LAST)
    assert [(r["set_no"], r["weight_kg"], r["reps"]) for r in rows] == [
        (1, 14, 15), (2, 21, 15), (3, 28, 12), (4, 28, 15)]
    assert "added set 1: 14 kg x 15" in tool_result(fake)
    router, fake = router_for(workout, [
        [tool_use("fix_past_set", {"date": LAST, "exercise": PRESS, "action": "remove",
                                   "set_no": 1})], "Removed."])
    router.handle("no, remove that one")
    assert [(r["set_no"], r["weight_kg"]) for r in workout.logged_sets(LAST)] == [
        (1, 21), (2, 28), (3, 28)]
    assert "removed set 1 (was 14 kg x 15)" in tool_result(fake)


def test_fix_past_set_refuses_today_and_unknown_sets(workout):
    router, fake = router_for(workout, [
        [tool_use("fix_past_set", {"date": DAY, "exercise": PRESS, "set_no": 1, "reps": 9})],
        [tool_use("fix_past_set", {"date": LAST, "exercise": PRESS, "set_no": 7, "reps": 9})],
        [tool_use("fix_past_set", {"date": LAST, "exercise": "Squat", "set_no": 1,
                                   "reps": 9})], "Done."])
    router.handle("fix it")
    texts = [str(m["content"]) for m in fake.calls[-1]["messages"] if m["role"] == "user"]
    joined = " ".join(texts)
    assert "fix_set" in joined  # today goes through fix_set
    assert "sets 1 to 3" in joined
    assert PRESS in joined  # what was logged that day
    assert [r["reps"] for r in workout.logged_sets(LAST)] == [15, 12, 15]
