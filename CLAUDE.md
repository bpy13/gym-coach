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
- Run: `conda run -n gym-coach python -m gym_coach` (the program itself comes with plan Task 9)
- Tests: `conda run -n gym-coach python -m pytest -q`
- Lint: `conda run -n gym-coach ruff check .`

## Project rules
- The repo is public. Personal data never goes into git: workout logs, body measurements,
  health notes, equipment photos, meal photos, `.env`. They live in the ignored folders
  (`data/`, `photos/`). `docs/` is public: no age, weight, address or building name there. Tests and examples use made-up data only.
- Before every commit, check `git status` for personal files that slipped past `.gitignore`.

## Conventions
<Patterns specific to this codebase.>
