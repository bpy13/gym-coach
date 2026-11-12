# Gym Coach

A personal gym coach as a Telegram chat bot. A small Python program on your PC sends the day's
session, logs what you report, estimates meals from photos and writes a weekly review.
It answers only the one Telegram account you allow.

## Setup
1. `conda env create -f environment.yml`
2. `conda run -n gym-coach pip install -e ".[dev]"`
3. Copy `.env.example` to `.env` and fill in `TELEGRAM_BOT_TOKEN` and `ANTHROPIC_API_KEY`.
   Leave `TELEGRAM_ALLOWED_USER_ID` empty: the first private message the bot receives pairs it
   with that account (it answers only that account afterwards). Set the number to override.
   Never commit `.env`.
4. Put your own profile and equipment lists in `data\profile.md` and `data\equipment.md`
   (same layout as the made-up files in `examples\`). `data\` is git-ignored.

## Develop
- Tests: `conda run -n gym-coach python -m pytest -q`
- Lint: `conda run -n gym-coach ruff check .`

## Run
- Check settings: `conda run -n gym-coach python -m gym_coach --check`
- Start the bot: `conda run -n gym-coach python -m gym_coach` (a second copy exits at once;
  the log is `data\bot.log`).
- Start at logon with no window: run `scripts\install-logon-task.ps1` once. It registers the task
  `gym-coach-bot`, which starts `pythonw.exe -m gym_coach` directly (no powershell or console
  in between), so `Stop-ScheduledTask gym-coach-bot` really ends the bot. If you registered the
  task with an older version of the script, run it again.

- Machine photos: each session message (and the first session of a proposal) is preceded by one
  album with the photo of each exercise's machine, taken from the photo ids in
  `dataequipment.md` and the files in `photoshome` and `photosparents`, shrunk to 1280 px.
  Needs Pillow: after pulling, run `conda run -n gym-coach pip install -e ".[dev]"`. Restart the bot.

- Exercise illustrations: for dumbbell, cable and barbell exercises the coach picks an id from
  the open exercise database free-exercise-db (https://github.com/yuhonas/free-exercise-db,
  Unlicense: public domain). The album then shows the exercise's start and end images with a
  short form cue; machines keep your own photo. The exercise list is downloaded once into
  `data/illustrations/` and each exercise's images the first time it is sent (needs internet then;
  without it the session still goes out as text). Nothing from there is committed. Existing
  plans have no illustrations: ask for a new proposal (`/propose`) to get them. Restart the bot.

See `docs/plans/` for the plan.
