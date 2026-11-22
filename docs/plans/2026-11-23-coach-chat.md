# Plan: a coach chat that talks like a real gym instructor (Task 15)

Approved by Brian on 2026-11-23 ("Go"). Built by helpers from the main session, not the
orchestrator.

## Goal
Talking to the bot feels like talking to a real gym instructor (Brian, 2026-11-23: "I need
speaking to the bot feels like speaking to real gym instructor"). Today the model only sorts
each message into one of about 14 labels and Python writes the reply from fixed text. When
the label is off, the bot cannot recover. Sunday 22 Nov showed three failures:
- 18:16–18:17: the bot asked "Which machine or weights at the parents gym do you want to use
  instead of Seated leg curl?" four times in a row. The model sent a machine name that was not
  exactly on the gym list, and the code only re-sent its fixed question.
- 18:09 (#140): his real third set "35kg x12" got "Already logged, nothing added".
- 18:02 (#130): "X12, typo" (the last rear delt set was 12, not 13) changed nothing.

Two causes sit under the swap loop besides the design:
- The equipment-list reader cuts a name at the first comma even inside brackets. The parents'
  low row is stored as `lat pulldown with low row (one tower`. In the comma-joined list the
  model sees, it runs into the next item, `leg extension and leg curl`, which is the blend the
  model sent.
- The parents' combined machine is a seated leg extension with a lying leg curl (Brian, 22 Nov
  chat: "it is a lying leg curl / seated leg extension, which you have mistakenly identified as
  seated leg curl"). The planner names it a seated leg curl, and next Sunday's proposed plan
  (29 Nov) repeats it.

## Approach
- One model call per message leads the conversation, with tools. Haiku 5.5 gets the coach's
  instructions, the profile, today's session with the sets logged, that gym's equipment list,
  the chat (the whole open workout, else today's last 12 lines) and his new message (and photo).
  It calls tools to change records, reads each tool's result, and writes the reply itself.
- Code still enforces every hard rule inside the tools: equipment must be on that day's gym
  list, numbers must be positive, exercise names must be in today's session (or added as his
  own exercise). A refused tool call returns the reason and the valid choices to the model,
  so the model fixes its own call instead of the bot repeating a fixed question.
- Code still sends the structured messages: the 07:00 session list and warm-up, each exercise
  card with its pictures, the stretch list, the "Finish session" button and the summary.
- Slash commands (`/start`, `/today`, `/propose`, `/progress`, `/cost`) and the "Finish
  session" button stay local. Everything else goes to the model.
- The label-sorting call, its fixed replies, the "repeat" detection, the missing-sets check
  call and the "yes" follow-ups are removed.

## Constraints (copied from `docs/decisions.md`)
- "Haiku 5.5 (`claude-haiku-5-5`) reads meal photos and his session reports." Prices per
  million tokens in/out: Haiku 5.5 US$0.10/US$0.50.
- "with a hard ceiling of US$5 a month. The runs stop calling the AI once the month's cost
  reaches it."
- "After each report the bot repeats what it logged ... He corrects it by replying. Reason:
  free-text parsing can misread a number."
- "Code never trusts the model for equipment" (plan 2026-11-13, Approach).
- "The bot states that it gives general fitness guidance, not medical advice."
- "during a strength session the bot shows one exercise at a time; the next one comes as he
  reports his progress, so he reads it while resting" (Brian, 2026-11-16).
- "each exercise is one Telegram message holding the machine photo, the illustration and the
  task" (Brian, 2026-11-16).
- "Messages are in English; weights in kg."
- "all personal data is git-ignored". `docs/` is public: no age, weight, address or building
  name there. Tests use made-up data only.
- Task 14j (built, Brian's spec): warm-up after the 07:00 list; stretches after the last
  exercise; a "Finish session" button that closes the workout.

## Acceptance criteria
1. Replaying Sunday 22 Nov's messages from Brian through the new bot (real Haiku calls, on a
   copy of the database): no question is sent twice in a row; the third "35kg x12" is logged as
   low row set 3; "X12, typo" changes rear delt set 3 from 13 to 12; the swap to a lying leg
   curl succeeds within his first two messages about it.
2. During a workout every reply except the structured messages listed in Approach is written
   by the model, and states the numbers it logged when it logged any.
3. Each hard rule has a test that shows the tool refusing a bad call and returning the valid
   choices: equipment not on the gym list, a weight or reps of zero or less, an unknown
   exercise name. The monthly ceiling still stops every model call.
4. The equipment list reads `lat pulldown with low row (one tower, high bar and low handle)`
   as one name. Stored sessions that carry the broken name are updated. The parents' combined
   machine is a seated leg extension with a lying leg curl in the list, in the 29 Nov proposed
   session and in its picture.
5. The median cost per message in the replay is under US$0.005.
6. Brian reads the replay transcript and says it sounds like a gym instructor (checkpoint).
7. The live bot runs the new code and its log shows a clean start.

## Shared resources
- `data/gym.db`: the live bot writes to it. Only Task 15a migrates it, after a copy to
  `data/gym.db.bak-15a`. The replay (Task 15d) uses a copy in the scratchpad, never the live
  file. Tests use temporary databases.
- `data/equipment.md`: personal and git-ignored; only Task 15a edits it.
- `src/gym_coach/router.py` and the router tests: only Task 15c.
- Real API calls: only Task 15d (estimated under US$0.20).

## Phase 1 – Equipment names (sonnet)

- [x] **Task 15a: equipment names read whole; the combined machine is a lying leg curl** `[parallel-ok]`
  - Files: modify `src/gym_coach/context.py` (`_item_name`), `tests/test_context.py`,
    `tests/test_illustrations.py` (the `"lat pulldown with low row (one tower"` fixture
    string), `data/equipment.md` (not committed); create
    `scripts/migrate_equipment_names.py` (run once on `data/gym.db`).
  - Done when: a new test in `tests/test_context.py` shows `"Lat pulldown with low row (one
    tower, high bar and low handle): seen (IMG_1)"` reads as `"lat pulldown with low row (one
    tower, high bar and low handle)"`; a planner or illustration test shows "Lying leg curl"
    on `"leg extension (seated) and lying leg curl"` matches `Lying_Leg_Curls`; the migration
    script prints the rows it changed; afterwards no `plan_sessions` row contains `(one
    tower"` and the 29 Nov session shows "Lying leg curl" with illustration
    `Lying_Leg_Curls`; full tests and ruff pass.
  - Notes: `_item_name` splits at the first `:`, `,` or `.` outside brackets. In
    `data/equipment.md` change only the parents' line to `- Leg extension (seated) and lying
    leg curl, one combined machine: seen (IMG_20261025_173328492)`; keep everything else.
    The migration copies `data/gym.db` to `data/gym.db.bak-15a` first, then in every
    `plan_sessions.exercises` entry replaces equipment `lat pulldown with low row (one tower`
    with the full name and `leg extension and leg curl` with `leg extension (seated) and lying
    leg curl`; an exercise on that machine whose name says "leg curl" becomes "Lying leg curl"
    with illustration `Lying_Leg_Curls`. Past days keep their exercise names (logged sets
    point at them); only the equipment string changes there. The script is idempotent.

## Phase 2 – The model leads the chat (opus)

- [x] **Task 15b: a tool-use call in the model wrapper** (opus)
  - Files: modify `src/gym_coach/llm.py`, `tests/test_llm.py`, `tests/fakes.py`.
  - Done when: tests show `Claude.converse(...)` runs a tool loop with a fake client: it
    calls the given Python handler for each `tool_use` block, sends the results back, stops at
    the first reply with no tool call, records cost for every round, raises `CeilingReached`
    before any round once the month is at the ceiling, adds each round to `trace`, and stops
    after 6 rounds with `LLMError`; full tests and ruff pass.
  - Notes: signature `converse(model, system, messages, tools, run_tool, jpeg=None) -> str`.
    `tools` are Anthropic tool definitions; `run_tool(name, input) -> str` returns the text
    of the tool result; an exception inside `run_tool` becomes an `is_error` result with its
    message, never a crash. `jpeg` goes into the first user message. Returns the final text.
    `tests/fakes.py` gains a fake client that plays a scripted list of responses (tool calls,
    then text).

- [x] **Task 15c: the coach chat with tools replaces the sorting call** (opus) needs: Task 15b
  - Files: create `src/gym_coach/coach.py`; modify `src/gym_coach/router.py`,
    `src/gym_coach/app.py` (trace of tool calls only); rewrite the tests that drive the
    sorting call: `tests/test_router.py`, `tests/test_14h.py`, `tests/test_14i.py`,
    `tests/test_14j.py`, `tests/test_session_fixes.py`, `tests/test_flow.py`; create
    `tests/test_coach.py`.
  - Done when: `tests/test_coach.py` covers each tool's happy path and each refusal in
    acceptance criterion 3, and three scripted conversations from Sunday: a swap with a wrong
    machine name that the model corrects after the refusal; a repeated identical set after a
    delivered reply logged as a new set; "X12, typo" fixing the last set. `grep -n
    "CLASSIFY_SYSTEM\|CHECK_SYSTEM\|_repeats_undelivered\|SAME_AGAIN"
    src/gym_coach/router.py` prints nothing. Full tests and ruff pass.
  - Notes:
    - Tools (names fixed): `log_sets(sets: [{exercise, weight_kg, reps, effort?, own?}])`,
      `fix_set(exercise, set_no, weight_kg?, reps?)`, `remove_set(exercise, set_no)`,
      `show_exercise(exercise)` (also ends the warm-up; "next" means the next open one),
      `swap_exercise(exercise, new_exercise, equipment, weight_kg?)`,
      `drop_exercise(exercise)`, `set_weight(exercise, weight_kg)`, `finish_workout()`,
      `skip_today()`, `log_meal(description, use_photo)`, `correct_meal(kcal?, protein_g?)`,
      `log_body(weight_kg, waist_cm?, confirmed)`, `note_plan_change(change)`,
      `revise_proposed_week(change)`, `approve_plan()`.
    - Each tool returns plain text: what changed, today's log line for that exercise, sets
      left, and what the code queued (the next exercise card, the stretch list and button).
      A weight outside 0.5–1.5 times the last set or plan returns "far from ... ask him if
      it is a typo" but still saves. `log_body` with a jump over 5 kg and `confirmed` false
      saves nothing and says to ask him. Refusals list the valid choices (the gym's
      equipment names, today's exercise names).
    - Keep the existing helpers for the flow (`_move_to`, `_next_open`, `_open`, `_close`,
      `_swap` without its fixed question, `_add_own`, `_typo`, `_fix_set`, `_week_question`,
      `reports`, `meals`, `planner`) and call them from the tools; delete what only the
      sorting path used.
    - Exact match for equipment ignores case and spaces only.
    - The coach's instructions (system prompt), in `coach.py`: talk like a good personal
      trainer standing next to him; during sets reply in 1–3 short sentences that react to
      what he just did and say what comes next; answer form questions with one or two cues;
      say plainly when a photo is unclear; never ask the same question twice: when his answer
      is still unclear, make the sensible choice, say what you did, and let him correct it;
      always state the numbers you logged; identical numbers after a delivered reply are a
      new set; a bot line marked NOT delivered means he never saw it; general fitness
      guidance, not medical advice; English, kg.
    - Photos: in an open workout, any photo goes to the coach call with the image; outside a
      workout a photo without caption keeps the meal estimate path; with a caption the coach
      call gets the image and decides (`log_meal(use_photo=true)` for food).
    - The trace's "understood" holds the tool calls and their first 200 characters of result,
      as JSON.

- [ ] **Task 15d: replay Sunday through the new coach** (checkpoint) needs: Task 15a, Task 15c
  - Files: create `scripts/replay_day.py`; output `data/replay/2026-11-22.txt` (ignored).
  - Done when: `conda run -n gym-coach python scripts/replay_day.py --day 2026-11-22` copies
    `data/gym.db` to the scratchpad, resets that day (logged sets removed; the session as sent
    at 07:00, with the parents' combined machine as "Lying leg curl"; workout, flow and warm-up
    keys cleared), feeds Brian's messages from the `chat` table in order with the clock set to
    each message's time (photos: the caption only, marked "[photo]"), and writes each message,
    the tool calls and the replies to the output file plus the total and median cost per
    message. The output shows acceptance criteria 1 and 5 met. Brian reads the file and
    answers whether it sounds like a gym instructor.
  - Notes: real Haiku calls, estimated under US$0.20 for about 55 messages. The old photos
    are not kept, so the replay cannot judge photo answers. The leg-curl part of the replay
    starts from the corrected machine name, so for the swap loop also replay messages #159
    to #165 once against the session as stored before Task 15a (the stored name "Seated leg
    curl" on the old machine name).

- [ ] **Task 15e: run it live and update the docs** needs: Task 15d (Brian's verdict)
  - Files: modify `README.md`, `docs/known-issues.md`, `docs/decisions.md` (Brian's line
    from 23 Nov, written by the main session), `docs/open-items.md`.
  - Done when: the bot restarts through its scheduled task (`Stop-ScheduledTask` /
    `Start-ScheduledTask gym-coach-bot`, or the detached start if the task is missing);
    `data/bot.log` shows the start and a getUpdates poll with no traceback; one `/today`
    from Brian gets an answer. Docs describe the tools and the limits found in the replay.

- [ ] **Task 15f: end-of-run review** (opus) needs: Task 15e
  - Files: none (pre-release-reviewer on this run's commit range).
  - Done when: findings are fixed or recorded in `docs/open-items.md`; full tests and ruff
    pass.
