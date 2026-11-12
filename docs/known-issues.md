# Known issues

- The logon task `gym-coach-bot` is not registered. Brian runs `scripts\install-logon-task.ps1`
  himself (the safety check refused a worker run).
- The owner is not paired yet. The first private message to the bot pairs it (`--check` prints
  "config ok (owner not paired yet)" until then).
- Task 11's live check (real `/start`, real schedule, `/cost`) has not run. It needs the bot
  running and Brian's first message.
- Checked without the live bot (2026-11-13): 83 tests and ruff pass. Tests cover dropping other
  senders, group messages never pairing, and `.env` owner override.
