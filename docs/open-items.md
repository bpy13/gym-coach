# Open items

As of 2026-11-13. Tick off, or move to `decisions.md` when settled. A bug that will be fixed goes
here; a limit or trap we live with goes in `known-issues.md`. Each item in one place only.

## Blockers

## Waiting on the user
- Check the dumbbell weights at both gyms (the coach assumes 2 kg steps until then).
- Three items in `data\equipment.md` are marked "unsure".
- Create the Telegram bot and put the keys into `.env` (plan Task 10; the question is in
  `docs/inbox.md`).

## Pending work
- Coach chat (Task 15): a workout question that calls no tool does not open the workout, so
  the next model call sees only today's last chat lines, not the whole workout.
- Coach chat (Task 15): two identical sets after a bot reply that was not delivered are told
  apart only by the model (the prompt marks the undelivered line); no code check yet.

## Later
- `scripts/replay_day.py` cannot judge answers to photos: photos are not kept, so a photo
  message is replayed as its stored text.
