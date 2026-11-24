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
- 2026-11-16, Brian: plan Tasks 12 to 15 (calorie and protein targets, meal photo estimates, weekly body numbers, the cost-limit test; code and tests only) are built now, before milestone 1's live check (Task 11). The live meal check (Task 16) and Phase 3 still wait for Task 11. (Brian, 2026-11-16: "Yes, build now")
- 2026-11-16, Brian: he reviews and approves the schedule and plan with the orchestrator, not by a reply to the bot in Telegram; in Telegram he reads the session message and trains by it. (Brian, 2026-11-16: "let's review and approve here instead. I don't expect having to approve at Telegram message, I'll just read the message over there and go workout according to the instruction sent"). Asked whether logging one real session per gym from his phone still stands, he said: "same as 1". What that changes in milestones 1 and 3 is open until his specification below.
- 2026-11-16, Brian: he will set a further specification for the bot; the live meal photo check (Task 16) and any test message wait for a real gym session. (Brian, 2026-11-16: "for the gym bot, I want to set further specification of what I need. If you insist that I message the bot on Telegram just to test connectivity, that's fine, otherwise that can wait until a real gym session")
- 2026-11-16, Brian: every exercise in a session message carries a picture: his photo of the machine, or an illustration of the movement for dumbbell, cable and bar exercises; none is left without (plan Task 9i). (Brian, 2026-11-16: "shouldn't the gym bot also send illustration?")
- 2026-11-16, Brian: he still reports sets and meals to the bot in Telegram; only the approval of the schedule happens with the orchestrator. (Brian, 2026-11-16: "b", to the question "(a) you never write to the bot at all, or (b) you still report sets and meals to the bot, and only the approval happens here?")
- 2026-11-16, Brian: he wants a session on Sunday. (Brian, 2026-11-16: "I'd like to spend a session on Sunday", in answer to the question on one weekly session at his parents' gym). Not yet settled: whether Sunday is at his parents' gym, and whether it replaces one of Monday, Wednesday, Friday or is a fourth session; asked 16 Nov.
- 2026-11-16, Brian: the Sunday session is at his parents' gym, and the three strength days are Tuesday, Thursday and Sunday, replacing Monday, Wednesday, Friday (plan Task 9j). (Brian, 2026-11-16: "yes parents' gym" (typed "yesw parents' gym") and "do Tue, Thu, Sun"). Read by the orchestrator as: Tuesday and Thursday at home, Sunday at his parents'; cardio days not yet decided (asked).
- 2026-11-16, Brian: each exercise is one Telegram message holding the machine photo, the illustration and the task (name, sets, reps, weight); a session with five exercises sends five such messages (plan Task 9k). (Brian, 2026-11-16: "(should be image + illustration + task) as one message. So if 5 task on gym, like on Tuesday, 5 messages should be sent")
- 2026-11-16, Brian: during a strength session the bot shows one exercise at a time; the next one comes as he reports his progress, so he reads it while resting (plan Task 9l). (Brian, 2026-11-16: "should show 1 at a time, and as I report my progress and during resting, show next")
- 2026-11-16, Brian: cardio days are Monday, Wednesday and Friday (plan Task 9m); with strength on Tuesday, Thursday and Sunday, Saturday has no session. (Brian, 2026-11-16: "cardio should be Mon Wed Fri")
- 2026-11-16, Brian: the first exercise of a session is sent at 07:00 with the session message, not on a "start" from him (plan Task 9l). (Brian, 2026-11-16: "Send at 07:00")
- 2026-11-16, orchestrator (Brian may change it): while a strength session is open, a reply is logged against the exercise now shown; the exercise completes when logged sets reach the planned sets or he writes "next", "done" or "skip"; then the next exercise message follows the short reply (plan Task 9l).
- 2026-11-16, Brian: the week of 17 to 22 Nov is approved as stored (strength Tue 17 and Thu 19 at home and Sun 22 at his parents', cardio Wed 18 and Fri 20); the orchestrator marked the five sessions approved in the database at 16:57. (Brian, 2026-11-16: "Approve and mark", to "Approve the week of 17-22 Nov and let me mark it approved in the bot's database?")
- 2026-11-17, Brian: the weekly check-in asks for body weight only; the waist question is dropped (plan Task 14b). A waist number he volunteers is still stored. It replaces the waist part of the 2026-11-13 line on weekly body numbers. (Brian, 2026-11-17: "gym: drop it", to "Gym: keep or drop the waist question."; on 2026-11-16 he had asked "for gym app, what's the point of asking waist")
- 2026-11-17, Brian: the form tip under each exercise picture is left out of the session messages for now; it comes back only when he asks (plan Task 14c). Reading "drop it" as removing the tip from the messages, not only closing the question, is the orchestrator's. (Brian, 2026-11-17: "gym: tip can be for later, drop it for now, and reconsider when I request", after being told the tip is cut at about 150 characters)
- 2026-11-17, Brian: the first real session message (Tue 17 Nov, 07:00) arrived and read correctly. (Brian, 2026-11-17: "it arrived and read correctly")
- 2026-11-17, Brian: the form tip comes back under each exercise as one short line (plan Task 14d); it replaces the 2026-11-17 line that left it out. (Brian, 2026-11-17: "gym tip: if it's just one line it's okay")
- 2026-11-17, Brian: the bot reads each message with the earlier messages of the session in view and copes with a message or reply that went missing (plan Task 14g). Keeping the chat text in `data/gym.db` for 30 days to do this is the orchestrator's call; Brian may change it. (Brian, 2026-11-17: "It seems to me the Telegram bot has no context and cannot read previous messages, please fix that because if missed message it messes everything without the capability to handle session messages")
- 2026-11-17, orchestrator (Brian may change it): a strength day is marked `done` when its session flow closes ("Session done"), or silently at 21:00 when sets are logged but the flow never closed; no longer at the first logged set (plan Task 14g).
- 2026-11-17, slot 1 (builder's default, Brian may change it): while a session is on, a request to change an exercise changes today's session only (swap, drop or new weight; logged sets kept). A change to a future week revises a proposed week that is waiting; with none waiting it is kept as a note for the next `/propose` and no week is written (plan Task 14g).
- 2026-11-23, Brian: talking to the bot must feel like talking to a real gym instructor. The
  model leads the chat with tools that change the records; code still enforces the hard rules
  inside the tools; the label-sorting call and its fixed replies go (plan
  `docs/plans/2026-11-23-coach-chat.md`, Task 15). (Brian, 2026-11-23: "we're doing this
  rule-based? no wonder the bot feels so dumb to speak to. Can we change that?", then "I need
  speaking to the bot feels like speaking to real gym instructor", then "Go")
- 2026-11-23, Brian: the parents' combined machine is a seated leg extension with a lying leg
  curl, not a seated leg curl (Task 15a). (Brian, 22 Nov chat: "it is a lying leg curl / seated
  leg extension, which you have mistakenly identified as seated leg curl")
- 2026-11-23, Brian: the bot logs cardio. A `log_cardio` tool saves the activity, minutes and,
  when he gives them, distance and average heart rate in a new `cardio` table; a logged cardio
  entry marks the day done and shows in the summary. The fields and marking the day done at
  once are the builder's call; Brian may change them. (Brian, 2026-11-23: "I thought the app
  would log cardio session", then "Yes, add it" to adding cardio logging and saving the
  23 Nov jog.)
- 2026-11-24, Brian: the coach uses the weights he last lifted when it recommends weights (plan Task 14k). The rules are the orchestrator's call (Brian may change them): start from the last logged weight, raise by the smallest step only when every set reached the top of the rep range, keep otherwise, lower when he missed the bottom. (Brian, 2026-11-24: "please do.")
- 2026-11-24, orchestrator (Brian may change it): the step for a weight change is the smallest gap in that exercise's own logged weights; else the smallest gap of another exercise on the same equipment at that gym; else, for a machine, the commonest gap among that gym's machines of the same kind (cable or pin stack) that divides the last weight (home machines: 7 kg, so lat pulldown 35 kg goes to 42 kg); else 2 kg for dumbbells and 2.5 kg for the rest (plan Task 14l). The code sets the planned weight by the Task 14k rule for every strength session not yet started, and for a newly proposed week; the model's number is the fallback for an exercise with no history.
- 2026-11-24, orchestrator (Brian may change it): history is matched by exercise name first, then, for a machine, by the same equipment at the same gym when the names share a word other than generic ones (machine, cable, seated...), the best overlap winning and a tie matching nothing ("Chest press" finds "Machine chest press"). Free weights match by name only. Dumbbell and barbell history counts at either gym; a machine's history from the other gym is shown as a note only (plan Task 14l; free weights by name only is slot 1's narrowing, after "Incline dumbbell press" took the flat bench press's sets).
- 2026-11-24, Brian: the day's weights follow his last session also for a week planned earlier (plan Task 14l; Brian: "why don't it use last time weight"), and the coach reads the trend across his sets and recommends from it (plan Task 14m; thresholds are the orchestrator's call, Brian may change them). (Brian, 2026-11-24: "also it should be able to see from my last rep whether I'm struggling (decreasing rep / weight etc) or if it's too easy (increasing rep / weight)", "and provide recommendation accordingly")
- 2026-11-24, orchestrator's call (Brian may change it): how the last day's sets are read (plan Task 14m, replacing the Task 14k rule). Struggling: reps fell from set to set at the same weight by 3 or more in total, or he lowered the weight during the day, or a set ended under the bottom of the rep range; too easy: he raised the weight and still reached the top of the range on the last set, or every set reached the top or more (reaching the top counts, as in Task 18's rule); steady otherwise. Too easy: one step up from his last top weight. Steady: his last top weight, aim for one more rep. Struggling: stay at the weight where it went wrong (where the reps fell, or the weight he lowered from); one step under only when the day before at that gym was also struggling at that same weight. The label comes from the last day; the earlier days only decide that step down. During a workout the coach reads today's sets the same way and says go up, hold or drop for the next set.
- 2026-11-24, orchestrator (Brian in the gym: "warm up is gone"): the coach always sees the fixed warm-up routine and its state, never makes up another, and starts the workout with a `start_workout` tool (the same as the word "start") when he asks to begin, asks for the warm-up, or asks for today's schedule before the warm-up was sent; `/today` says the warm-up comes first until it is done (plan Task 14m).
- 2026-11-24, orchestrator's call (Brian may change it): too easy wins whenever the last set was at the day's top weight and reached the top of the range; otherwise struggling is checked first (plan Task 14m). So 21 kg x 15, 12 then 28 kg x 12 at 8-12 reads too easy, and so does 21 kg x 15, 12, 12.
- 2026-11-24, Brian: the coach shows what he did last time for each exercise and suggests no weight and no reps (plan Task 14o); this replaces the recommendations of Tasks 14k to 14m. Orchestrator's reading (Brian may change it): advice only when he asks; an exercise with no history says so; the week proposal follows the same way. (Brian, 2026-11-24: "For reps, no need to suggest weight and rep, just show last time data")
