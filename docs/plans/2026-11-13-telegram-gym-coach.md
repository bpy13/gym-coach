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

- [x] **Task 9b: the real bot never receives messages** needs: Task 9a (slot 1 only) (waiting: Brian restarts the bot; orchestrator checks bot.log) (code fixes pushed 2026-11-13, slot 1)
 (ticked 2026-11-13 by the orchestrator: after Brian restarted the bot on the fixed code at 03:20, bot.log shows one ConnectError retry, then Brian's "hi" at 03:24 was answered (Brian: "hi and responded"); owner paired at 03:18. Not checked: that Stop-ScheduledTask now ends python; nobody stopped the bot since.)
  - Found by the orchestrator, 2026-11-13, with the real bot: Brian sent /start and "hi"; after 3 minutes `data\bot.log` holds only "bot started", nothing paired, no warning. A thread dump after 75 s (faulthandler) shows the main thread still inside the first `getUpdates` POST (`telegram.py` `_call` -> httpx -> `ssl.recv`, waiting for response headers), although the client timeout is 60 s and pending updates should return at once. The PC reaches https://api.telegram.org (curl: 302 in 1 s). Second bug: `Stop-ScheduledTask gym-coach-bot` stops conhost/powershell but leaves `python.exe -m gym_coach` running (the orchestrator had to stop it by PID).
  - Files: `src\gym_coach\telegram.py`, `src\gym_coach\app.py`, `scripts\run-bot.ps1`, their tests, `docs\known-issues.md`.
  - What: find the root cause before changing code (debug skill). Leads: httpx timeout semantics with a 50 s long poll (try an explicit `httpx.Timeout(connect=10, read=POLL_TIMEOUT_S + 10, write=10, pool=10)`), HTTP/1.1 keep-alive on a dead pooled socket, IPv6 vs IPv4, a proxy in the environment. Verify against the real Telegram with a short-lived run (a `getMe` and one `getUpdates` with `timeout` 0 is enough; never print or log the token). Make the logon task's stop end the bot too (e.g. run python directly from the task action, or have run-bot.ps1 wait on and stop its child).
  - Done when: a short real run logs a successful poll within 70 s and, with Brian's queued messages, "owner paired"; a test covers the fixed timeout; `Stop-ScheduledTask gym-coach-bot` leaves no `python.exe -m gym_coach` running; `pytest -q` and `ruff check .` pass. The orchestrator restarts the logon task afterwards (do not leave your own bot instance running).

- [x] **Task 9c: /start does not propose the first week** needs: Task 9b (slot 1 only) (ticked 2026-11-13, slot 1: router has a /propose command; 88 tests and ruff pass; not run against the real bot)
  - Found by the orchestrator, 2026-11-13, on the real bot: after Brian's /start, `plan_sessions` is empty and every API call was the fast model. `App.handle` appends `router.handle("/propose")`, but `Router._handle` has no `/propose` command, so the text goes to the classifier and no plan is made.
  - Files: `src\gym_coach\router.py`, `src\gym_coach\app.py`, `tests\test_router.py`, `tests\test_app.py`.
  - What: write the failing test first: with FakeClaude and no upcoming plan, `/start` returns the help text plus a proposed first week, and `plan_sessions` holds `proposed` rows. Then add the `/propose` command to the router (calling `planner.propose` for this week, as the `change_plan` path already does) or call the planner directly from `App`; pick whichever keeps one path.
  - Done when: the new tests pass; `pytest -q` and `ruff check .` pass; pushed. Do not start or stop the real bot: Brian restarts it and the orchestrator checks the result.

- [x] **Task 9d: stopping the logon task still leaves the bot running** needs: Task 9c (slot 1 only) (ticked 2026-11-13, slot 1: task now starts pythonw.exe directly; parent-watching and run-bot.ps1 removed; 86 tests and ruff pass; task not re-registered: Brian re-runs install-logon-task.ps1)
  - Found by the orchestrator, 2026-11-13 03:45: Brian ran `Stop-ScheduledTask gym-coach-bot` then `Start-ScheduledTask`. The bot from 03:20 (python, `--exit-with-parent`) kept running, so the new code never started (the second instance hit the lock). Its parent, `powershell.exe` (run-bot.ps1), was also still alive: Stop-ScheduledTask ends only `conhost.exe`, so watching the direct parent (`os.getppid()`) never fires.
  - Files: `src\gym_coach\__main__.py`, `src\gym_coach\app.py`, `scripts\run-bot.ps1`, `scripts\install-logon-task.ps1`, their tests, `docs\known-issues.md`, `README.md`.
  - What: find a way that Task Scheduler's stop really ends the bot. Options to weigh: make the task action start python directly with `pythonw.exe`/`python.exe` and no conhost or powershell between (Task Scheduler then stops the process it started), or have the bot watch the conhost grandparent. Prefer the one with fewer moving parts; keep "no window" and no `-ExecutionPolicy Bypass`. If the action changes, Brian re-runs install-logon-task.ps1: say so in the README.
  - Done when: a test covers the chosen mechanism; `pytest -q` and `ruff check .` pass; pushed. Do not start or stop the real bot or the task: the orchestrator gives Brian the steps.

- [x] **Task 9e: session messages list every exercise and show the machine's photo** needs: Task 9d (slot 1 only) (ticked 2026-11-13, slot 1: proposal lists every day; albums via albums.py; 97 tests and ruff pass; not run on the real bot: Brian restarts after pip install, orchestrator checks)
  - Brian, 2026-11-13: "message should show images so I know which machine to use" (on seeing the first proposed week, which named machines in text only).
  - Found by the orchestrator, 2026-11-13: the proposal reply sent to Telegram holds only the coach's introduction; the exercises stored in `plan_sessions` never appear in the message.
  - Files: `src\gym_coach\planner.py` or `router.py` (proposal text), `src\gym_coach\messages.py`, `src\gym_coach\telegram.py` (`send_photo` / `send_media_group`), `src\gym_coach\context.py` (photo lookup), their tests, `README.md`.
  - What: (1) The proposal reply lists each day: date, gym, kind, and per exercise the name, sets x reps and weight (Task 8's line format). (2) The 07:00 session message and the proposal attach, per exercise, the photo of its machine: `data\equipment.md` names the photo id beside each item (e.g. "Chest press: seen (IMG_...)"); the files are in `photos\home\` and `photos\parents\`. Send one album per session (Telegram media group, at most 10, each photo's caption = the exercise name), then the text. Shrink each photo to at most 1280 px on the long edge before upload. An exercise whose equipment has no photo id goes without one. The proposal sends photos for the first session only (to keep the chat short); the daily message sends them for that day. Photos are personal: never commit them or copies; tests use made-up images.
  - Done when: tests with FakeTelegram show the album and the full text for a strength day, no album on a cardio day, and a missing photo skipped; `pytest -q` and `ruff check .` pass; pushed. Do not start or stop the real bot: the orchestrator gives Brian the restart steps.

- [x] **Task 9f: free-weight and cable exercises show an illustration of the movement** needs: Task 9e (slot 1 only) (ticked 2026-11-13, slot 1: free-exercise-db is Unlicense; illustrations.py; 107 tests and ruff pass; not run on the real bot)
  - Brian, 2026-11-13: "dumbbell should show illustration, hard to understand just from the exercise name" (after Task 9e: machine exercises show his machine photo; dumbbell exercises would show only the rack).
  - Source (orchestrator's default; check it first): the open exercise database `free-exercise-db` on GitHub (yuhonas/free-exercise-db), about 800 exercises with JSON and two images each (start and end position). Confirm its licence allows use and say it in the README; if it does not, stop and post the question to `docs/inbox.md` with two other sources.
  - Files: `src\gym_coach\illustrations.py` (new: download once into `data\illustrations\`, look up by exercise id), `src\gym_coach\prompts.py` / `planner.py` (the coach picks free-weight and cable exercises from a short list of names that exist in the database, filtered to the equipment at that gym), `src\gym_coach\messages.py` (album: the exercise's start and end images where there is no machine photo), their tests, `README.md`.
  - What: images stay out of git (in `data\`, ignored); fetch only the images of exercises in the allowed list, not the whole database. Machine exercises keep Brian's own photo (Task 9e). Caption = exercise name plus one short form cue from the database's instructions.
  - Done when: tests with fakes show a dumbbell exercise sent with its two images and a machine exercise with the machine photo; an exercise not in the database still sends text; `pytest -q` and `ruff check .` pass; pushed. Do not start or stop the real bot.

- [x] **Task 9g: the scheduler thread crashes on the database every minute** needs: Task 9f (slot 1 only) (ticked 2026-11-13, slot 1: Store shares one connection across threads under a lock; 108 tests and ruff pass; not run on the real bot)
  - Found by the orchestrator, 2026-11-13, in `data\bot.log`: every scheduler tick fails with `sqlite3.ProgrammingError: SQLite objects created in a thread can only be used in that same thread` (scheduler.py `_send_session` -> store.py `get`). `app.py` runs `scheduler.run` in a thread but shares the Store made in the main thread. So the 07:00 session message can never be sent.
  - Files: `src\gym_coach\store.py` and/or `src\gym_coach\app.py`, `src\gym_coach\scheduler.py`, their tests.
  - What: make database use from the scheduler thread safe (for example one connection with `check_same_thread=False` guarded by a lock, or a separate Store for the thread). Pick the smaller change; no data loss, no schema change.
  - Done when: a new test runs a scheduler tick in a real second thread against a real Store file and it sends the session message (FakeTelegram); `pytest -q` and `ruff check .` pass; pushed. Do not start or stop the real bot.

- [x] **Task 9h: restart the real bot so it runs the Task 9g fix, then check its log** needs: Task 9g (slot 1 only) (ticked 2026-11-16, slot 1: restarted via the scheduled task; new pythonw pid started 14:45:20; 3 min later "SQLite objects created in a thread" count 149 before and 149 after, Traceback count 149 before and after; bot still running)
  - Found by the framework review, 2026-11-16: the bot process (`pythonw -m gym_coach`) started 13 Nov 03:48, before Task 9g landed at 13:00, so it still runs the old code. `data\bot.log` has 145 "SQLite objects created in a thread" errors, the last at 14:36 on 16 Nov.
  - Brian, 2026-11-16 (framework review, question 2): "a)": the worker restarts the live program as part of the task and checks the log after.
  - Files: none in git (read `data\bot.log`; never commit it or paste personal values from it).
  - What: restart through the scheduled task only: `Stop-ScheduledTask gym-coach-bot`, confirm no `pythonw` process runs `-m gym_coach`, then `Start-ScheduledTask gym-coach-bot`. Never start the bot as the worker's own child process: run-worker stops the worker's children when the run ends.
  - Done when: after the restart one `pythonw -m gym_coach` process runs with a start time after the restart; after at least 3 minutes `data\bot.log` shows no new "SQLite objects created in a thread" line (count before and after) and no new traceback; the bot process is still running when the worker hands back. Report the counts in the tick note.

- [x] **Task 9i: every exercise in a session message gets a picture** (slot 1 only) (bot restarted 16:07 on 16 Nov after the code change; bot.log shows a clean start and no new error; orchestrator checked, and rendered 18 Nov with 10 pictures for 6 exercises, 20 Nov with 8 for 6)
  - Brian, 2026-11-16: "shouldn't the gym bot also send illustration?" and "I've requested an image
    or an illustration for each of the workout task" (decisions of 2026-11-13, Tasks 9e and 9f).
  - Symptom (checked by the orchestrator on the real `data\gym.db`, 2026-11-16): no exercise in
    `plan_sessions` carries an `illustration` id, so `session_album` returns pictures for machine
    exercises only: 5 of 6 on Mon 16 Nov, 2 of 6 on Wed 18 Nov, 4 of 6 on Fri 20 Nov. The week was
    proposed on 13 Nov, before Task 9f; and the prompt lets the model leave the id out.
  - Do: (1) After a proposal, code (not the model) makes sure every strength exercise has either
    Brian's machine photo or an illustration id from that gym's list: match by exercise name
    against the catalogue; when nothing matches, ask the model once for the id or for another
    exercise that has one, and log what stays without a picture. (2) Add the ids to the sessions
    already stored for 17 to 20 Nov; change nothing else in them (exercises, sets, weights,
    status). (3) Restart the bot through its scheduled task (`Stop-ScheduledTask`, then
    `Start-ScheduledTask gym-coach-bot`) and check `databot.log`: a new "bot started" line and no
    new error after it.
  - Files: `src\gym_coach\planner.py`, `src\gym_coach\illustrations.py`, `src\gym_coach\prompts.py`,
    their tests; a one-off script under `scripts\` for step 2.
  - Done when (on the real database, not tests alone): for each strength session of 17 to 20 Nov,
    `session_album` returns at least one picture per exercise; write the count per day here
    (exercise names and counts only, no personal values). Tests cover a proposal whose model answer
    has no ids. Tests and ruff pass. The bot runs the new code and its log is clean.
  - Done 2026-11-16 (slot 1): code matches names to the catalogue, asks the model once for the rest (`planner.ensure_pictures`); ids added to the stored sessions of 18 and 20 Nov (17 and 19 are cardio) with `scriptsdd_illustration_ids.py`, nothing else changed. `session_album` on the real database, images per exercise: Wed 18 Nov [2, 2, 2, 1, 2, 1]; Fri 20 Nov [2, 1, 1, 1, 1, 2]. 136 tests pass, ruff clean.
  - Step 3 not done: the auto-mode check refused `Stop-ScheduledTask`/`Start-ScheduledTask gym-coach-bot` (2026-11-16). Brian restarts the bot; the orchestrator checks `databot.log` for a new "bot started" line and no error.
- [x] **Task 9j: strength days are Tuesday, Thursday (home) and Sunday (parents' gym)** (slot 1 only) (beside earlier phases) (Brian restarted the bot 16:34 on 16 Nov; bot.log shows a clean start; the stored week checked by the orchestrator); the restart was refused by the auto-mode check, so the orchestrator restarts `gym-coach-bot` and checks bot.log, then ticks this)
  - Brian, 2026-11-16: "I'd like to spend a session on Sunday", "yes parents' gym" and
    "do Tue, Thu, Sun" (decisions.md). This replaces Monday, Wednesday, Friday.
  - Do: (1) Find where the weekly pattern is set (the plan prompt and any day rule in
    `planner.py`, the settings, `docs/milestones.md` line "home Monday-Friday, parents'
    Saturday-Sunday") and make it: strength on Tuesday and Thursday at the home gym and on
    Sunday at his parents' gym; no other strength day. A day holds one session, so a strength
    day has no cardio row. Cardio days are not decided yet (asked 16 Nov): keep cardio off
    Tuesday, Thursday and Sunday and leave the other days as the code has them. (2) Sunday's
    session uses what only the parents' gym has (decisions.md and the equipment list name it:
    leg press, Smith machine, fly machine) for muscles the home gym trains poorly. (3) Replace
    the stored sessions from 17 Nov to 22 Nov on the real `data\gym.db` with a new proposal on
    this pattern (one paid call, well under the US$10 allowance; put the real cost on the board);
    every strength exercise carries its picture (Task 9i). Leave the status "proposed": Brian
    approves the week with the orchestrator, who then asks for the status change. (4) Restart
    the bot through its scheduled task if code it loads changed; if the restart is refused, say
    so in the ENDED message and stop there.
  - Done when: on the real database, 17 and 19 Nov are strength at home, 22 Nov is strength at
    parents' with at least one exercise on equipment the home gym lacks, no strength row on
    another day from 17 to 22 Nov, every strength exercise has a picture (count them with
    `session_album`), tests pass, and `databot.log` shows no new error after the last start.
    Send the orchestrator the new sessions' dates, gyms and exercise names in the ENDED message.
- [x] **Task 9k: one Telegram message per exercise: machine photo, illustration and the task together** `[parallel-ok]` (slot 1 only) (beside earlier phases) (done 2026-11-16: on Brian's "Yes, do both" the orchestrator restarted the bot at 16:55; bot.log shows a clean start, no new error)
  - Brian, 2026-11-16, on seeing a mock-up of the 18 Nov session (one text message, then one
    album of ten pictures): "(should be image + illustration + task) as one message. So if 5
    task on gym, like on Tuesday, 5 messages should be sent" (decisions.md).
  - Symptoms (checked by the orchestrator, 2026-11-16): (a) `telegram.py` `send_album` sends one
    media group with a caption on several items; Telegram shows no caption under such an album,
    so the pictures arrive with no name. (b) A machine exercise gets only Brian's machine photo
    and no illustration of the movement. (c) "Dumbbell lateral raise" on the old 18 Nov session
    got the illustration of a one-arm raise lying sideways on an incline bench: the name match
    in Task 9i picked the wrong catalogue entry.
  - Do: (1) A strength session goes out as one short header message (gym and date), then one
    message per exercise, in order: that exercise's pictures (Brian's photo of the machine when
    the exercise uses one of his machines, and the illustration of the movement when the
    catalogue has one; both when both exist) with ONE caption under them: the name, sets x reps
    at weight, and the form cue. In a media group put the caption on the first item only and
    leave the others empty, so Telegram shows it; a single picture goes as a photo with the
    caption; an exercise with no picture at all goes as text and is logged. Then the closing
    line asking what he did. Cardio stays one text message. (2) Machine exercises get an
    illustration id too, where the catalogue has the movement (same rule as Task 9i: code
    matches, the model is asked once, what stays without is logged); add the ids to the stored
    sessions from 17 to 22 Nov and change nothing else in them. (3) Make the name match safer:
    a match must agree on the equipment and the body position (standing, seated, lying), and
    list in the ENDED message every stored exercise with the catalogue entry it got, so the
    orchestrator can look at each picture. (4) Restart the bot through its scheduled task; if
    the restart is refused, say so in the ENDED message and stop there.
  - Done when: for each strength session from 17 to 22 Nov on the real `data\gym.db`, the
    number of messages the bot would send is the number of exercises plus two (header and
    closing line), each exercise message has exactly one caption and it names the exercise with
    its sets, reps and weight; every exercise has at least one picture; tests cover the caption
    rule; and after the last start `data\bot.log` shows no new error. Do not send anything to
    Brian's chat as a test.
- [x] **Task 9l: a strength session shows one exercise at a time; the next comes when Brian reports** `[parallel-ok]` (slot 1 only) (beside earlier phases) (done 2026-11-16: on Brian's "Yes, do both" the orchestrator restarted the bot at 16:55; bot.log shows a clean start, no new error)
  - Brian, 2026-11-16, on seeing the per-exercise messages of Task 9k all at once: "should show
    1 at a time, and as I report my progress and during resting, show next" (decisions.md).
  - Do: (1) At the session time the bot sends one text message: gym, date and the list of
    exercises (name, sets x reps at weight, no pictures), ending "Send start when you begin."
    (2) On "start" (any case) it sends the first exercise message (Task 9k's: pictures and one
    caption). (3) Each reply of Brian's is logged against the exercise now shown, as today's
    reports are (sets, reps, weight, how hard). When the reply completes that exercise (the
    logged sets reach the planned sets, or he writes "next", "done" or "skip"), the bot answers
    in one short line what it logged and at once sends the next exercise message, so he reads
    it while resting. A reply that leaves sets open gets the short logged line and how many sets
    remain; nothing else. After the last exercise it sends the closing summary of the session.
    (4) Which exercise is shown is stored in the database (it survives a bot restart); a new
    day's session starts fresh; a reply when no session is open is handled as today. Cardio
    stays one text message. (5) The orchestrator's calls, which Brian may change: the list
    message plus "start" (he trains in the late afternoon, so the first exercise should arrive
    when he begins, not at 07:00), and the words next, done, skip. Record them in decisions.md
    as "(orchestrator's call, 2026-11-16; Brian may change it)". (6) Restart the bot through its
    scheduled task; if the restart is refused, say so in the ENDED message and stop there.
  - Done when: a test drives a whole stored session through the router with a fake Telegram
    (list message, start, reports that complete each exercise, next, skip, a restart in the
    middle) and sees exactly one exercise message after each completing reply and the summary
    at the end; on the real `data\gym.db` a dry run of 17 Nov (nothing sent to Brian's chat,
    nothing written to the real database) gives the list message, then six exercise messages
    one per completing reply; all tests pass; and after the last start `data\bot.log` shows
    no new error.
  - CHANGE (Brian, 2026-11-16: "Send at 07:00", to the question whether the first exercise
    should come on "start" instead of at 07:00): there is no "start" step. At the session time
    the bot sends the list message (without the "Send start" line) and right after it the first
    exercise message. This replaces steps (1), (2) and the first call in (5) above, and the
    word start in the Done-when test.
- [x] **Task 9m: cardio days are Monday, Wednesday and Friday** `[parallel-ok]` (slot 1 only) (beside earlier phases) (done 2026-11-16: on Brian's "Yes, do both" the orchestrator removed the 21 Nov cardio row and restarted the bot at 16:55; bot.log shows a clean start, no new error)
  - Brian, 2026-11-16: "cardio should be Mon Wed Fri" (decisions.md). Strength stays Tuesday,
    Thursday (home) and Sunday (parents' gym) (Task 9j). Saturday has no session.
  - Do: (1) In the day rule and the plan prompt (`planner.py`, `prompts.py`): cardio on Monday,
    Wednesday and Friday at the home gym, and on no other day. (2) On the real `data\gym.db`
    (back it up first) remove the proposed cardio row of Saturday 21 Nov; leave 18 and 20 Nov
    and every strength row as they are. (3) Restart the bot through its scheduled task if code
    it loads changed; if the restart is refused, say so in the ENDED message and stop there.
  - Done when: a test shows a proposed week has cardio only on Monday, Wednesday and Friday
    and strength only on Tuesday, Thursday and Sunday; the real database has no row for 21 Nov
    and the rows of 17, 18, 19, 20 and 22 Nov are unchanged; all tests pass.

- [x] **Task 10: Brian creates the Telegram bot and fills `.env`** (ticked 2026-11-13 by the orchestrator: Brian, "API keys added"; the orchestrator saw TELEGRAM_BOT_TOKEN and ANTHROPIC_API_KEY set without reading them; TELEGRAM_ALLOWED_USER_ID stays empty by decision, see Task 9a)
  - Files: `.env` (never committed).
  - Done when: `python -m gym_coach --check` prints "config ok" on slot 1.
  - Notes: the question is in `docs/inbox.md`. Steps for Brian, one per message: BotFather
    `/newbot`; copy the token; message the new bot once; read his user id; create an Anthropic
    API key; set a US$5 monthly spend limit in the Anthropic Console; paste the three values
    into `.env`.

- [x] **Task 11: live check with the real bot** needs: Task 9, Task 9a, Task 9b, Task 9c, Task 10 (slot 1 only) (checkpoint) (orchestrator, 2026-11-16: Brian sent /start on 13 Nov; the database holds his owner number, 5 proposed sessions for 16 to 20 Nov and 7 model calls costing US$0.07. The bot runs from the scheduled task since 14:45 today. Run the rest of the live check now; the sessions are still "proposed", so the card asks Brian to approve the schedule in the chat) (ticked 2026-11-16, slot 1: schedule stored as proposed, equipment check clean, month cost US$0.07, other senders dropped per tests; card asks Brian to approve in chat)
  - Files: modify `docs\known-issues.md` (create if needed), `docs\open-items.md` via the report.
  - Done when: with the bot running from the logon task, Brian's `/start` yields a real schedule
    and first-week proposal that uses only equipment in `data\equipment.md`; `/cost` shows a
    non-zero month total under US$1; the bot ignores a message from a second Telegram account or
    a forged update in a test call; the checkpoint card asks Brian to approve or change the
    schedule in the chat, and milestone 1's last line (one real session logged at each gym)
    is left for him to complete.
  - Notes: paste no personal values into any committed file or the card.

## Phase 2 – Meal photos and body numbers (sonnet)

Brian, 2026-11-16: "Yes, build now". Tasks 12 to 15 (code and tests only) are built now, beside
milestone 1's live check (Task 11); they count as serving the current milestone. Task 16 and Phase 3
still wait for Task 11.

- [x] **Task 12: daily calorie and protein targets** (beside earlier phases) (ticked 2026-11-16, slot 1: targets.py; 115 tests and ruff pass)
  - Files: create `src\gym_coach\targets.py`, `tests\test_targets.py`.
  - Done when: tests pass for the formula on the made-up profile, including: the weekly loss
    implied by the deficit never exceeds 1% of body weight; protein is 1.8 g per kg of body
    weight; targets recompute when a new body weight is stored.
  - Notes: resting energy by the Mifflin-St Jeor formula, activity factor 1.4, deficit 400 kcal
    a day, capped by the 1% rule. Pure code, no model call. Reads weight from the latest `body`
    row, falling back to the profile.

- [x] **Task 13: meal photo estimates** needs: Task 12 (beside earlier phases) (ticked 2026-11-16, slot 1: meals.py, photo and text meals, meal_correction intent; 123 tests and ruff pass)
  - Files: create `src\gym_coach\meals.py`, `tests\test_meals.py`; modify
    `src\gym_coach\router.py`.
  - Done when: tests pass with the fakes: a photo message leads to one fast-model call with
    the image, one `meals` row, and a reply like "About 650 kcal, 35 g protein (chicken rice).
    Today: 1,420 of 2,000 kcal, 78 of 130 g protein."; a caption ("half portion") is passed to
    the model; "that was 400 kcal" corrects the last meal; no image bytes are written to disk.
  - Notes: use the Telegram photo size chosen in Task 3. A text-only meal ("had two eggs and
    toast") is logged the same way; add the `meal` intent to the router. The reply says
    estimates from photos are rough.

- [x] **Task 14: weekly body numbers** needs: Task 13 (beside earlier phases) (ticked 2026-11-16, slot 1: Monday 07:00 prompt, body intent with 5 kg check; 131 tests and ruff pass)
  - Files: modify `src\gym_coach\router.py`, `src\gym_coach\scheduler.py`; create
    `tests\test_body.py`.
  - Done when: tests pass: Monday 07:00 sends one prompt for weight and waist; "81.6 kg, waist
    91" stores one `body` row; a weight more than 5 kg from the last one is questioned before it
    is stored.

- [x] **Task 15: ceiling check end to end** needs: Task 13 `[parallel-ok]` (beside earlier phases) (ticked 2026-11-16, slot 2: 124 tests and ruff pass)
  - Files: create `tests\test_ceiling_e2e.py`.
  - Done when: the test seeds `api_calls` to US$5.00 for the month, sends a photo and a report
    through the router with the fakes, and asserts that no model call happens and both replies
    state the limit; `/cost` still works.

- [x] **Task 14b: the weekly check-in asks for weight only** `[parallel-ok]` (Brian restarted the bot; log: "bot started" 2026-11-17 00:41, after the code commits of 00:26 and 00:35, no error after except Telegram connection retries; checked by the orchestrator)
  - Files: modify `src\gym_coach\scheduler.py` (the Monday prompt), `src\gym_coach\router.py`
    (the "did not catch your weight" reply and the router prompt's wording), `tests\test_body.py`.
  - Done when: tests pass: the Monday 07:00 prompt and the "did not catch" reply name body weight
    only and give the example "81.6 kg"; "81.6 kg" stores one `body` row; "81.6 kg and 91 cm
    round the middle" still stores both numbers (the column and the stored rows stay). Then
    restart the bot through its scheduled task, as in Task 9k, and read `data\bot.log`: "bot
    started" and no error after it.
  - Notes: Brian, 2026-11-17: "gym: drop it" (the waist question). No change to the database
    schema and no stored row is removed.

- [x] **Task 14c: exercise messages without the form tip** `[parallel-ok]` (Brian restarted the bot; log: "bot started" 2026-11-17 00:41, after the code commits of 00:26 and 00:35, no error after except Telegram connection retries; checked by the orchestrator)
  - Files: the module that builds each exercise message caption (find the form cue that is cut at
    about 150 characters) and its tests.
  - Done when: tests pass: an exercise message caption holds the task line (name, sets, reps,
    weight) and no form tip; one setting (default off) turns the tip back on, with a test for
    each state. The stored tips stay in the data. The bot restart follows Task 14b's (same
    scheduled task); if the restart is refused, mark the task waiting on Brian's restart.
  - Notes: Brian, 2026-11-17: "gym: tip can be for later, drop it for now, and reconsider when I
    request".

- [x] **Task 14d: the form tip is back, as one short line** `[parallel-ok]` (done 2026-11-17: Brian re-registered and restarted the task (Brian: "bot started"); orchestrator read data/bot.log: "starting (pid 14848)" 15:21:48.477, "bot started" 15:21:48.777, "claude client ready" 15:21:50; task priority 4) (was waiting: Brian's restart, 2026-11-17: code and tests done, 151 tests and ruff pass; restart through the scheduled task refused by the auto-mode check; orchestrator or Brian restarts `gym-coach-bot` and checks data/bot.log shows "bot started" after the commit)
  - Why: Brian, 2026-11-17: "gym tip: if it's just one line it's okay" (after seeing that the tip is one line of text under the exercise line).
  - Files: the caption builder (`src/gym_coach/albums.py`), the tip source (`src/gym_coach/illustrations.py`, `CUE_CHARS`), the setting from Task 14c, their tests.
  - Done when: tests pass: with the default settings an exercise caption is the task line plus one tip line; the tip is the first instruction sentence, cut at a word end to at most 60 characters with "..." when longer (60 is the orchestrator's call for one line on a phone; Brian may change it), and holds no line break; the Task 14c setting still turns the tip off. Then restart the bot through its scheduled task and check `data/bot.log` shows "bot started" after the commit and no error; if the restart is refused, mark the task waiting on Brian's restart.

- [x] **Task 14e: the bot hangs at start and writes no log line (bug; the bot is down)** (opus) `[parallel-ok]` (done 2026-11-17: Brian re-registered and restarted the task (Brian: "bot started"); orchestrator read data/bot.log: "starting (pid 14848)" 15:21:48.477, "bot started" 15:21:48.777, "claude client ready" 15:21:50; task priority 4) (was waiting: Brian's restart, 2026-11-17: cause found and fixed, 157 tests and ruff pass. Cause: the logon task runs at Task Scheduler priority 7 (below-normal CPU, low disk) and `build()` imported the anthropic SDK (2,824 modules) before "bot started"; on the busy PC pid 28844 was still in that import after 48 min, while a normal-priority start on a copy of the data logged "starting" at +0.2 s and "bot started" at +0.7 s. Fix: `boot.py` writes "starting" before the heavy imports, the Claude client loads lazily in a background thread, the install script sets `-Priority 4`. No network call is made during start. Restart refused by the auto-mode check: Brian runs `Stop-ScheduledTask gym-coach-bot`, then `scripts\install-logon-task.ps1`, then `Start-ScheduledTask gym-coach-bot`; orchestrator checks data/bot.log shows "starting" then "bot started" within 2 minutes, twice in a row)
  - Symptom (orchestrator, 2026-11-17): Brian stopped and started the scheduled task `gym-coach-bot`; the new copy (`pythonw.exe -m gym_coach`, pid 28844, started 13:50:42) was alive 17 minutes later with 375 ms of CPU time, 25 MB, 2 threads, and `data/bot.log` has no line after 13:41:51 (the old copy's last warning) and no "bot started". The old copy is gone; `Test-NetConnection api.telegram.org -Port 443` succeeds; the task state is Running. The start of 00:39 on 17 Nov took 98 s to its "bot started" line. `main()` in `src/gym_coach/app.py`: lock, `setup_logging`, `build`, then the log line, so it hangs in imports, the lock, logging setup or `build` (which may fetch the illustrations catalogue or call the network without a timeout). The PC is busy (many workers, queue jobs; the repo is under OneDrive).
  - What: find where it hangs (for example `py-spy dump` on the live pid, or `python -X importtime -v -m gym_coach` with a separate data folder and a fake token so the real lock, database and chat are not touched), fix the cause, and make the start log its first line before anything that can block ("starting", then "bot started"), with a timeout on every network call made during start. A failing test first where the cause can be tested.
  - Done when: after a restart of the scheduled task, `data/bot.log` shows "bot started" within 2 minutes of the process start, twice in a row, and no error after; tests and ruff pass. If the worker's restart is refused, mark the task waiting on Brian's stop and start (`Stop-ScheduledTask gym-coach-bot`, then `Start-ScheduledTask gym-coach-bot`), and say so in the ENDED message. It must be up before 07:00 on 18 Nov (next session message).

- [ ] **Task 14f: replies and pictures get lost when a Telegram call fails (bug, live)** (opus) `[parallel-ok]` (waiting: Brian's restart, 2026-11-17: code done, 172 tests and ruff pass; restart refused by the auto-mode check, orchestrator asked Brian and does the 2-hour bot.log check. (1) every send (text, album, single picture, file download) tries 4 times, pauses 1, 3, 8 s, only on ConnectError/ConnectTimeout/PoolTimeout (the request never left the PC), so an answered send is never repeated; the poll keeps its own 5 s pause. (2) `handle`: the reply, the exercise message and each picture part are guarded separately; a failed album falls back to its text, a failed reply still lets the exercise go out, a failed photo download answers "send it again". The "failing album still sends the text" test passed before the change (send_parts already fell back); the other three failed first. (3) Cause, 200 getMe calls per variant from this PC: a new connection per call failed 28 and 26 of 200 (IPv4-bound and default) in the TLS handshake, `SSL: UNEXPECTED_EOF_WHILE_READING`, median 0.84 to 0.85 s; a kept connection failed 0 of 200 (both), median 0.28 s. IPv4 = default: curl -6 cannot connect, no IPv6 route. DNS is a VPN's (103.86.96.100), so the cut is likely on that path (inferred). Kept: one kept connection, 30 s idle expiry (`new_http_client`); errors now log the cause text with the token removed. (4) log lines `received text (N chars)` / `received photo (caption N chars)` and `replied: M messages, P pictures, S s after receipt`. (5) the catalogue files lat pulldowns and low rows under cable: `kinds_of` adds cable for pulldown/low-row towers, ties prefer the closer name and two-handed variants; 'Lat pulldown' -> Wide-Grip Lat Pulldown, 'Seated low row' -> Seated Cable Rows, written into the stored sessions 19-29 Nov (illustration key only, no model call). (6) on the board. ConnectError lines today before the fix: 133 in 17.5 h, about 8 an hour; count after the restart to be written beside it by the orchestrator)
  - Brian, 2026-11-17 17:10: "Please check gym project, app not behaving nirmally". Facts from
    `data/bot.log` (orchestrator, 17:12): the bot runs (started 15:21:48) and its Claude calls
    answer 200, but calls to Telegram fail now and then with `ConnectError`: 221 such lines in
    the log, 33 since 15:00 today. A failed poll is tried again, a failed send is not:
    17:09:26 `handling a message failed ... sendMessage failed: ConnectError` (`app.py` line 58:
    the reply was built and then dropped, he got nothing); 17:10:57 `sending pictures failed;
    sending the text ... send album failed: ConnectError` (pictures dropped). From the same PC,
    six plain `curl https://api.telegram.org/` calls at 17:14 all connected in under 0.05 s, so
    the line is not down; the failures are short and come and go. The log holds no line for a
    message received or sent, so nobody can tell from it what he asked and what he got.
    Replies are also slow: one message makes two to five Claude calls, up to 37 s apart.
  - Files: `src/gym_coach/telegram.py`, `src/gym_coach/app.py`, their tests, the planner where
    it logs `has no illustration`.
  - Do: (1) every send (`sendMessage`, album, single picture, file download) tries again on a
    connection error: 4 tries, pauses 1, 3, 8 s, then raises; a send is never repeated once
    Telegram answered. (2) In `handle`, a failure of one part (pictures, the exercise message)
    never stops the text reply from going out. (3) Find why connecting fails so often and say
    it in the plan line with the evidence: log the cause text of the error (never the URL, it
    holds the token); test IPv4 against IPv6 for api.telegram.org (a transport bound to
    `0.0.0.0` forces IPv4) and one new connection per call against a kept one; keep what
    measures better over 200 calls to `getMe`. (4) Log one line per message received (kind and
    length only, no text) and per reply sent (parts, pictures, seconds from receipt to last
    send). (5) 'Lat pulldown' and 'Seated low row' have no picture: give them one from the
    stored set or say in the plan line why none fits. (6) Report where the seconds of a slow
    reply go (count and time of the Claude calls for one "next" during a session); change
    nothing there, write it on the board for Brian.
  - Done when: failing tests first: a send that fails twice and then works delivers once; a
    failing album still sends the text; a failing exercise message still sends the reply.
    Tests and lint pass. Then restart the bot through its scheduled task `gym-coach-bot` (if
    the restart is refused, ask the orchestrator: Brian runs it) and read `data/bot.log`: over
    the next 2 hours with at least one exchange, no `handling a message failed` and no
    `sending pictures failed` without a later successful send, and the count of
    `ConnectError` lines per hour written beside today's (about 8 an hour).

- [ ] **Task 14g: what the 17 Nov session shows beyond lost sends (bug, live)** (opus) `[parallel-ok]` (waiting: next real session, Thu 19 Nov; code on main and bot restarted 17:40:39 on it; orchestrator reads the `chat` table and `data/bot.log`)
  - Brian, 2026-11-17: "Can you see the conversation? If so you should be able to figure out
    along with the gym app trace and log". The bot keeps no message text and the orchestrator
    cannot read his Telegram, so the session was rebuilt from `data/gym.db` (read-only) and
    `data/bot.log`. Facts (checked 17:25):
    - Three replies were dropped in eight minutes (17:09:26, 17:15:21, 17:17:02) and one set
      of pictures (17:10:57). Each dropped reply came after the work was done: a report is
      saved, the reply saying so never arrives, so he cannot tell whether to send it again.
    - `kv flow:2026-11-17` = 2 (Lat pulldown is "shown") yet two sets of Lying leg curl
      (index 3) are logged and Lat pulldown has 2 of 3 sets; Machine shoulder press and Seated
      cable row have none. The session row says `done` since the first set
      (`reports.py` line 43), with 10 of 18 sets logged.
    - 17:10:41 and 17:10:44: two Opus calls (14,555 and 16,292 input tokens) wrote a whole new
      proposed week, 23 to 29 Nov, in the middle of the session: a message of his was read
      as "change the plan". Most likely (inferred, not seen) he asked to change an exercise of
      today's session.
  - Files: `src/gym_coach/router.py`, `src/gym_coach/reports.py`, `src/gym_coach/store.py`,
    `src/gym_coach/app.py`, `src/gym_coach/prompts.py`, their tests.
  - Do: (1) keep the chat: one table in `data/gym.db` (git-ignored) with time, direction,
    text, and whether the send reached Telegram; rows older than 30 days are removed
    (orchestrator's call, 2026-11-17; Brian may change it). (2) A reply that could not be
    delivered within Task 14f's tries is kept and sent first when the next send works,
    marked "(late)". (3) While a session is on, a request to change an exercise changes
    today's session only (swap or drop that exercise, keep the logged sets) and never writes
    a new week; a new week is proposed only on `/propose`, or on a change request when a
    proposed week is waiting. Before writing code, write the three to five message kinds he
    could have sent at 17:09 to 17:10 and what each should do, in the plan line. (4) The
    exercise "shown" follows what he reports: a set for a later exercise of today moves the
    pointer there, and exercises with sets missing are listed at "Session done" instead of
    being passed over in silence. (5) The day is marked `done` when the flow closes or at
    the evening report, not at the first set. (6) The proposed week 23 to 29 Nov stays as it
    is: only Brian approves or drops it.
    (7) The bot reads each message with the session in view (Brian, 2026-11-17: "It seems
    to me the Telegram bot has no context and cannot read previous messages, please fix that
    because if missed message it messes everything without the capability to handle session
    messages"). Checked: `router._handle` gives the model the one message alone, and
    `_answer` adds only the profile and today's plan. From now on every model call that
    reads a message (the sorting call and the answer) also gets: the last 12 chat lines of
    today from the chat table of (1), each bot line marked delivered or not delivered;
    today's session with the sets logged per exercise and the exercise now shown. The
    sorting prompt says so: a short message ("same again", "35 12", "the other one", "I
    already told you") is read against those lines; a report that repeats one whose reply
    was not delivered is not logged twice (the bot answers with the state instead); when
    the message cannot be placed, the bot asks one short question and changes nothing.
    Keep the fast model for sorting; write the added tokens per message on the board.
  - Message kinds at 17:09 to 17:10 and what each does (slot 1, 2026-11-17, before code):
    - "can I do seated row instead of lat pulldown, it's taken": swap that exercise in today's
      session (equipment must be on today's gym list, else one short question); its logged
      sets stay; the new exercise gets the sets still to do and the same rep range; if it was
      the exercise shown, the new one's message goes out.
    - "drop the shoulder press, my shoulder hurts": drop it from today's session (kept with
      the sets already logged, if any); the next exercise is shown if it was the one shown.
    - "35 is too heavy for leg curl, make it 30": today's weight for that exercise changes.
    - "less leg work next week" (a change to a future week): with a proposed week waiting it
      revises that week; without one it is kept as a note, the reply says so, and the next
      `/propose` uses it. No new week is written.
    - "what can I do instead of lat pulldown?" (a question): answered, nothing changes.
  - Orchestrator, 2026-11-17: (5) the day is `done` when the flow closes, or by a silent
    21:00 job for an approved strength day with sets logged. The task ends waiting on the
    next real session (orchestrator reads the chat table and bot.log).
  - Done when: failing tests first for (2) to (5). Tests and lint pass. Restart the bot
    through its scheduled task (if refused, ask the orchestrator), then in the next real
    session read the chat table and `data/bot.log` (tests for (7): a repeated report after
    an undelivered reply logs once; "same again" logs the last set again): every message of his has a delivered
    reply, the pointer matches the sets logged, and no new week appears unless he asked.

- [ ] **Task 14h: Brian's 17 Nov list: traces, photo kinds, own exercises, no surprise weeks, faster replies (bug, live)** (opus) (Brian's direct instructions, 2026-11-17 evening; built in his chat session, not by a worker)
  - Brian, 2026-11-17: "the image is supposed to be a gym query but the bot confuses it as
    meal. Please fix that"; "the bot should also save chat history for debugging purpose, not
    just the interpreted set. What if I made a typo"; "fix slow replies"; at the third lat
    pulldown set "last same set done" got "today's full-body session is done"; "Lying leg curl
    and shoulder press and cable now missing" got a whole new week ("Home gym, Tue 24 Nov");
    "it keeps asking me for Lat pulldown when I've already done them"; "if you cannot see [the
    replies], you should work on adding logs and traces in database".
  - Already done by hand (chat session, 17 Nov; db backed up to
    `data/gym.db.bak-17nov-fix`): Lying leg curl set 4 (a copy of set 1) deleted; his own
    exercise "Plate halo" (10 kg plate, 3 x 10) added to today's session and logged; the
    weight-plate photo stored as a 0 kcal meal deleted.
  - Files: `src/gym_coach/router.py`, `app.py`, `store.py`, `meals.py`, `llm.py`,
    `telegram.py`, `reports.py`, a new `scripts/show_chat.py`, their tests.
  - Do:
    (1) Keep the chat for good (Brian wants it for debugging): drop the 30-day prune.
    (2) A trace per incoming message in `data/gym.db`: the chat row it answers, what the bot
    understood (intent and the parsed JSON, or "local" when no model call), each model
    call's seconds, the total seconds to the reply, any error. A trace failure never stops
    the reply. `scripts/show_chat.py --day YYYY-MM-DD` prints the chat with its traces, so a
    misread or a typo can be found. Each logged set also gets a save time (a `saved_at` column
    on `logged_sets`, added to the existing db on start, old rows left empty), which
    `show_chat.py` prints in time order (Brian approved, 2026-11-17; the rest of the
    orchestrator's "what each message changed" addition is on hold).
    (3) A photo is not always a meal. With a caption, the caption is read like a text (the
    sorting call is told a photo came with it); only a meal intent sends the image to the
    meal estimate. Without a caption, the image call says meal or not; a non-meal is never
    stored as a meal and the bot asks what it is.
    (4) His own exercises: a set for an exercise that is not in today's session and is not a
    clear match for one (the sorting call says so) is logged under its own name and added to
    today's session (marked `"own": true`), never relabelled as the shown exercise.
    (5) A message saying sets are missing or the log is wrong ("X and Y now missing") gets
    today's log and what is missing, changing nothing; it is never a plan change.
    (6) No surprise weeks: a chat message never writes or revises a week by itself. A
    future-week change with a proposed week waiting asks "Revise the proposed week D1 to D2
    with: <change>? Reply yes." and revises only on yes; while today's strength session is
    open (approved, not done) it is only kept as a note for `/propose`.
    (7) A set reported for an exercise other than the one shown: the reply names the
    exercise logged and its sets, then "Now: <shown exercise>"; the pointer still follows
    later exercises (Task 14g); the session closes only when no exercise has sets left.
    (8) Typos: the reply echoes what was logged; a weight over 1.5 times or under half the
    plan or the last set of that exercise adds "Typo? Reply with the right number."
    (9) Faster replies: send Telegram's "typing" action on receipt; a plain set report for
    the shown exercise ("35 12", "35kg 12 12 10") is read locally with no model call; photos
    are shrunk to at most 1024 px before an image call. Measure receipt-to-reply seconds per
    message kind before and after, and write them on the board.
  - Done when: failing tests first for (2) to (8); tests and lint pass; the bot restarted on
    the new code; one real message checked in the chat and trace tables.

- [ ] **Task 14i: the whole workout in view (bug, live)** (opus) needs: Task 14h (same files)
  - Brian, 2026-11-17: "I've already proposed for the bot to keep history, at least throughout
    the gym session. I can prompt to start the session which has context"; on how a workout
    starts: "sure, default, it should intelligently pick up if gym session has already
    started". Checked: Task 14g gives each model call only today's last 12 chat lines; on
    17 Nov he sent about 40 messages in the workout.
  - Do: (1) A workout opens on "start", or on its own when a message shows the workout has
    begun (a set, or a question about one of today's exercises). The open time is kept.
    (2) While it is open, every model call that reads a message gets every chat line since
    it opened (not 12), plus the sets saved and the current exercise. (3) It closes when no
    exercise has sets left, on "end", or at the 21:00 close. (4) Each message's trace
    records the current exercise after it. Measure the added tokens and cost for a 40-message
    workout and write them on the board.
    (5) Brian, 2026-11-17: "photo that sits within the gym session after start command is
    never a meal picture, always a query": while a workout is open, a photo is never sent to
    the meal estimate; it is read as a question or report about the workout.
    (6) Brian, 2026-11-17: "it should only ask to plan the week AFTER the current week is
    completed": the bot asks to plan or revise next week only once this week's last planned
    session is done or skipped (or its day has passed); before that a week change is kept as
    a note. (Inferred, to confirm: `/propose` typed by Brian still works at any time.)
    (7) Repeat Telegram's "typing" action every 4 s until the reply is sent (it shows for
    about 5 s only).
    (8) Brian, 2026-11-17, on "X and Y now missing": "the bot should be able to intelligently
    pick up that either something went wrong with the messages it sends or I misread it. It
    should verify which is the case, and self correct if I am right or ask if I misread".
    The bot checks his claim against the workout's chat and the saved sets. If he reported
    sets in the chat that were never saved (or were saved wrong, or a reply never arrived),
    it saves or fixes them and says what it changed. If the sets are saved as he reported
    them, it shows them and asks whether he misread. Replaces Task 14h's "log_check" reply,
    which only showed the log.
    (9) The sorting call's JSON leaves out empty fields (about half a second per message).
  - Done when: failing tests first; tests and lint pass; the bot restarted; the next real
    workout checked in the chat and trace tables.

- [ ] **Task 14j: warm-up first, stretching last, a button to finish** (opus) needs: Task 14i (same files)
  - Brian, 2026-11-17: "at the end of the session, the bot should remind me to do stretching,
    and when I am done there should be a simple way to close the gym session"; "I find that I
    am not sweating enough during the last gym session. Please include warm up exercises such
    as bear walk to enable warmup fully".
  - Do: (1) Every strength session starts with a warm-up, sent right after the day's list and
    before the first exercise: a fixed routine of about 8 minutes that needs no equipment
    (bear crawl, jumping jacks, high knees, arm circles, bodyweight squats; times or reps
    each), kept in one list in the code so it is easy to change. Its sets are not logged; the
    first exercise follows when he says he is done with it (or reports a first set).
    (2) When the last exercise is done, the bot reminds him to stretch (a short list of
    about 5 minutes for the muscles of the day) and shows a Telegram reply-keyboard button
    "Finish session". The button sends a normal text; the bot then closes the workout (Task
    14i's close), sends the summary, and removes the button. Typing "finish" or "end" works
    the same. The 21:00 close still closes a workout he never finished.
  - Done when: failing tests first; tests and lint pass; the bot restarted; the next real
    workout checked in the chat and trace tables.

- [x] **Task 14k: planned weights come from what he last lifted** (opus) `[parallel-ok]` (slot 1 only)
  - Asked by Brian, 2026-11-24: "curious for the gym coach app would it use my previous weight to recommend current weight"; told that it does not, and offered a task: "please do." Then: "also it should be able to retrieve past reps for the same task" (the reps of each earlier set of the same exercise, not the weight alone: in the history the planner reads, in the last-time line, and when he asks the coach what he did before).
  - Found by the orchestrator in the code: `planner.propose` gives the model the profile, the equipment lists, the dates and the week's earlier proposal only; `router.context` gives the workout coach today's sets only. `store.logged_sets(date)` holds every earlier set but nothing reads the earlier days back.
  - Files: modify `src/gym_coach/store.py`, `planner.py`, `router.py` (and `coach.py` if the wording of the prompt needs it), with their tests.
  - Do: (1) a store reader that returns, per exercise (matched by the same name key the log uses), the sets of the last 3 days it was logged on (date, weight, reps per set). (2) The week proposal's prompt carries that history for every exercise logged in the last 8 weeks, and tells the model: start an exercise he has done before from his last logged weight; raise it by the smallest step the equipment allows only when he reached the top of the rep range on every set last time; keep it when he did not; lower it when he missed the bottom of the range; an exercise with no history gets a weight from the profile as now. The proposal message says in one short line per changed exercise why the weight moved. (3) During a workout, today's session lines in the coach's context show, per exercise, what he did last time ("last: 35 kg x 10, 10, 8 on 19 Nov"), so the coach can answer "what did I lift last time" and suggest a weight. (4) No stored set is changed; an already approved week is not rewritten.
  - Done when: failing tests first, then tests prove (1) to (4) with a stub model (the prompt text holds the history lines; an exercise with no history has none; the context shows the last-time line); pytest and ruff pass; the bot restarted through its scheduled task `gym-coach-bot` and `data/bot.log` shows "bot started" after the commit with no error for 3 minutes. If the permission check refuses the restart, do not retry: mark the task waiting and tell the orchestrator.
  - Notes: the raise and lower rules are the orchestrator's call (2026-11-24; Brian may change them). Tasks 14h to 14j are built (in Brian's chat session) though unticked, so this task does not wait on them. The orchestrator asks Brian to look at the next proposed week.

- [x] **Task 14l: the day's weights follow his last session, also for a week planned earlier (bug, live)** (opus) `[parallel-ok]` (slot 1 only) (done 2026-11-24, slot 1: `weights.py` sets the weight by the 14k rule; `Router.plan`, the coach and the 07:00 list read sessions through it; today's weights are written into the stored session once (kv `weights:<day>`) so a weight he sets before his first set stays; the week proposal applies the same function and its message lists each moved weight. Step and matching rules are the orchestrator's calls of 2026-11-24 (decisions.md); slot 1 narrowed equipment matching to machines after the live print showed "Incline dumbbell press" taking the flat bench press's sets. 368 tests pass (347 before; 21 new in `tests/test_14l.py`; one 14k test's made-up data put three exercises on one machine and now gives each its own, and two 14k lines changed wording), ruff clean; the 5 wiring tests fail on the old code. Bot restarted through `gym-coach-bot`: "bot started" 18:24:59, no error after for 3 minutes. Live db read-only, 26 Nov: Lat pulldown 42 kg (up from 35 x 12, 12, 12), Seated cable row 27.5, Shoulder press 28 (from Machine shoulder press), Lying leg curl 35 (home 17 Nov; parents 22 Nov as a note), Dumbbell squat 16, Triceps pushdown 12.5 kept, Incline dumbbell press 10 (no history). Today's 24 Nov session (no set logged) was rewritten by the running bot at 18:25 to Chest press 35, Lat pulldown 42, Seated cable row 27.5, Shoulder press 28, Leg extension 35, Lying leg curl 35, Stiff-legged deadlift 16. Paid calls: none)
  - Symptom (Brian, 2026-11-24, in the gym, after Task 14k went live: "why don't it use last time weight"). The bot's 18:09 schedule for 24 Nov (chat table, read by the orchestrator): "2. Lat pulldown, 25 kg (last time 35 kg x 12)", "3. Seated cable row, 20 kg (last time 25 kg x 15)", "5. Leg extension, 20 kg (last time 28 kg x 15)", "6. Lying leg curl, 15 kg (last time 21 kg x 15)", "7. Stiff-legged dumbbell deadlift, 10 kg (last time 14 kg x 15)"; "1. Chest press, 20 kg" and "4. Shoulder press, 15 kg" show no last time at all.
  - Causes (orchestrator, from `data/gym.db` read-only): (a) the week 22 to 29 Nov was written before Task 14k and Task 14k only changes weights when a week is proposed anew, so every stored session of this week keeps its old weights; (b) the history is matched by exercise name, and the plan says "Chest press" and "Shoulder press" where the sets of 17 Nov are logged as "Machine chest press" (21, 28, 28 kg) and "Machine shoulder press" (21, 21, 21 kg).
  - Files: modify `src/gym_coach/router.py`, `store.py`, `planner.py`, `coach.py` as needed, with tests.
  - Do: (1) One function in code (no model call) gives the weight to use for an exercise from its history by Task 14k's rule (last top weight; one step up when every set of the last day reached the top of the rep range or more; keep otherwise; lower when a set missed the bottom). The step is the smallest gap seen in that exercise's logged weights (the machines here move in 7 kg plates: 21, 28, 35), else 2.5 kg, dumbbells 2 kg. (2) Every strength session not yet started (no set logged that day), proposed or approved, shows and uses that weight for each exercise with history, on the day's list, the exercise card and in the coach's context; the stored planned weight is the fallback for an exercise with no history. The line says where it came from ("35 kg, last time 35 kg x 12, 12, 12" or "42 kg, up from 35 kg x 12, 12, 12"). (3) The same machine is the same exercise: match history by the name key first, then by the same equipment at the same gym (the plan session of the day the sets were logged names the equipment), so "Chest press" finds "Machine chest press". History from the other gym's machine is shown as a note only ("parents gym: 21 kg x 15"), not used for the weight. (4) The week proposal uses the same function, so a newly proposed week and the day's list agree. (5) Stored sets are never changed.
  - Done when: failing tests first; tests prove (1) to (5), among them the 24 Nov case built from the rows above (lat pulldown 35 x 12, 12, 12 gives one step up from 35; seated cable row 20, 22.5, 25 x 15 gives a weight above 25; chest press finds the 17 Nov machine sets); pytest and ruff pass; then restart the bot through its scheduled task `gym-coach-bot` and check `data/bot.log` shows "bot started" with no error for 3 minutes, and with the live database opened read-only print what the 26 Nov session would show (no message sent). If the permission check refuses the restart, do not retry: mark the task waiting and tell the orchestrator.
  - Notes: Brian may be mid-workout on 24 Nov; a restart between his messages is fine (the workout state is in the database). Do not send him a message.

- [x] **Task 14m: read the trend across his sets: struggling or too easy, and recommend accordingly** (opus) `[parallel-ok]` needs: Task 14l (slot 1 only) (done 2026-11-24, slot 1: warm-up first, live at 18:34:17: the coach context always holds the fixed routine and its state, SYSTEM forbids another warm-up, a `start_workout` tool runs `Router._start`, `/today` says the warm-up comes first; 5 tests in `tests/test_14m_warmup.py`. Labels: `weights.read_sets` reads the last day as too easy, steady or struggling by the plan rule plus three orchestrator calls (decisions.md, 2026-11-24): reaching the top counts as over it; struggling stays at the weight where it went wrong, one step under only after two struggling days at that weight; too easy wins when the last set at the day top weight reached the top of the range. The list, card, proposal and coach context show the weight with its reason; the coach sees "today so far: <label>: go up / hold / drop" per exercise; stored sets unchanged. 386 tests pass (373 after the warm-up part; 13 new in `tests/test_14m.py`, 11 of them fail on the old code; 14 older 14k, 14l and session tests changed to the new wording, shoulder press and leg extension cases by the new rule), ruff clean. Bot restarted through `gym-coach-bot` three times (18:34:17 warm-up, 18:40:21 labels, 18:43:33 rule B), "bot started" each time, no error after for 3 minutes. Live db copy, 26 Nov: Dumbbell squat 16, Lying leg curl 35 (28 x 12 felt easy), Incline dumbbell press 10 (no history), Seated cable row 27.5, Shoulder press 28, Lat pulldown 42 (all felt easy), Triceps pushdown with rope 12.5 (reps fell 15, 12, 10). Paid calls: none)
  - Asked by Brian, 2026-11-24: "also it should be able to see from my last rep whether I'm struggling (decreasing rep / weight etc) or if it's too easy (increasing rep / weight)" and "and provide recommendation accordingly".
  - Files: the weight function of Task 14l and its callers (`router.py`, `planner.py`, `coach.py`), with tests.
  - Do: (1) From the sets of the last day an exercise was done (and the two days before it when they exist), code labels the exercise: "struggling" when reps fall from set to set at the same weight by 3 or more in total, or he lowered the weight during the day, or a set ended under the bottom of the rep range; "too easy" when he raised the weight during the day and still reached the top of the range or more on the last set, or every set went over the top of the range; "steady" otherwise. Examples from his log: lying leg curl 22 Nov 21 kg x 15, 12, 10 is struggling; machine chest fly 22 Nov 21, 28, 35 kg x 15, 15, 15 is too easy; dumbbell bench press 19 Nov 12 kg x 12 then 10 kg x 15, 15 lowered the weight. (2) The recommendation follows the label and replaces Task 14l's plain rule where they differ: too easy = start at his last top weight and go one step up; steady = his last top weight, aim for one more rep; struggling = stay at (or one step under) the weight where the reps fell and aim to hold the reps across all sets. The day's list, the exercise card and a newly proposed week show the weight with a short reason ("42 kg: last time 35 kg felt easy, 15, 15, 15", "21 kg again: reps fell 15, 12, 10 last time"). (3) During the workout the coach's context carries the same label for today's sets as they come in, so after a set it can say to go up, hold or drop for the next set. (4) Stored sets are never changed.
  - Done when: failing tests first; tests prove (1) to (4) with the three examples above; pytest and ruff pass; bot restarted through its scheduled task `gym-coach-bot`, `data/bot.log` shows "bot started" and no error for 3 minutes; with the live database read-only, print what the 26 Nov session would show (no message sent). If the permission check refuses the restart, do not retry: mark the task waiting and tell the orchestrator.
  - Added 2026-11-24 18:35 (sent to the worker by message; do this first): Brian, in the gym: "warm up is gone". Chat 18:30: he asked "Warm up?" and the coach made one up; "We used to have a different warmup set". Cause: the fixed warm-up of Task 14j is sent only by the word "start" or the 07:00 flow; a free-text request for the schedule goes to the coach model, which has neither the warm-up text nor a way to start the workout. Do: the coach's context carries the fixed warm-up and its state and never invents another; a coach tool starts the workout as "start" does and returns the fixed warm-up; the day's list says the warm-up comes first while it is not done. Test: "Warm up?" with a stub model gives the fixed routine and sets the warm-up key.
  - Notes: the thresholds are the orchestrator's call (2026-11-24; Brian may change them). Do not send Brian a message.

- [ ] **Task 14n: the coach reports past sets exactly, and his own word on effort beats the rep count (bug, live)** (opus) `[parallel-ok]` (slot 1 only)
  - Symptom (Brian, 2026-11-24, mid-workout: "Currently the app is unable to retrieve that correct, please check our ongoing session"). Chat table, 24 Nov: 18:45:58 he asked "I mean how did last session chest press went"; the coach: "On 17 Nov you did chest press at 28 kg: 12 reps on the first set, then 15 on the second." 18:46:14 "There should be 3 sets"; the coach answered about today's 3 sets. 18:46:40 "17 Nov 28kg x12 then x15, that's only 2 sets"; the coach: "You're right, last time's log shows only two chest press sets". 18:46:52 "That's a mistake"; the coach repeated two sets. The record (`logged_sets`, 17 Nov, Machine chest press) has three: 21 kg x 15, 28 kg x 12, 28 kg x 15. Also 18:44:39 and 18:44:56: after "35kg x15 done" the coach called it "too easy" and said to aim for 8-12; he answered "Today is not easy, I barely managed, will probably only do 12 for second set". And "How did my last session go", asked while on the chest press, got a recap of every exercise of three days.
  - Cause to prove (orchestrator's reading): the history line the coach sees is "21 kg x 15; 28 kg x 12, 15", which the model reads as two sets at 28 kg and drops the first; nothing tells it to list every set or to check the record before agreeing with a correction; the too-easy label looks at reps only.
  - Do: (1) Past sets reach the coach (context line and the `past_sets` tool) one per set with its number and the count: "17 Nov, 3 sets: set 1 21 kg x 15, set 2 28 kg x 12, set 3 28 kg x 15". The card's short line may stay short. (2) System text: when he asks about an earlier day, list every set from the record with its weight and reps, call `past_sets` when the context does not hold it, never say a set count or number that the record does not show, and never agree that the record is different without reading it again; when the record and his memory differ, say what the record holds and ask whether to correct it. (3) While an exercise is in progress, "last session" / "last time" means that exercise unless he names another or says the whole session. (4) His own word on effort wins: "barely", "hard", "struggled", "easy", "too light" and the like are saved as the set's effort (the column exists) and the label and next-set advice follow it over the rep count (35 kg x 15 "barely managed" is not too easy: hold); with no word from him and reps over the top of the range the coach asks how it felt in a few words instead of calling it easy. The effort saved also feeds the next session's recommendation. (5) A tool to correct a set of an earlier day (date, exercise, set number, weight, reps; or add / remove a set) that states the old and new values, so he can fix a wrong record by saying so.
  - Done when: failing tests first; tests prove (1) to (5), among them the 17 Nov chest press case with a stub model (the context holds three numbered sets) and the 35 x 15 "barely managed" case (effort saved, label not too easy); replay the six messages 18:44:51 to 18:46:52 through the real coach model on a copy of the database (paid, a few cents; write the cost on the board) and paste the replies in the board note: each must name three sets for 17 Nov; pytest and ruff pass; bot restarted through its scheduled task, `data/bot.log` shows "bot started" and no error for 3 minutes. If the permission check refuses the restart, do not retry: mark the task waiting and tell the orchestrator.
  - Notes: Brian is mid-workout; restart between his messages. Do not send him a message.

- [ ] **Task 16: live check of meals** needs: Task 13, Task 14 (slot 1 only) (checkpoint) (waiting: inbox, 2026-11-16: bot restarted through the scheduled task at 15:31 on the Task 12-14 code, log clean; Brian sends one real meal photo at a real meal or session, question in docs/inbox.md. Slot 1 never committed this mark; the orchestrator restored it)
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
