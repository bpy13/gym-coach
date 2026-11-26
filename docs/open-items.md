# Open items

As of 2026-11-26. Tick off, or move to `decisions.md` when settled. A bug that will be fixed goes
here; a limit or trap we live with goes in `known-issues.md`. Each item in one place only.

## Blockers

## Waiting on the user
- Check the dumbbell weights at both gyms (the coach assumes 2 kg steps until then).
- Three items in `data\equipment.md` are marked "unsure".
- Back up `photos/` somewhere else if wanted: it is the only copy of the machine photos
  (Brian was told on 2026-11-17 and may delete the identical Downloads copy).

## Pending work
- Weekly review (milestone 3) must read the `cardio` table (jogs: minutes, distance, pace,
  heart rate) as well as sets and body numbers; today only the daily summary and the coach read
  it (said to Brian on 2026-11-23: "the weekly review isn't built yet").
- Brian's Strava ask of 2026-11-23 (Telegram "start"/"done" as the triggers, Strava numbers
  merged with typed ones by the model, no automatic pick-up) was not built; he moved to sharing
  Strava's summary picture (Task 14q). Confirm with him only if he raises it again.
- Coach chat (Task 15): a workout question that calls no tool does not open the workout, so
  the next model call sees only today's last chat lines, not the whole workout.
- Coach chat (Task 15): two identical sets after a bot reply that was not delivered are told
  apart only by the model (the prompt marks the undelivered line); no code check yet.


## Later
- `scripts/replay_day.py` cannot judge answers to photos: photos are not kept, so a photo
  message is replayed as its stored text.
