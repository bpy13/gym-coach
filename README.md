# Gym Coach

A personal gym coach as a Telegram chat bot. A small Python program on your PC sends the day's
session, logs what you report, estimates meals from photos and writes a weekly review.
It answers only the one Telegram account you allow.

## Setup
1. `conda env create -f environment.yml`
2. `conda run -n gym-coach pip install -e ".[dev]"`
3. Copy `.env.example` to `.env` and fill in `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_ID`
   and `ANTHROPIC_API_KEY`. Never commit `.env`.
4. Put your own profile and equipment lists in `data\profile.md` and `data\equipment.md`
   (same layout as the made-up files in `examples\`). `data\` is git-ignored.

## Develop
- Tests: `conda run -n gym-coach python -m pytest -q`
- Lint: `conda run -n gym-coach ruff check .`

## Run
- Check settings: `conda run -n gym-coach python -m gym_coach --check`
- Start the bot: `conda run -n gym-coach python -m gym_coach` (a second copy exits at once;
  the log is `dataot.log`).
- Start at logon with no window: run `scripts\install-logon-task.ps1` once. It registers the task
  `gym-coach-bot`.

See `docs/plans/` for the plan.
