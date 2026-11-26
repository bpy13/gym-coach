# Gym Coach – notes for Claude

A personal gym coach for one user (Brian), as a Telegram chat bot run by a small Python program
on his PC. The bot sends him the day's session, he replies with what he did and sends meal
photos, and Claude (through the API) estimates meals and writes a weekly review and next
week's plan. Goal: build muscle and lose fat. He trains at two clubhouse gyms: the one where
he lives (Monday-Friday) and his parents' (Saturday-Sunday). Each session uses only the
equipment at that day's gym.

Read these before substantial changes:

- `docs/decisions.md` – what was decided and why (don't re-litigate without a reason)
- `docs/open-items.md` – pending work and questions waiting on the user
- `docs/plans/` – the latest plan
- `docs/architecture.md` – modules, data flow, where things live (once it exists)
- `docs/known-issues.md` – limits and traps found so far (once it exists)
- `README.md` – user-facing setup and commands

## Environment
- Python 3.12, conda env `gym-coach` (python-env skill).
- Install: `conda env create -f environment.yml`, then
  `conda run -n gym-coach pip install -e ".[dev]"`
- Run: `conda run -n gym-coach python -m gym_coach` (a second copy exits at once; log `dataot.log`)
- Tests: `conda run -n gym-coach python -m pytest -q`
- Lint: `conda run -n gym-coach ruff check .`

## Project rules
- The repo is public. Personal data never goes into git: workout logs, body measurements,
  health notes, equipment photos, meal photos, `.env`. They live in the ignored folders
  (`data/`, `photos/`). `docs/` is public: no age, weight, address or building name there. Tests and examples use made-up data only.
- Before every commit, check `git status` for personal files that slipped past `.gitignore`.

## The live bot (learned in Brian's chat session, 2026-11-17 to 2026-11-23)
- The bot runs on this PC all the time, started by the scheduled task `gym-coach-bot`. Restart
  it with `Stop-ScheduledTask gym-coach-bot` then `Start-ScheduledTask gym-coach-bot`, never as
  your own child process, and read `dataot.log` afterwards ("bot started", no traceback). Do it
  when code changes, but not while Brian is mid-workout (the log and `chat` table show his last
  message). A bot started by hand holds the lock, so the task's start then exits 1.
- Data is in `data/gym.db`: sets, meals, body numbers, cardio, the full chat (`chat`, kept for
  good) and a `trace` row per message (what the bot understood, seconds per step). Telegram does
  not let a bot read old messages, so this table is the only record of what he typed.
  `scripts\show_chat.py` prints one day's chat with its traces; `scriptseplay_day.py` replays a
  day through the model on a copy of the db and spends real money (cap with `--max-cost`).
- Before changing live rows by hand, copy the db first (`data/gym.db.bak-<what>`), and tell Brian
  what was changed.
- The machine and equipment photos in `photos/home` and `photos/parents` (8 and 9 files) are the
  only copy; git ignores them. Brian's old Downloads copy is identical and may be deleted.
- When Brian reports a bad session, read that day's chat and trace first, find the first message
  where it went wrong, and fix the cause; replay the day on a db copy before going live.
- Working with Brian in chat: answer the question he asked first (if he asks to see what he typed,
  show it); do not add scope he did not ask for, and when he asks "why add?", say what is missing
  and let him decide; keep explanations short and plain (he answered a long one with "what??");
  say "the helper is working on it" instead of explaining the build. Questions to him: say what it
  is, an example, why it matters, options with a default.

## Conventions
- Messages to Brian are plain English, weights in kg, no codes or internals. The model leads the
  chat through tools (`coach.py`); code enforces the hard rules inside the tools.
