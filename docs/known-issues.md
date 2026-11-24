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
  the `chat` table of `data/gym.db` (for good since Task 14h; it was 30 days), so each model call that reads a message sees
  today's last 12 lines and today's session. Limits: a reply that never reached Telegram goes
  out "(late)" only with the next send of the same day; a report sent again with the same text
  after an undelivered reply is not logged twice, so two identical real sets in a row while
  Telegram is down need the second one sent again after the "Already logged" reply
  (replaced by Task 15: the "Already logged" repeat is gone, see the Task 15 entry). A swap
  needs equipment exactly on that day's gym list; the new exercise has no picture until a
  proposal gives it one.
- Task 14h (2026-11-17): each incoming message gets a row in the `trace` table (what the bot
  understood, each model call's seconds and reply, seconds to the reply, any error), and each
  logged set a save time (`saved_at`; sets saved before 14h have none).
  `scripts\show_chat.py --day YYYY-MM-DD` prints a day in time order. The trace does not yet
  record what a message changed (sets rewritten, the session pointer); Brian holds that.
  Limits: every set report goes to the model (reading "35 12" without it was removed the same
  day, Brian: "quite risky, no need"; replaced by Task 15: the coach reads it with tools). A photo without a caption that the model calls "not a meal"
  stores nothing and the bot asks what it is; the image is not kept, so he sends it again with
  a caption. A future-week change asks "Revise the proposed week ...? Reply yes." only when no
  strength session is open today; any reply other than yes drops the question.
  (Replaced by Task 15: the "yes" follow-up is answered through the coach, whose
  `revise_proposed_week` and `note_plan_change` tools do it.)
- Task 14i (2026-11-17): a workout opens on "start", or by itself on a set report, a
  correction, a missing-sets message, a change to today's session, "next/done/skip", or a
  question the sorting call marks as about today's workout. It closes when no exercise has
  sets left, on "end", or at 21:00; once closed it reopens only on "start". While it is open,
  model calls see every chat line since it opened (outside a workout, today's last 12), and a
  photo is never stored as a meal. Each trace row names the exercise shown after the message.
  A week change waits until this week's last planned session is done, skipped or past; the
  kept note is asked about when that session closes. `/propose` works any time. A
  missing-sets message makes one more Haiku call that compares his claim with the chat: it
  adds or fixes sets (never deletes) and says what changed, or asks whether he misread
  (replaced by Task 15: that extra check call is gone; the coach has the chat and the log
  tools, and the sorting call that opened the workout is replaced too). Limits:
  added sets are checked only by exercise name (a name not in today's session or log is
  skipped); a very long workout grows each call (about 1,900 tokens at message 40).
- Task 14j (2026-11-17): the 07:00 message is the list, then the warm-up (no first exercise);
  the first exercise follows on "done" (or "next", "skip", "ready", "warm-up done") or a first
  set report. After the last exercise the bot marks the day done, lists the stretches for the
  day's exercises (matched by words in the exercise names; an unmatched name gets only the
  two stretches that always come) and shows a "Finish session" button. The button, "finish"
  or "end" close the workout, send the summary and remove the button. Limits: the 21:00 close
  is silent, so the button stays on his phone until his next message that closes; a reply
  that went out "(late)" loses its button.
- Task 15 (2026-11-23): the coach chat replaced the sorting call. One fast-model conversation
  per message leads the chat with 15 tools (log, fix and remove sets, show/swap/drop an exercise,
  set a weight, finish, skip, meals, body weight, plan notes). The model decides; the code
  enforces equipment on that day's gym list, positive numbers and exercise names in today's
  session, and a refused call goes back to the model with the valid choices. When a failure
  comes after a tool ran, the reply lists what was saved (never "try again"). Cost measured in
  the replay of Sunday 22 Nov: median about US$0.001 per message, about US$0.06 for the 52
  messages. Equipment names now keep commas inside brackets. Limits: a question with no tool
  call does not open the workout; two identical sets after an undelivered reply rely on the
  model (the prompt says to check the log); the replay cannot judge photo answers (photos are
  not kept).
- Task 14n (2026-11-24): past sets reach the coach one per set ("17 Nov, 3 sets: set 1 21 kg
  x 15, set 2 28 kg x 12, set 3 28 kg x 15"); the grouped form ("21 kg x 15; 28 kg x 12, 15")
  was read as two sets. His effort word is read by keywords (`weights.effort_kind`: "barely",
  "hard", "not easy" and the like are hard; "easy", "light" are easy; anything else is no
  word); the last set with a word decides. A word the list misses counts as none, so the rep
  rule applies. `fix_past_set` changes an earlier day only after he names the set and the
  numbers (prompt rule, not code-checked); an added or removed set renumbers that day's sets.
