# Inbox

## Open

**Can you send the bot one real meal photo and tell me if its estimate looked reasonable?** (from slot 1, 2026-11-16, plan Task 16, live check of meals)
- What it is: the bot can now estimate calories and protein from a photo of a meal and keep a running total for the day. It has only been tested with fake data, so it needs one real photo.
- Example: you photograph your lunch and send it in the Telegram chat. The bot replies something like "About 650 kcal, 35 g protein (chicken rice). Today: 1,420 of 2,000 kcal, 78 of 130 g protein." Then you send `/cost` to see that the month's cost rose by less than US$0.01.
- Why it matters: if the estimate is far off or the reply is wrong, the meal feature (milestone 2) needs fixing before the weekly review builds on it. Until you do this, the weekly review tasks wait.
- Options: **Default:** send one photo now (the bot was restarted on the new code today), then reply "ok" if the estimate looked reasonable, or say what was off. Or send it later; the tasks that wait stay waiting.
- Card sent 2026-11-16, card 1 (orchestrator). Bot restart at 15:31 checked in bot.log: "bot started", no error after.
- Brian (2026-11-16): "for the gym bot, I want to set further specification of what I need. If you insist that I message the bot on Telegram just to test connectivity, that's fine, otherwise that can wait until a real gym session". Orchestrator: no test message is needed (the bot answered him on 13 Nov); this check waits for a real meal or session.

## Answered

**Can you create the Telegram bot and put three keys into the `.env` file?** (from session "kickoff", 2026-11-13, plan Task 10, the Telegram bot and keys)
- What it is: the program needs three secret values that only you can get: a token for a new
  Telegram bot, your own Telegram user number, and an Anthropic API key. They go into the file
  `C:\Users\brian\OneDrive\Documents\workspace\repo\gym-coach\.env`, which git ignores.
- Example: in Telegram you message the account "BotFather", send `/newbot`, pick a name, and it
  replies with a token that looks like `1234567890:AAH...`. The orchestrator walks you through
  each step, one at a time.
- Why it matters: without these the bot cannot message you, and the builders cannot run the
  real end-to-end check (plan Task 11). All other tasks carry on meanwhile.
- Options: **Default:** you do it when the orchestrator sends the first step, and you also set
  a US$5 monthly spend limit in the Anthropic Console as a second safety net. Or tell the
  orchestrator a later time.
- Brian (2026-11-13): "API keys added" (bot token and Anthropic key set; the user number stays empty).
- Brian (2026-11-13): "ok" (to the orchestrator's question "How should the bot learn your Telegram user number?"; Default: the bot saves the first sender's number and confirms in Telegram; Brian messages it as soon as it starts). Plan Task 9a.
