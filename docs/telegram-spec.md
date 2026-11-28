# Telegram spec: gym-coach

What this app's bot does, in its own terms. The shared rules are in the `telegram-bot` skill;
this file says how this app applies them. Keep it current: a change to the bot's commands,
intents or replies updates this file in the same commit.

Written 2026-11-28 from a read-only survey of the code at commit f496d13. It describes
what the bot does today, not what it should do.

## Purpose and direction
- A personal gym coach for one person. It sends the day's session, logs the sets, cardio,
  meals and body weight he reports, and answers questions like a trainer would.
- Direction: two-way (he messages it; it also sends scheduled messages).
- Bot code: `src/gym_coach/` (`telegram.py` client, `app.py` poll loop and sending,
  `router.py` commands and routing, `coach.py` the model-led chat with tools,
  `scheduler.py` timed messages). Entry point: `python -m gym_coach`
  (`src/gym_coach/__main__.py`); `--check` only validates the settings.

## Who may message it
- Allowed chats: one owner account. Setting `TELEGRAM_ALLOWED_USER_ID` in `.env`; when empty,
  the first private-chat sender pairs and is stored in the database `kv` row `owner_id`
  (`telegram.py` `get_updates`, `app.py` `build`). The setting wins over the stored owner.
- On pairing it replies "Paired with this account. I will answer only you."
- Messages from anyone else: dropped silently, with no reply and no log line
  (`telegram.py` `get_updates`, `continue`). Group messages never pair.
- Languages people write in: English only. The coach prompt says "English only, weights in kg"
  (`coach.py` `SYSTEM`); decisions.md "Messages are in English; weights in kg".

## Commands
Handled in `router.py` `_handle`; no model call except `/propose`.

| Command | What it does | What it saves | Reply (example) |
|---|---|---|---|
| `/start` | Help text; with no plan in the next 21 days it also proposes a week (`app.py` `_handle`) | with a proposal: `plan_sessions` rows | "Hi! I'm your gym coach. I send the day's session; reply with what you did (e.g. "chest press 35 kg 10 10 8"). Commands: /today, /progress, /cost. ..." |
| `/today` | Today's planned session | nothing | "Today at the home gym:" then one line per exercise with last time's sets; "Warm-up first: say "start" and I send it." |
| `/propose` | Proposes (or revises) next week with the coach model; uses a kept plan-change note | `plan_sessions` (status `proposed`), clears the `pending:plan_change` note | coach intro, then every day with its exercises; then one message per exercise of the first strength day, with pictures |
| `/progress` | Placeholder | nothing | "Progress numbers are coming soon." |
| `/cost` | This month's Claude spend | nothing | "This month: US$0.42 of US$5." |
| word `start` (also "start workout", "start session") | Opens today's workout, sends the warm-up | `kv` workout/flow/warm-up markers | "Workout started." plus the fixed warm-up list |
| button "Finish session" | Closes the workout, removes the button | day marked done, workout closed | "Workout finished. Summary: ..." plus "Missing: ..." |

## Free-text intents
Everything that is not a command, "start" or the button goes to one coach conversation
(`router.py` `_coach` -> `coach.py` `Coach.reply` -> `llm.py` `Claude.converse`). The fast
model reads the message with today's chat and session, calls tools, and writes the reply. The
code enforces the hard rules inside each tool (`ToolRefused` goes back to the model with the
valid choices). Examples are from the README, the coach prompt and decisions.md.

| Intent | Examples | What it saves (tool) | Reply (example) |
|---|---|---|---|
| Log sets | "chest press 35 kg 10 10 8", "35 for 12", "3rd set 40 x 10" | `logged_sets` (`log_sets`; own exercise with `own: true`) | confirms the numbers logged and what is left; a far-off weight asks "typo?" |
| Move on | "next", "done", "skip" | `kv` flow pointer (`show_exercise`) | short reply, then the next exercise card with pictures |
| Swap, drop or reweight today's exercise | "swap the leg press for lunges" | today's `plan_sessions` row (`swap_exercise`, `drop_exercise`, `set_weight`) | says the change |
| Log cardio | "jogged 45 min, 6 km"; a Strava summary picture | `cardio` (`log_cardio`); day marked done | distance, time and pace |
| Log a meal | a photo with no caption; "chicken rice for lunch" | `meals` estimate only, never the image (`log_meal`, `meals.py`) | kcal and protein against the day's targets |
| Body weight | "81.6 kg" (reply to the Monday prompt) | `body` (`log_body`; asks first if over 5 kg from the last) | "Saved: 81.6 kg. Daily targets now 2,300 kcal and 160 g protein." |
| Question about a machine or form | photo with caption "can I use this for rows?" | nothing | one or two cues |
| Past sets | "what did I lift last time?" | nothing (`past_sets`) | every set numbered, from the record |
| Future plan change | "less legs next week" | note in `kv` (`note_plan_change`) or a revised week (`revise_proposed_week`) | says it is kept or revised |
| Start / finish / skip | "let's begin", "finish", "end", "skip today" | workout markers (`start_workout`, `finish_workout`, `skip_today`) | warm-up, summary, or skip confirmation |
| Correction of the last saved item | "x12, typo", "that was 37.5"; "it was 7 km"; "that meal was about 600 kcal" | `fix_set`, `remove_set`, `fix_cardio`, `correct_meal`; earlier days `fix_past_set` (only once he names the set and numbers) | "Fixed: Lat pulldown set 2 from 35 kg x 10 to 35 kg x 12" |
| Fallback (Claude call) | anything else | nothing unless a tool runs | the coach's own reply. If the model returns no text: the last tool result, else "Sorry, I have no answer to that." |

Other replies with no model call (`app.py` `_handle`): a sticker or other non-text, non-photo
message gets "I can only read text for now."; a photo Telegram will not hand over gets
"I could not fetch that photo from Telegram. Please send it again."

## App-specific rules
- A photo during an open workout is never a meal; it is a workout question : photo of a plate
  held to the chest, logged as his own exercise "Plate halo" (Brian, 2026-11-17)
- A failure after a tool already saved something replies with what was saved, never "try
  again" (sending again would log it twice) : "My full reply did not come through. This is
  saved, no need to send it again: ..." (Task 15f, commit e451e6d, 2026-11-23)
- Identical numbers after a delivered reply are a new set; after an undelivered reply they may be
  the same set, so the model checks the log first (coach prompt; open item, no code check)
- No suggested weight or reps unless he asks : the card shows last time's sets only
  (Brian, 2026-11-24, Task 14o)
- Every set report goes to the model; no number-only shortcut : "35 12" (Brian, 2026-11-17:
  "quite risky, no need", commit c774af5)
- A running-app summary picture is the jog, never a meal; a second picture of the same run
  updates it (Task 14q, 2026-11-25)

- How text is understood: three exact-match rules first (slash commands, the word "start",
  the "Finish session" button), then the coach call. Model: `MODEL_FAST`, default
  `claude-haiku-5-5`, with 20 tools defined by JSON input schemas (`coach.py` `TOOLS`); final
  reply is free text. Up to 6 tool rounds (`llm.py` `MAX_TOOL_ROUNDS`). Photos without a
  caption outside a workout go first to a meal-estimate JSON call (`meals.py`, `claude.json`,
  retried once on bad JSON).
- Follow-ups: no stored "last question". Each coach call sees today's last 12 chat lines, or
  the whole open workout (`router.py` `context`, `CHAT_LINES`), with undelivered bot lines
  marked, plus the session state and the exercise shown now. Corrections are resolved by the
  model against that context and the logged sets.

## Messages the bot sends unasked
From `scheduler.py` (checked every minute; a `kv` marker `sent:<kind>:<day>` stops repeats;
the marker is set after the send, so a crash may repeat a message but never loses one).

| When | What | To whom |
|---|---|---|
| `SESSION_TIME` (07:00 HK) on a planned day, or at start later that day | the day's list; on a strength day then the fixed warm-up; on a jog day an "Open Strava" button | the owner (`kv` `chat_id`) |
| Monday at `SESSION_TIME` | "Weekly check-in: what is your body weight today? Reply like "81.6 kg"." | the owner |
| 21:00 | nothing sent: silently marks a day with sets as done and closes an open workout | n/a |
| first pairing | "Paired with this account. I will answer only you." | the new owner |
| next successful send of the same day | each undelivered reply, prefixed "(late) " | the owner |

Settings `REVIEW_TIME` and `BODY_PROMPT_TIME` exist in `config.py` but nothing reads them; the
Sunday weekly review is not built (open-items.md, "Weekly review (milestone 3)").

## Schedule and process
- How it runs: one long-running process. The main thread long-polls `getUpdates` (50 s); a
  daemon thread runs the scheduler every 60 s (`app.py` `run_forever`). One instance at a time
  through the lock file `data/bot.lock` (`boot.py` `InstanceLock`); a second copy exits 1.
  Scheduled task name: `gym-coach-bot`, a logon task that starts `pythonw.exe -m gym_coach`
  directly at priority 4 (`scripts/install-logon-task.ps1`).
- Restart: no restart script. `Stop-ScheduledTask gym-coach-bot`, confirm no `pythonw` runs
  `-m gym_coach`, `Start-ScheduledTask gym-coach-bot`; then check `data/bot.log` shows
  "starting (pid N)" then "bot started" and no traceback (CLAUDE.md "The live bot"; plan Task
  9h). Not while he is mid-workout (check the last `chat` row). Never as a worker's child.
- Offset and outbox: the update offset is kept in memory only (`TelegramClient.offset`; nothing
  saves it, although plan Task 2 named `kv` for it). Unsent replies are `chat` rows with
  `delivered = 0` in `data/gym.db`; `app.py` `_send_late` resends today's ones, marked
  "(late)", before the next send. Earlier days' unsent replies are never resent. A failed
  scheduled message is not marked sent, so the next scheduler minute retries it.

## Logging
- Log file: `data/bot.log` (rotating, 500 kB x 3; `boot.py` `setup_logging`). Per message:
  "received text (N chars)" or "received photo (caption N chars)" and "replied: M messages,
  P pictures, S s after receipt" (`app.py` `handle`). Never the text; httpx is set to WARNING
  because its URLs hold the token; error text has the token replaced by `<token>`.
- Full record in `data/gym.db`: `chat` (every message both ways, kept for good, with
  delivered flag) and `trace` (one row per incoming message: what was understood, i.e.
  "local" or the tool calls as JSON, each model call's seconds and reply, seconds to the reply,
  error, exercise shown after). `scripts/show_chat.py --day YYYY-MM-DD` prints a day.
- Dropped messages from other senders are not logged.

## Network
- Kept HTTPS connection, 30 s idle expiry, at most 2 (`telegram.py` `new_http_client`).
  Measured: a new TLS handshake per call failed 26-28 of 200 with `SSL:
  UNEXPECTED_EOF_WHILE_READING`; a kept one failed 0 of 200 (known-issues.md, Task 14f).
- Sends (text, photo, album, file download): 4 tries, pauses 1, 3, 8 s, only on
  `ConnectError`, `ConnectTimeout`, `PoolTimeout` (the request never left the PC), so Telegram
  never gets a send twice. Other HTTP errors fail at once.
- Long poll: no retry inside the call; a failure logs a warning, pauses 5 s, and polls again.
- Timeouts: connect 10 s, read 60 s (poll 50 s + 10), write 10 s, pool 10 s.
- Any unexpected error in the poll loop: logged, 30 s pause, loop goes on.

## Cost
- Claude calls per message: one coach conversation of 1 to 6 API rounds (median about
  US$0.001 per message, US$0.06 for a 52-message day, measured in the 22 Nov replay;
  known-issues.md Task 15). A caption-less photo outside a workout adds one meal-estimate call.
  `/propose` uses `MODEL_COACH` (default `claude-opus-5-5`) JSON calls, plus one for missing
  pictures.
- Model: `claude-haiku-5-5` for chat and meals; `claude-opus-5-5` for week plans.
- Ledger: table `api_calls` in `data/gym.db` (time, model, tokens, US$), written for every round
  (`llm.py` `Claude._round`; prices in `PRICES`).
- Ceiling: monthly, not daily: `MONTHLY_CEILING_USD`, default US$5. Checked before every round;
  once reached, the reply is "This month's US$5 limit on AI calls is reached. I can't read new
  messages until next month; /today and /cost still work." `scripts/replay_day.py` spends real
  money and checks month cost plus `--max-cost` (default US$0.50) first.

## Gaps against the skill's rules
- Rule 1, one reply saying what was understood: mostly met (the prompt says
  "always state the numbers you logged"; failures after a save list what was saved). But a
  move-on reply can come as several messages (reply, then exercise card), and a model reply
  with no text falls back to the raw last tool result.
- Rule 2, free text never dead-ends: the fallback is a
  tool-use conversation, so saves have strict shapes, but the final reply is free text. Dead
  ends remain: "Sorry, I have no answer to that.", "Sorry, I could not reach the coach just
  now. Please try again.", and "I can only read text for now." for stickers or voice.
- Rule 3, corrections to the last saved item: met (`fix_set`, `remove_set`, `fix_cardio`,
  `correct_meal`, `fix_past_set`). Only meals and cardio target "the last" entry by code;
  sets rely on the model picking the set.
- Rule 6, local record of message, reply and branch: met in `data/gym.db`
  (`chat` + `trace`); `data/bot.log` has receipt and reply lines but no handling branch.
  Messages from other senders are dropped with no log line.
- Rules 10–11, kept connection and send retries: met for sends (kept connection, 4 tries on connect
  errors). The long poll has no backoff beyond a fixed 5 s pause.
- Rule 12, persisted offset and outbox: offset NOT persisted (memory only; the plan
  said `kv`). After a restart, Telegram re-delivers any update not yet confirmed, so a message
  handled just before a stop can be handled twice (a set logged twice; inferred, not seen in
  the docs). Outbox exists (`chat.delivered`), but only for the same day; older unsent
  replies are dropped.
- Rule 16, restart script, then check the log: met in CLAUDE.md and plan Task 9h.
  No restart script exists. CLAUDE.md names the log as `data` + backspace + `ot.log` (a
  mangled `\b`); README has the right path `data\bot.log`.
- Rule 18, cost ledger and ceiling: met (`api_calls`, monthly US$5 ceiling checked per round).
  The ceiling is monthly, not daily.
- Rule 19, no test messages to real people: met. Tests use `FakeTelegram` and `FakeClaude`
  (`tests/fakes.py`); the other-sender check was done in tests, not with a second account
  (known-issues.md, Task 11).

None of these gaps is in `docs/open-items.md` yet.
