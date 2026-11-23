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

- Photos you send: with a caption, the caption is read like a text (a meal caption gets a meal
  estimate, a question about the machine gets an answer). Without a caption the bot estimates
  a meal, or asks what it is when it shows no food. During a workout a photo is never a meal:
  it is answered as a question about the workout.

- Workouts: the morning message lists the exercises, then a warm-up of about 8 minutes (edit
  `WARM_UP` in `src/gym_coach/messages.py` to change it); say "done" after it and the first
  exercise follows. Send "start" when you begin (the first set or a question about today's
  exercises also starts it). After the last exercise the bot lists stretches and shows a
  "Finish session" button; tap it (or send "finish" or "end") for the summary. A workout you
  never finish closes at 21:00. Chatting: talk in plain words, there is no format to learn. The coach (a fast model
  leading the chat with tools) logs your sets ("35 for 12", "3rd set 40 x 10"), fixes or removes
  a set, swaps or drops an exercise of today's session, changes a planned weight, shows the
  next exercise ("next", "done", "skip"), logs cardio ("jogged 45 min, 6 km", with minutes and
  any distance or heart rate; it marks the day done), logs meals and body weight, keeps a change for a future
  week, and finishes the workout. It answers form questions and always says the numbers it
  logged. The code, not the model, enforces the hard rules: a swap needs equipment on that
  day's gym list, numbers must be above 0 and exercise names must be in today's session (your
  own extra exercise is logged as such). If a call fails after something was saved, the reply
  says what is saved. A change to next week is kept until this week's last session is done;
  then the bot asks.
- What stays a command or button: `/start`, `/today`, `/propose`, `/progress`, `/cost`, the
  word "start" when you begin, and the "Finish session" button (the coach also finishes on
  "finish" or "end").

- Replay a day: `conda run -n gym-coach python scripts\replay_day.py --day 2026-11-22` feeds
  that day's messages from the chat table through the current coach and writes what it said,
  its tool calls and the cost per message to `data\replay\<day>.txt`. It makes real API calls
  and spends real money (about US$0.06 for a 52-message day): it checks this month's cost plus
  `--max-cost` (default 0.50) against the monthly ceiling first and stops when the run passes
  `--max-cost`. It works on a copy of `data\gym.db` in `--work-dir` (system temp by default);
  the live database is only read. Photos are not kept, so it cannot judge photo answers.

- See a day's chat: `conda run -n gym-coach python scripts\show_chat.py --day 2026-11-17`
  prints the chat with what the bot understood, its model calls and seconds, the exercise
  shown after each message, and each logged set's save time (read-only on `data\gym.db`).

See `docs/plans/` for the plan.
