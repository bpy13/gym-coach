# Known issues

- The logon task `gym-coach-bot` is not registered. Brian runs `scripts\install-logon-task.ps1`
  himself (the safety check refused a worker run).
- Task 11 live check (2026-11-16): the bot runs from the logon task on the Task 9g fix. The owner
  is paired. The first week (5 days) is stored as `proposed`; no exercise uses equipment outside
  its gym's list. The month's model cost is US$0.07 over 7 calls. Another sender and a forged
  update are dropped (tests in `tests	est_telegram.py`, no real second account used). Still
  open: Brian approves the schedule in the chat. Milestone 1's last line (one real session
  logged at each gym) is Brian's.
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
- Task 14f (2026-11-17): Telegram calls failed about 8 times an hour with `ConnectError`. Cause,
  measured from this PC over 200 `getMe` calls per variant: a new connection per call failed
  26-28 times in the TLS handshake (`SSL: UNEXPECTED_EOF_WHILE_READING`), median 0.85 s; a
  kept connection failed 0 times, median 0.28 s. IPv4 and the default route measure the same
  (this PC has no IPv6 route to api.telegram.org). The DNS server is a VPN's, so the
  handshake cut is likely on the VPN path (inferred, not checked). The client now keeps its
  connection (30 s idle expiry); every send tries 4 times (pauses 1, 3, 8 s) on a connect
  error only, never once Telegram may have the request. The Task 9b "no keep-alive" choice was
  a guess (the real 9b cause was the task's low priority, Task 14e) and is undone.
- Task 14g (2026-11-17): the bot keeps the chat (both directions, text, delivered or not) in
  the `chat` table of `data/gym.db` for 30 days, so each model call that reads a message sees
  today's last 12 lines and today's session. Limits: a reply that never reached Telegram goes
  out "(late)" only with the next send of the same day; a report sent again with the same text
  after an undelivered reply is not logged twice, so two identical real sets in a row while
  Telegram is down need the second one sent again after the "Already logged" reply. A swap
  needs equipment exactly on that day's gym list; the new exercise has no picture until a
  proposal gives it one.
