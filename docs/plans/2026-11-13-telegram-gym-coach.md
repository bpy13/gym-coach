# Plan: Telegram gym coach (milestones 1–3)

Approved by Brian on 2026-11-13 ("if no more question then go"). Built by the orchestrator's
workers. Phases run in order (`phaseOrder`).

## Goal
A Telegram chat bot, run by a small Python program on Brian's PC, that sends him the day's gym
session, logs what he reports back, estimates his meals from photos, and writes a weekly review
and next week's plan. His goal is to build muscle and lose fat.

## Approach
- One Python package, `gym_coach`, in a conda env. One long-running process: it long-polls
  Telegram, runs a small in-process scheduler, and calls Claude through the `anthropic` SDK.
- Records in SQLite (`data\gym.db`). Profile and equipment in `data\profile.md` and
  `data\equipment.md` (both exist on slot 1; both are git-ignored). Tests and examples use the
  made-up files in `examples\`.
- Every Claude call goes through one wrapper that records cost and enforces the monthly ceiling.
- Code never trusts the model for equipment: a validator rejects any exercise whose equipment
  is not in that day's gym list.

## Constraints (copied from `docs/decisions.md`)
- "a Telegram chat bot, run by a small program on this PC. The bot messages him the day's
  session for that day's gym. He replies in plain words with what he did and sends meal photos
  into the same chat; the bot replies with a calorie and protein estimate. The program saves
  every session and meal to a record file on this PC, which git ignores. While the PC is off
  the bot is silent and answers waiting messages when the PC starts."
- "public GitHub repo"; "all personal data is git-ignored (logs, measurements, health notes,
  photos, `.env`)". `docs/` is public: no age, weight, address or building name there.
- "the scheduled runs on this PC use the API key ... with a hard ceiling of US$5 a month. The
  runs stop calling the AI once the month's cost reaches it."
- "Haiku 5.5 (`claude-haiku-5-5`) reads meal photos and his session reports. Opus 5.5
  (`claude-opus-5-5`) writes the first plan, the weekly review and next week's plan." Prices
  per million tokens in/out: Haiku 5.5 US$0.10/US$0.50, Opus 5.5 US$4/US$20.
- "three strength sessions a week, in the late afternoon, for now. He also does cardio at a
  heart rate of about 130." Claude's unconfirmed reading: cardio falls on days between the
  strength sessions; the schedule proposal must state this so he can correct it.
- Home gym Monday–Friday, parents' gym Saturday–Sunday. Saturday is free in the morning only.
- "The coach assumes 2 kg steps at both gyms" for dumbbells until he checks the racks.
- "The bot answers only Brian's own Telegram account and ignores everyone else."
- "Session message at 07:00 Hong Kong time on training days; weekly review on Sunday at 20:00;
  body weight and waist prompt on Monday at 07:00. All three times are settings. If the PC was
  off at that time, the bot sends the message when it starts, on the same day only."
- "After each report the bot repeats what it logged ... He corrects it by replying."
- "Progression is rule-based and cautious: add weight only after he hits the top of the rep
  range on every set. Fat loss target at most 0.5-1% of body weight a week. The bot states that
  it gives general fitness guidance, not medical advice."
- "The program does not keep meal photos on disk. It stores only the estimate."
- "Python 3.12 in a conda env named `gym-coach`. Dependencies: the `anthropic` SDK only. The
  program calls Telegram's HTTP interface directly with `httpx` ... Tests use pytest with a fake
  Telegram and a fake Claude."
- Windows rules from the working agreement: absolute paths, headless start with
  `conhost.exe --headless`, no `-ExecutionPolicy Bypass`.

## Acceptance criteria
The "Done when" lists in `docs/milestones.md`, milestones 1 to 3.

## Shared resources
- `data\gym.db`, `data\*.md`, `.env` and the conda env exist only in the project folder
  (slot 1). Tests must use a temporary database and `examples\`, never `data\`.
- Only one process may poll a Telegram bot token at a time: only slot 1 runs the real bot.
- `src\gym_coach\router.py` and `src\gym_coach\app.py` are touched by several tasks; those
  tasks are chained with `needs:` so they never run at once.

---

## Phase 1 – Daily session and report (sonnet)

- [x] **Task 1: project skeleton and environment** (slot 1 only)
  - Files: create `pyproject.toml`, `environment.yml`, `src\gym_coach\__init__.py`,
    `src\gym_coach\config.py`, `tests\test_config.py`, `.env.example`, `README.md`,
    `examples\profile.md`, `examples\equipment.md`; modify `CLAUDE.md` (Environment section).
  - Done when: `conda run -n gym-coach python -m pytest -q` passes and
    `conda run -n gym-coach ruff check .` reports no errors; CLAUDE.md lists the real install,
    run, test and lint commands.
  - Notes: follow the python-env skill. `config.py` reads `.env` with the standard library
    (no dotenv package) into a frozen dataclass: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_ID`,
    `ANTHROPIC_API_KEY`, `MONTHLY_CEILING_USD=5`, `SESSION_TIME=07:00`, `REVIEW_TIME=20:00`,
    `BODY_PROMPT_TIME=07:00`, `TIMEZONE=Asia/Hong_Kong`, `MODEL_FAST=claude-haiku-5-5`,
    `MODEL_COACH=claude-opus-5-5`, `DATA_DIR=data`. Missing secrets raise a clear error naming
    the key, never printing a value. `examples\` holds a made-up person and two made-up gyms in
    the same layout as `data\profile.md` and `data\equipment.md` (read those for the layout; copy
    no real values). Dev dependencies: pytest, ruff.

- [x] **Task 2: record storage** needs: Task 1 `[parallel-ok]`
  - Files: create `src\gym_coach\store.py`, `tests\test_store.py`.
  - Done when: `pytest tests\test_store.py -q` passes, including a test that reopening the
    file keeps the data.
  - Notes: `sqlite3` from the standard library. Tables: `plan_sessions` (date, gym, kind
    strength|cardio, status proposed|approved|done|skipped, exercises as JSON: name, equipment,
    sets, rep_low, rep_high, weight_kg), `logged_sets` (date, exercise, set_no, weight_kg, reps,
    effort note), `meals` (timestamp, description, kcal, protein_g), `body` (date, weight_kg,
    waist_cm), `api_calls` (timestamp, model, input_tokens, output_tokens, cost_usd),
    `kv` (key, value) for the Telegram offset, last-sent markers and the approved weekly
    schedule. Write tests first.

- [x] **Task 3: Telegram client** needs: Task 1 `[parallel-ok]`
  - Files: create `src\gym_coach\telegram.py`, `tests\test_telegram.py`, `tests\fakes.py`
    (FakeTelegram).
  - Done when: `pytest tests\test_telegram.py -q` passes: updates from another user id are
    dropped; the offset advances so no update is handled twice; a network error is retried with
    a pause and does not crash; a photo message yields the file id of the largest size whose
    long edge is at most 1280 px.
  - Notes: `httpx` against `https://api.telegram.org/bot<token>/`: `getUpdates` (long poll,
    timeout 50 s), `sendMessage` (split texts over 4,000 characters), `getFile` plus download
    to bytes in memory. Never log the token. Telegram keeps undelivered updates for at most 24
    hours, so nothing else is needed for catch-up.

- [x] **Task 4: Claude wrapper with cost ceiling** needs: Task 2
  - Files: create `src\gym_coach\llm.py`, `tests\test_llm.py`; add FakeClaude to
    `tests\fakes.py`.
  - Done when: `pytest tests\test_llm.py -q` passes: each call writes one `api_calls` row with
    the cost from the price table; when the month's total is at or over the ceiling, the wrapper
    raises `CeilingReached` without calling the API; a new calendar month (Hong Kong time)
    starts from zero.
  - Notes: price table in `llm.py`, US$ per million tokens in/out: `claude-haiku-5-5` 0.10/0.50
    (0.50/2.50 when the prompt exceeds 100,000 tokens), `claude-opus-5-5` 4/20. Read tokens
    from the response's `usage`. One function for text, one for text plus one JPEG image.
    Structured answers: ask for JSON and parse it; on a parse failure retry once, then raise.

- [x] **Task 5: gym for the day and coach context** needs: Task 1 `[parallel-ok]`
  - Files: create `src\gym_coach\context.py`, `tests\test_context.py`.
  - Done when: `pytest tests\test_context.py -q` passes: Monday–Friday dates give `home`,
    Saturday–Sunday give `parents` (Hong Kong time); the equipment list for each gym parses from
    `examples\equipment.md` into a set of equipment names; "unsure" items are excluded.
  - Notes: `equipment.md` has `## Home gym (weekdays)` and `## Parents' gym (weekends)`
    sections with bullet lists; items carrying "Unsure" or under "Not seen" do not count as
    available. Expose `gym_for(date)`, `equipment_for(gym)`, `profile_text()`.

- [x] **Task 6: first schedule and plan proposal** needs: Task 2, Task 4, Task 5
  - Files: create `src\gym_coach\planner.py`, `src\gym_coach\prompts.py`,
    `tests\test_planner.py`.
  - Done when: `pytest tests\test_planner.py -q` passes with FakeClaude: a plan naming
    equipment missing from that day's gym is rejected and regenerated once, then fails loudly;
    a valid plan is stored as `proposed`; `approve` marks it `approved`; a change request
    ("move Thursday to Friday") produces a new proposal.
  - Notes: the coach model gets the profile, both equipment lists and these fixed rules: three
    strength sessions a week in the late afternoon; Saturday only in the morning, so prefer
    weekdays and Sunday; cardio at about 130 bpm on days between strength sessions, and the
    proposal text must say "I placed cardio on the days between strength sessions; tell me if
    you meant something else"; full-body sessions for a beginner, 5–7 exercises, 3 sets, rep
    range 8–12; first-week weights light, and the message asks how hard each set felt; dumbbell
    weights in 2 kg steps; general guidance, not medical advice. Output JSON matching
    `plan_sessions`. The validator, not the model, enforces equipment and the gym for each date.

- [x] **Task 7: message router and report logging** needs: Task 3, Task 4, Task 6
  - Files: create `src\gym_coach\router.py`, `src\gym_coach\reports.py`,
    `tests\test_router.py`, `tests\test_reports.py`.
  - Done when: both test files pass with the fakes: "chest press 35kg 10 10 8, lat pulldown 40
    3x10" stores six sets against today's session and the reply starts with "Logged:" and lists
    them; a following "no, chest press was 30 kg" replaces those sets and replies with the
    corrected log; "approve" approves a proposed plan; "skip today" marks the session skipped;
    when `CeilingReached` is raised the reply says the month's US$5 limit is reached.
  - Notes: the fast model classifies each text into one intent (`report`, `correction`,
    `approve`, `change_plan`, `skip`, `body`, `progress`, `question`) and extracts fields as
    JSON. Exact commands `/start`, `/today`, `/progress`, `/cost` skip the model. `question`
    gets a short answer from the fast model with the profile and today's session as context.
    Handlers for `body` and `progress` are stubs here ("coming soon"); Tasks 14 and 17 fill them.

- [x] **Task 8: daily session message and scheduler** needs: Task 7
  - Files: create `src\gym_coach\scheduler.py`, `src\gym_coach\messages.py`,
    `tests\test_scheduler.py`.
  - Done when: `pytest tests\test_scheduler.py -q` passes with a fake clock: at 07:00 on a day
    with an approved session, exactly one message is sent, naming the gym and each exercise with
    sets, reps and weight; a start at 15:00 the same day sends it once; a start the next day
    does not send yesterday's; a cardio day sends the cardio line; a rest day sends nothing.
  - Notes: no scheduling library: a loop checks due jobs each minute and records "sent" markers
    in `kv`. Message layout: first line "Home gym, Tue 17 Nov" (or "Parents' gym"), then one
    line per exercise, e.g. "Chest press machine: 3 x 8-12 at 30 kg".

- [x] **Task 9: main program and logon start** needs: Task 8 (slot 1 only) (ticked 2026-11-13; logon task not registered: the safety check refused it; Brian runs scripts\install-logon-task.ps1 himself (orchestrator, 2026-11-13))
  - Files: create `src\gym_coach\app.py`, `src\gym_coach\__main__.py`, `scripts\run-bot.ps1`,
    `scripts\install-logon-task.ps1`, `tests\test_app.py`; modify `README.md`.
  - Done when: `pytest -q` and `ruff check .` pass; `python -m gym_coach --check` prints
    "config ok" and exits 0 with a filled `.env`, or names the missing key and exits 1; running
    `scripts\install-logon-task.ps1` registers a task named `gym-coach-bot` whose action is
    `conhost.exe --headless powershell.exe -NoProfile -File <absolute path>\scripts\run-bot.ps1`
    (check with `Get-ScheduledTask gym-coach-bot`).
  - Notes: `app.py` runs the poll loop and the scheduler in one process, writes a rotating log
    to `data\bot.log` (no message text or secrets at INFO level), and restarts the loop after an
    unexpected error with a 30-second pause. A second instance must exit at once (lock file in
    `data\`). On first `/start` with no plan, the bot runs Task 6's proposal. Do not use
    `-ExecutionPolicy Bypass`.

- [x] **Task 9a: the bot learns Brian's user number on first message** needs: Task 9 (slot 1 only)
  - Brian, 2026-11-13: "ok" (to the orchestrator's question: the bot saves the first sender's Telegram user number instead of Brian copying it into `.env`; Default accepted).
  - Files: modify `src\gym_coach\config.py`, `src\gym_coach\router.py` (or `app.py`, wherever updates are filtered), their tests, `README.md`, `.env.example`.
  - What: `TELEGRAM_ALLOWED_USER_ID` becomes optional. If it is set, it wins. If it is empty and no owner is stored, the first private-chat message's sender number is stored in `kv` as the owner, the bot replies "Paired with this account. I will answer only you.", and logs "owner paired" (never the number at INFO). From then on every update from another sender is ignored, exactly as with the `.env` value. Group chats never pair. `--check` prints "config ok (owner not paired yet)" when no owner is set or stored. Never write the number into any committed file.
  - Done when: tests with the fakes show: first sender pairs and gets the reply; a second sender is ignored afterwards; a group message never pairs; a set `.env` value overrides pairing; `pytest -q` and `ruff check .` pass; on slot 1 `python -m gym_coach --check` prints "config ok (owner not paired yet)".

- [ ] **Task 9b: the real bot never receives messages** needs: Task 9a (slot 1 only) (waiting: Brian restarts the bot; orchestrator checks bot.log) (code fixes pushed 2026-11-13, slot 1)
  - Found by the orchestrator, 2026-11-13, with the real bot: Brian sent /start and "hi"; after 3 minutes `data\bot.log` holds only "bot started", nothing paired, no warning. A thread dump after 75 s (faulthandler) shows the main thread still inside the first `getUpdates` POST (`telegram.py` `_call` -> httpx -> `ssl.recv`, waiting for response headers), although the client timeout is 60 s and pending updates should return at once. The PC reaches https://api.telegram.org (curl: 302 in 1 s). Second bug: `Stop-ScheduledTask gym-coach-bot` stops conhost/powershell but leaves `python.exe -m gym_coach` running (the orchestrator had to stop it by PID).
  - Files: `src\gym_coach\telegram.py`, `src\gym_coach\app.py`, `scripts\run-bot.ps1`, their tests, `docs\known-issues.md`.
  - What: find the root cause before changing code (debug skill). Leads: httpx timeout semantics with a 50 s long poll (try an explicit `httpx.Timeout(connect=10, read=POLL_TIMEOUT_S + 10, write=10, pool=10)`), HTTP/1.1 keep-alive on a dead pooled socket, IPv6 vs IPv4, a proxy in the environment. Verify against the real Telegram with a short-lived run (a `getMe` and one `getUpdates` with `timeout` 0 is enough; never print or log the token). Make the logon task's stop end the bot too (e.g. run python directly from the task action, or have run-bot.ps1 wait on and stop its child).
  - Done when: a short real run logs a successful poll within 70 s and, with Brian's queued messages, "owner paired"; a test covers the fixed timeout; `Stop-ScheduledTask gym-coach-bot` leaves no `python.exe -m gym_coach` running; `pytest -q` and `ruff check .` pass. The orchestrator restarts the logon task afterwards (do not leave your own bot instance running).

- [x] **Task 10: Brian creates the Telegram bot and fills `.env`** (ticked 2026-11-13 by the orchestrator: Brian, "API keys added"; the orchestrator saw TELEGRAM_BOT_TOKEN and ANTHROPIC_API_KEY set without reading them; TELEGRAM_ALLOWED_USER_ID stays empty by decision, see Task 9a)
  - Files: `.env` (never committed).
  - Done when: `python -m gym_coach --check` prints "config ok" on slot 1.
  - Notes: the question is in `docs/inbox.md`. Steps for Brian, one per message: BotFather
    `/newbot`; copy the token; message the new bot once; read his user id; create an Anthropic
    API key; set a US$5 monthly spend limit in the Anthropic Console; paste the three values
    into `.env`.

- [ ] **Task 11: live check with the real bot** needs: Task 9, Task 9a, Task 9b, Task 10 (slot 1 only) (checkpoint) (waiting: Brian starts the bot via the logon task and sends /start; orchestrator runs the live part)
  - Files: modify `docs\known-issues.md` (create if needed), `docs\open-items.md` via the report.
  - Done when: with the bot running from the logon task, Brian's `/start` yields a real schedule
    and first-week proposal that uses only equipment in `data\equipment.md`; `/cost` shows a
    non-zero month total under US$1; the bot ignores a message from a second Telegram account or
    a forged update in a test call; the checkpoint card asks Brian to approve or change the
    schedule in the chat, and milestone 1's last line (one real session logged at each gym)
    is left for him to complete.
  - Notes: paste no personal values into any committed file or the card.

## Phase 2 – Meal photos and body numbers (sonnet)

- [ ] **Task 12: daily calorie and protein targets** needs: Task 11
  - Files: create `src\gym_coach\targets.py`, `tests\test_targets.py`.
  - Done when: tests pass for the formula on the made-up profile, including: the weekly loss
    implied by the deficit never exceeds 1% of body weight; protein is 1.8 g per kg of body
    weight; targets recompute when a new body weight is stored.
  - Notes: resting energy by the Mifflin-St Jeor formula, activity factor 1.4, deficit 400 kcal
    a day, capped by the 1% rule. Pure code, no model call. Reads weight from the latest `body`
    row, falling back to the profile.

- [ ] **Task 13: meal photo estimates** needs: Task 12
  - Files: create `src\gym_coach\meals.py`, `tests\test_meals.py`; modify
    `src\gym_coach\router.py`.
  - Done when: tests pass with the fakes: a photo message leads to one fast-model call with
    the image, one `meals` row, and a reply like "About 650 kcal, 35 g protein (chicken rice).
    Today: 1,420 of 2,000 kcal, 78 of 130 g protein."; a caption ("half portion") is passed to
    the model; "that was 400 kcal" corrects the last meal; no image bytes are written to disk.
  - Notes: use the Telegram photo size chosen in Task 3. A text-only meal ("had two eggs and
    toast") is logged the same way; add the `meal` intent to the router. The reply says
    estimates from photos are rough.

- [ ] **Task 14: weekly body numbers** needs: Task 13
  - Files: modify `src\gym_coach\router.py`, `src\gym_coach\scheduler.py`; create
    `tests\test_body.py`.
  - Done when: tests pass: Monday 07:00 sends one prompt for weight and waist; "81.6 kg, waist
    91" stores one `body` row; a weight more than 5 kg from the last one is questioned before it
    is stored.

- [ ] **Task 15: ceiling check end to end** needs: Task 13 `[parallel-ok]`
  - Files: create `tests\test_ceiling_e2e.py`.
  - Done when: the test seeds `api_calls` to US$5.00 for the month, sends a photo and a report
    through the router with the fakes, and asserts that no model call happens and both replies
    state the limit; `/cost` still works.

- [ ] **Task 16: live check of meals** needs: Task 13, Task 14 (slot 1 only) (checkpoint)
  - Done when: Brian sends one real meal photo and gets an estimate and a daily total; the
    month's cost in `/cost` rose by less than US$0.01 for that photo; the card asks Brian
    whether the estimate looked reasonable.

## Phase 3 – Weekly review (sonnet)

- [ ] **Task 17: progress numbers** needs: Task 16
  - Files: create `src\gym_coach\progress.py`, `tests\test_progress.py`; modify
    `src\gym_coach\router.py`.
  - Done when: tests pass: `/progress` returns, for the last four weeks, sessions done out of
    planned, the best set per exercise per week, body weight and waist per week, and average
    daily kcal and protein; weeks with no data show "no data", not zero.
  - Notes: pure code from the database, no model call.

- [ ] **Task 18: weekly review and next week's plan** needs: Task 17
  - Files: create `src\gym_coach\review.py`, `tests\test_review.py`; modify
    `src\gym_coach\scheduler.py`, `src\gym_coach\planner.py`.
  - Done when: tests pass with FakeClaude and a fake clock: Sunday 20:00 sends one review and
    stores next week's sessions as `approved`; an exercise where every set reached the top of
    the rep range goes up by the smallest step (2 kg dumbbells, one plate on machines, default
    2.5 kg); one where any set fell below the bottom of the range for two sessions goes down one
    step; otherwise it holds; a model plan that breaks these rules or the equipment check is
    corrected by code, not sent as is.
  - Notes: the coach model gets Task 17's numbers, the profile and both equipment lists, and
    writes at most 12 lines: what went well, what to change, the body and food trend against
    the 0.5–1% rule. The code computes each exercise's next weight; the model only words the
    review and may swap an exercise for an equivalent on available equipment.

- [ ] **Task 19: live check of the review** needs: Task 18 (slot 1 only) (checkpoint)
  - Done when: a review triggered by hand (`python -m gym_coach --review-now`) arrives in
    Brian's chat from his real records, and the card asks him whether the review and next
    week's plan read sensibly; `pytest -q` and `ruff check .` pass.
