# Known issues

- The logon task `gym-coach-bot` is not registered. Brian runs `scripts\install-logon-task.ps1`
  himself (the safety check refused a worker run).
- The owner is not paired yet. The first private message to the bot pairs it (`--check` prints
  "config ok (owner not paired yet)" until then).
- Task 11's live check (real `/start`, real schedule, `/cost`) has not run. It needs the bot
  running and Brian's first message.
- Checked without the live bot (2026-11-13): 83 tests and ruff pass. Tests cover dropping other
  senders, group messages never pairing, and `.env` owner override.
- Task 9b (2026-11-13, no real Telegram call by order of the orchestrator): the first
  `getUpdates` hung past its 60 s client timeout. The root cause is not confirmed. Changes made:
  explicit `httpx.Timeout(connect=10, read=60, write=10, pool=10)`, no keep-alive pool and
  `Connection: close` so a dead pooled socket cannot be reused. If the hang remains after the
  restart, look at the proxy, IPv6 and the route to api.telegram.org next.
- `Stop-ScheduledTask gym-coach-bot` ended conhost and powershell but left python running
  (Task 9d). A parent-watching flag did not help: Task Scheduler stops only the conhost, not the
  powershell between. The task now starts `pythonw.exe -m gym_coach` directly, so Task Scheduler
  stops the process it started. A bot started by the old task has to be stopped by hand once,
  and `scripts\install-logon-task.ps1` re-run.
