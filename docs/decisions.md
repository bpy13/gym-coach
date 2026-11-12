# Decisions

What was decided, why, when, and whose call it was (Brian / Claude's default / builder check).
Change these only with a reason, and note the change here (mark reversed decisions as reversed
rather than deleting them). Nothing Brian didn't say is recorded as his decision.

## Scope
- 2026-11-13, Brian: the goal is to build muscle and lose fat at the same time.
- 2026-11-13, Brian: no past records to import. Brian describes his history in words: he
  joined a commercial gym and trained with a personal trainer for about 2 months, two 1-hour sessions a
  week. The coach starts from that description plus a first-week test of working weights.
- 2026-11-13, Brian: he no longer trains at the commercial gym. The two clubhouse gyms are his only gyms.
- 2026-11-13, Brian: the coach works out the weekly schedule (days, session length) from his
  stats ("we should figure that out based on my stat"). He has not fixed any days.
- 2026-11-13, Brian ("default"): no injuries or medical limits. The coach uses the normal
  exercise list.
- 2026-11-13, Brian ("default"): he records body weight and waist once a week and follows a
  daily protein and calorie target himself. He adds: "I should take photos of my meal where
  possible". What the project does with meal photos is still open (round 3).
- 2026-11-13, Brian ("default"): he saves equipment photos into two folders on this PC, one
  per gym. Claude drafts each equipment list once and he confirms it.
- 2026-11-13, Brian: beginner level. He can train any time on weekdays, any time on Sunday,
  and on Saturday morning only. (His age, height and weight are personal data: they go in the
  ignored `data/` folder, not in this public file.)
- REVERSED 2026-11-13 (replaced by the Drive folder below). Brian ("default"): he uploads
  each meal photo on the phone page. The AI estimates calories and protein and keeps a daily
  total.
- REVERSED 2026-11-13 (replaced by the Telegram bot; photos stay in the Telegram chat).
  Brian ("default, but photos should be cleaned from Drive to not clog space"):
  he saves meal photos into a Google Drive folder. Claude estimates calories and protein once
  a day, in the evening, and writes them into the sheet's meals tab. The project removes
  photos from Drive after it has estimated them.
- 2026-11-13, Brian ("default, for now aim for 3 sessions per week during late afternoon. I
  also would do cardio (heart rate ~130) in between"): three strength sessions a week, in the
  late afternoon, for now. He also does cardio at a heart rate of about 130.
  Claude's reading, not confirmed: "in between" means on days between the strength sessions.
  The bot's schedule proposal states this reading, and he corrects it in the chat if wrong.
  Saturday is free in the morning only, so late-afternoon sessions fall on weekdays or Sunday.
- 2026-11-13, Brian ("default"): the three milestones in `docs/milestones.md` are approved.
- 2026-11-13, Brian ("if no more question then go"): go-ahead for the plan
  `docs/plans/2026-11-13-telegram-gym-coach.md`, built by the orchestrator's workers.

## Platform and hosting
- REVERSED 2026-11-13 (replaced by the Google Sheet below). Brian ("default"): a phone web
  page for logging sets in the gym. An AI coach reviews the logs and adjusts the plan once a
  week.
- REVERSED 2026-11-13 (replaced by the Telegram bot below). Brian ("gym progress is easily
  recorded on a spreadsheet which can be shared
  via Google Drive"; then "default"): one Google Sheet replaces the phone page. It holds the
  week's plan, the workout log, the weekly body numbers and the meals. He logs in the Google
  Sheets phone app. Once a week Claude reads the sheet on this PC and writes next week's plan
  and a short review into it. Nobody builds a page, a hosted database or a sign-in.
- 2026-11-13, Brian ("I just want an easy way for me and the app to share data: me to
  receive the gym schedule on that particular day, and me to report what I've ended up doing
  in response to the schedule, as well as me to share the meal I've eaten"; then "a"): a
  Telegram chat bot, run by a small program on this PC. The bot messages him the day's session
  for that day's gym. He replies in plain words with what he did and sends meal photos into
  the same chat; the bot replies with a calorie and protein estimate. The program saves every
  session and meal to a record file on this PC, which git ignores. While the PC is off the bot
  is silent and answers waiting messages when the PC starts.
- 2026-11-13, Brian: the AI runs on paid Claude API calls ("can use API key from Anthropic").
- 2026-11-13, Brian ("b"): the scheduled runs on this PC use the API key, not his Claude
  subscription, with a hard ceiling of US$5 a month. The runs stop calling the AI once the
  month's cost reaches it.
- REVERSED 2026-11-13 (no page to host). Brian ("default"): a free hosting service runs the
  page and the database. Only his Google account can sign in.
- 2026-11-13, Brian ("default"): he checks the dumbbell racks on his next visit. Until then
  the coach assumes 2 kg steps at both gyms.
- 2026-11-13, Brian: both gyms have a dual cable machine (he confirmed the cable photo belongs
  to his parents' gym).
- 2026-11-13, Brian ("default"): Haiku 5.5 (`claude-haiku-5-5`) reads meal photos and his
  session reports. Opus 5.5 (`claude-opus-5-5`) writes the first plan, the weekly review and
  next week's plan. Prices quoted from Anthropic's pricing page on 2026-11-13, per million
  tokens in/out: Haiku 5.5 US$0.10/US$0.50, Opus 5.5 US$4/US$20.

## Data and secrets
- Claude's default, 2026-11-13: records live in one SQLite file, `data\gym.db`. The profile and
  both equipment lists live in `data\profile.md` and `data\equipment.md`. Secrets live in
  `.env`: the Telegram bot token, the Anthropic API key and Brian's Telegram user id.
- Claude's default, 2026-11-13: Python 3.12 in a conda env named `gym-coach`. Dependencies:
  the `anthropic` SDK only. The program calls Telegram's HTTP interface directly with `httpx`,
  which the SDK already installs. Tests use pytest with a fake Telegram and a fake Claude.
  Reason: least new code and no extra library for a few HTTP calls.
- Claude's default, 2026-11-13: the bot starts at Windows logon through a scheduled task and
  runs with no window.
- 2026-11-13, Brian: all personal data is git-ignored (logs, measurements, health notes,
  photos, `.env`).

## Behaviour and rules
Claude's defaults from the builder check, 2026-11-13. Brian has not reviewed these; each is a
setting or a small change.
- The bot answers only Brian's own Telegram account and ignores everyone else. Reason: the
  chat holds health data, and anyone can find a bot by name.
- Session message at 07:00 Hong Kong time on training days; weekly review on Sunday at 20:00;
  body weight and waist prompt on Monday at 07:00. All three times are settings. If the PC was
  off at that time, the bot sends the message when it starts, on the same day only.
- After each report the bot repeats what it logged ("Logged: chest press 35 kg, 10, 10, 8").
  He corrects it by replying. Reason: free-text parsing can misread a number.
- The first week uses light starting weights and asks how hard each set felt, to find his
  working weights. The coach proposes the weekly schedule in the chat and he approves it there.
- Progression is rule-based and cautious: add weight only after he hits the top of the rep
  range on every set. Fat loss target at most 0.5-1% of body weight a week. The bot states
  that it gives general fitness guidance, not medical advice.
- The program does not keep meal photos on disk. It stores only the estimate. The photos stay
  in the Telegram chat.
- Cost: the program records each call's token usage and price, and stops calling Claude once
  the month reaches US$5. It tells him in the chat when that happens.
- Messages are in English; weights in kg.

## UI

## Repository
- 2026-11-13, Brian ("default"): project name `gym-coach`, folder `repo\gym-coach\`.
- 2026-11-13, Brian: public GitHub repo on his account, created at "go".
- 2026-11-13, Brian: the bot learns his Telegram user number from the first private message instead of him copying it into `.env`; a value in `.env` still wins (plan Task 9a). (Brian, 2026-11-13: "ok" (to the orchestrator's question "How should the bot learn your Telegram user number?"; Default: the bot saves the first sender's number and confirms in Telegram; Brian messages it as soon as it starts))
- 2026-11-13, Brian: each session message shows the photo of the machine for each exercise, from his equipment photos, and lists every exercise with sets, reps and weight (plan Task 9e). (Brian, 2026-11-13: "message should show images so I know which machine to use" (on seeing the first proposed week, which named machines in text only))
- 2026-11-13, Brian: dumbbell (free-weight) exercises show an illustration of the movement, not only the name; source by default the open free-exercise-db, licence to be checked (plan Task 9f). (Brian, 2026-11-13: "dumbbell should show illustration, hard to understand just from the exercise name")
