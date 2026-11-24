# Board: gym-coach

## Workers
- slot 1: Task 14m, labels built and live; waiting on the orchestrator for one rule question

## Ready to build

## Waiting on Brian

## Done and carried over
- Task 14l, the day's weights follow his last session (`weights.py`, `router.py` `plan`, `coach.py`, `scheduler.py`, `planner.py`, `messages.py`): done 2026-11-24 (slot 1). One function in code sets each planned weight from his last day by the 14k rule (step: own gap, else same equipment, else the gym's commonest machine gap, home 7 kg; else 2 / 2.5 kg); every strength session not started shows and uses it, with where it came from ("42 kg (up from 35 kg x 12, 12, 12 on 17 Nov)"); "Chest press" finds "Machine chest press"; the other gym's machine is a note. 368 tests pass (347 before; 21 new in `tests/test_14l.py`), ruff clean. Bot restarted 18:24:59, no error for 3 minutes. Today's 24 Nov session now reads Chest press 35, Lat pulldown 42, Seated cable row 27.5, Shoulder press 28, Leg extension 35, Lying leg curl 35, Stiff-legged deadlift 16. Paid calls: none. Note for Brian: by the rule every 17 Nov set at 12-15 reps moves one full 7 kg plate up (Lying leg curl 28 -> 35 though 22 Nov at his parents' fell to 10 reps at 21 kg); Task 14m reads the trend.
- Task 14k, planned weights from what he last lifted (`store.py recent_sets`, `planner.py`
  history and weight-change lines, `prompts.py`, `router.py` last-time line, `coach.py`
  `past_sets` tool): done 2026-11-24 (slot 1). The week proposal's prompt lists, per exercise
  logged in the last 8 weeks, its last 3 days (weight x reps per set, the plan's rep range);
  the model starts from the last top weight and raises, keeps or lowers it by the rep-range
  rule; the proposal message adds one line per changed weight with why. During a workout
  each exercise shows "last: 35 kg x 10, 10, 8 on 19 Nov"; the coach can look up any
  exercise's earlier days. A proposal over a week with an approved or done session is
  refused. 347 tests pass (335 before; 12 new in `tests/test_14k.py`), ruff clean. On a copy
  of the real db the history block lists 18 exercises (17-22 Nov). Bot restarted through
  `gym-coach-bot` at 18:02:05, "bot started", no error after for 3 minutes. Paid calls:
  none. Brian looks at the next proposed week.
- Task 14j, warm-up first, stretching last, a "Finish session" button (`messages.py`
  `WARM_UP` and `STRETCHES`, `scheduler.py`, `router.py`, `app.py`, `telegram.py`
  `reply_markup`): code on main 2026-11-17, not ticked; waits on a bot restart and the next
  real workout checked in the `chat` and `trace` tables. 263 tests pass (250 before; 13 new
  in `tests/test_14j.py`; 7 older tests now expect the warm-up and the button), ruff clean.
  No model call added. Paid calls: none.
- Task 14i, the whole workout in view (`router.py`, `app.py`, `store.py`, `reports.py`,
  `scheduler.py`, `scripts/show_chat.py`): code on main 2026-11-17, not ticked; waits on a bot
  restart and the next real workout checked in the `chat` and `trace` tables. 250 tests pass
  (223 before; 27 new in `tests/test_14i.py`; the 14h missing-sets test now expects the
  check call), ruff clean. Added cost, on fakes (a made-up 40-message workout: 24 set reports
  and 16 questions, 56 model calls; tokens estimated as characters / 4): the workout view adds
  about 20,600 input tokens over the 12-line view (48,300 to 68,800); the largest call grows
  from about 1,000 to 1,900 tokens; about US$0.002 added per workout at Haiku's price. A
  missing-sets message costs one more Haiku call. Shorter sorting JSON: the one real sorting
  reply in the `trace` table used 178 output tokens (299 characters); a trimmed set report
  is about 40 (inferred, not measured on the real model). Paid calls: none.
- Task 14h, Brian's 17 Nov list (traces, photo kinds, own exercises, no surprise weeks,
  faster replies): code on main 2026-11-17, not ticked; waits on a bot restart and one real
  message checked in the `chat` and `trace` tables. 227 tests pass (197 before; 33 new in
  `tests/test_14h.py`, 3 superseded 14g tests removed), ruff clean. Seconds from receipt to
  reply: before, real, from `data/bot.log` and the `chat` table: photo with caption 14.7 s
  (one sample; no real text timings exist before the trace). After, with fakes (no network):
  number-only set report 0.06 s with no model call; set report in words 0.09 s plus its one
  fast model call; photo 0.06 s plus its image call. After, real: one image call on a made-up
  1024 px picture took 1.67 s (1,254 input tokens, US$0.00014). Real after-numbers per kind
  come from the `trace` table once the bot runs the new code.
- Task 3, Telegram client: done 2026-11-13 (slot 4). 8 tests for it pass, ruff clean.
- Task 2, record storage (`store.py`): done 2026-11-13 (slot 2). 15 tests and ruff pass.
- Task 1, project skeleton and environment: done 2026-11-13 (slot 1). Conda env `gym-coach`
  built; 9 tests and ruff pass.
- Task 5, gym for the day and coach context: done 2026-11-13 (slot 3). 8 tests pass, ruff clean.
- Task 4, Claude wrapper with cost ceiling (`llm.py`): done 2026-11-13 (slot 1). 40 tests pass, ruff clean.
- Task 6, first schedule and plan proposal (`planner.py`, `prompts.py`): done 2026-11-13 (slot 1). 48 tests pass, ruff clean.
- Task 7, message router and report logging (`router.py`, `reports.py`): done 2026-11-13 (slot 1). 62 tests pass, ruff clean.
- Task 8, daily session message and scheduler (`scheduler.py`, `messages.py`): done 2026-11-13 (slot 1). 72 tests pass, ruff clean.
- Task 9, main program and logon start (`app.py`, `__main__.py`, `scripts\`): done 2026-11-13 (slot 1). 79 tests pass, ruff clean. Logon task not registered: Brian runs `scripts\install-logon-task.ps1` himself.
- Task 9a, bot pairs with the first private sender (`telegram.py`, `config.py`): done 2026-11-13 (slot 1). 83 tests pass, ruff clean; `--check` prints "config ok (owner not paired yet)".
- Task 9b, bot hang and Stop-ScheduledTask leftover: code fixed 2026-11-13 (slot 1), 87 tests pass, ruff clean. Not verified against real Telegram (orchestrator's order); waiting for Brian to restart the bot, orchestrator checks bot.log.
- Task 9c, /start proposes the first week (`router.py` `/propose`): done 2026-11-13 (slot 1). 88 tests pass, ruff clean. Not run on the real bot: Brian restarts it, orchestrator checks.
- Task 9d, Stop-ScheduledTask really ends the bot: done 2026-11-13 (slot 1). The logon task now starts `pythonw.exe -m gym_coach` directly (no powershell/conhost); 86 tests pass, ruff clean. Not run on the real task: Brian stops the old bot, re-runs `scripts\install-logon-task.ps1`, orchestrator checks.
- Task 9e, session messages list every exercise and show the machine photos (`albums.py`, `messages.py`, `telegram.py send_album`): done 2026-11-13 (slot 1). 97 tests pass, ruff clean; real photos shrink fine in a local check. Not run on the real bot: Brian runs `pip install -e ".[dev]"` (Pillow) and restarts it, orchestrator checks.
- Task 9f, illustrations for free-weight and cable exercises (`illustrations.py`, `albums.py`, `planner.py`, `prompts.py`): done 2026-11-13 (slot 1). Source free-exercise-db (Unlicense). 107 tests pass, ruff clean. Not run on the real bot or the real download: Brian restarts it and asks `/propose` for a new week, orchestrator checks.
- Task 9g, scheduler thread database crash (`store.py`): done 2026-11-13 (slot 1). One shared connection with a lock; new test runs a tick in a second thread. 108 tests pass, ruff clean. Not run on the real bot: Brian restarts it, orchestrator checks bot.log.
- Task 9h, restart the real bot on the Task 9g fix: done 2026-11-16 (slot 1). Restarted through the scheduled task; after 3 minutes no new thread-error lines (149 before, 149 after) and no new traceback; bot still running.
- Task 12, daily calorie and protein targets (`targets.py`): done 2026-11-16 (slot 1). 115 tests pass, ruff clean.
- Task 13, meal photo estimates (`meals.py`, router `handle_photo` and `meal` intents): done 2026-11-16 (slot 1). 123 tests pass, ruff clean. Not run on the real bot.
- Task 14, weekly body numbers (`router.py` body intent, `scheduler.py` Monday prompt): done 2026-11-16 (slot 1). 131 tests pass, ruff clean. Not run on the real bot.
- Task 15, ceiling check end to end (`tests/test_ceiling_e2e.py`): done 2026-11-16 (slot 2). 124 tests pass, ruff clean.
- Task 11, live check with the real bot: done 2026-11-16 (slot 1). Bot runs; first week stored as proposed, uses only listed equipment; month cost US$0.07; 132 tests pass, ruff clean. Brian still approves the schedule in the chat and logs one real session per gym.
- Task 9i, every exercise gets a picture (`planner.py`, `illustrations.py`, `scriptsdd_illustration_ids.py`): code and stored sessions done 2026-11-16 (slot 1); 136 tests pass, ruff clean. Waiting: bot restart was refused by the auto-mode check; Brian restarts, orchestrator checks bot.log.
- Task 9j, strength on Tue, Thu (home) and Sun (parents'): code and stored week 17-22 Nov done 2026-11-16 (slot 1); 138 tests pass, ruff clean. Paid call: one coach-model proposal, cost not yet read from /cost (well under US$1). Every strength exercise has a picture or machine photo. Waiting: bot restart refused by the auto-mode check; orchestrator restarts and checks bot.log.
- Task 9k, one Telegram message per exercise (`albums.py session_parts`, `telegram.py send_pictures`, `illustrations.py` position and equipment match): code and stored sessions 17-22 Nov done 2026-11-16 (slot 1); 143 tests pass, ruff clean. Real db: 8, 9 and 8 messages for 6, 7 and 6 exercises, every exercise has a picture. Paid calls: two small fast-model calls, well under US$1. Waiting: bot restart refused by the auto-mode check; orchestrator restarts and checks bot.log.
- Task 9l, one exercise at a time (`router.py` flow, `scheduler.py`, `app.py send_exercise`, `albums.py exercise_parts`): code and tests done 2026-11-16 (slot 1); 146 tests pass, ruff clean. Dry run on a copy of the real db, 17 Nov: list message, first exercise at 07:00, five more one per completing reply, then the summary. No Claude call. Waiting: bot restart refused by the auto-mode check; orchestrator restarts and checks bot.log.
- Task 14b, weekly check-in asks for weight only (`scheduler.py`, `router.py`, `tests/test_body.py`): code and tests done 2026-11-17 (slot 1); 148 tests pass, ruff clean. Waiting: bot restart refused by the auto-mode check; orchestrator or Brian restarts `gym-coach-bot` and checks bot.log.
- Task 14c, exercise messages without the form tip (`albums.py`, `config.py SHOW_FORM_TIP`, `app.py`): code and tests done 2026-11-17 (slot 1); 150 tests pass, ruff clean. Tip back on with `SHOW_FORM_TIP=on` in `.env`. Waiting: bot restart refused by the auto-mode check; orchestrator or Brian restarts `gym-coach-bot` (with Task 14b) and checks bot.log.
- Task 14d, one-line form tip back on by default (`illustrations.py CUE_CHARS=60`, `albums.py`, `config.py SHOW_FORM_TIP`): code and tests done 2026-11-17 (slot 1); 151 tests pass, ruff clean. Turn off with `SHOW_FORM_TIP=off` in `.env`. Waiting: bot restart refused by the auto-mode check; orchestrator or Brian restarts `gym-coach-bot` and checks bot.log.
- Task 14f, lost replies on failed Telegram calls (`telegram.py`, `app.py`, `illustrations.py`): code and tests done 2026-11-17 (slot 1); 172 tests pass, ruff clean. Cause: about 1 in 7 new TLS connections to Telegram is cut in the handshake (26-28 of 200); a kept connection failed 0 of 200 and is 3 times faster, so the bot now keeps one; sends retry 4 times. Lat pulldown and Seated low row now have pictures (stored sessions 19-29 Nov updated, no model call). Paid calls: none. Waiting: restart refused by the auto-mode check; Brian restarts `gym-coach-bot`, orchestrator checks bot.log for 2 hours.
  For Brian, where a slow reply's seconds go (17 Nov session, changed nothing): "next", "done" or "skip" during a session makes no Claude call; a set report makes one Haiku call; a message read as neither makes two (classify, then a free answer, the second 2 to 4 s); the plan change at 17:10 made one Haiku and two Opus calls (14,555 and 16,292 input tokens), about 28 s and US$0.19. The gaps of up to 37 s were between his messages. The new log lines give the receipt-to-reply seconds per message from the restart on.
- Task 14e, bot hangs at start (`boot.py`, `app.py`, `llm.py LazyAnthropic`, `scripts\install-logon-task.ps1 -Priority 4`): code and tests done 2026-11-17 (slot 1); 157 tests pass, ruff clean. Cause: the logon task's below-normal priority (7) starved the anthropic import (2,824 modules) that ran before "bot started"; pid 28844 still stuck after 48 min. A normal-priority start on a copy of the data: "starting" +0.2 s, "bot started" +0.7 s. Waiting: the restart was refused by the auto-mode check; Brian runs `Stop-ScheduledTask gym-coach-bot`, `scripts\install-logon-task.ps1`, `Start-ScheduledTask gym-coach-bot` before 07:00 on 18 Nov; orchestrator checks bot.log.
- Task 14g, the 17 Nov session's lessons (`store.py` chat table, `app.py` late replies, `router.py`, `reports.py`, `scheduler.py` 21:00 close): code and tests done 2026-11-17 (slot 1); 197 tests pass, ruff clean. The bot keeps the chat 30 days; an undelivered reply goes out "(late)" with the next send; a change during a session edits today only (swap, drop, weight) and a future-week change without a proposed week becomes a note for `/propose`; the pointer follows reported sets and "Session done" lists missing sets; the day is `done` at the flow's end or at 21:00; each sorting and answer call sees today's last 12 chat lines and the session state. Added tokens per message (measured on a copy of the real db, 12 lines): sorting call about 600 (instructions 230, chat and session 270, equipment list 90), answer about 270; under US$0.0001 at Haiku's price. Paid calls: none. Restarted through the scheduled task: the first start at 17:39:59 exited 1 (old process still held the lock), the second at 17:40:38 logged "bot started". Waiting: the next real session (Thu 19 Nov); orchestrator reads the `chat` table and bot.log. Seen at 17:39 on the old code: the waiting proposed week 23-29 Nov was revised again (two Opus calls, US$0.21); today's session closed with all six exercises at 3 sets and 4 of Lying leg curl.
