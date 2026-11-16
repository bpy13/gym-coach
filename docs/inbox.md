# Inbox
- Card sent 2026-11-16, card 1 (orchestrator). Bot restart at 15:31 checked in bot.log: "bot started", no error after.
- Brian (2026-11-16): "for the gym bot, I want to set further specification of what I need. If you insist that I message the bot on Telegram just to test connectivity, that's fine, otherwise that can wait until a real gym session". Orchestrator: no test message is needed (the bot answered him on 13 Nov); this check waits for a real meal or session.

## Open

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
