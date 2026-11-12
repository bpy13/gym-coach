# Board: gym-coach

## Workers

## Ready to build

## Waiting on Brian

## Done and carried over
- Task 3, Telegram client: done 2026-11-13 (slot 4). 8 tests for it pass, ruff clean.
- Task 2, record storage (`store.py`): done 2026-11-13 (slot 2). 15 tests and ruff pass.
- Task 1, project skeleton and environment: done 2026-11-13 (slot 1). Conda env `gym-coach`
  built; 9 tests and ruff pass.
- Task 5, gym for the day and coach context: done 2026-11-13 (slot 3). 8 tests pass, ruff clean.
- Task 4, Claude wrapper with cost ceiling (`llm.py`): done 2026-11-13 (slot 1). 40 tests pass, ruff clean.
- Task 6, first schedule and plan proposal (`planner.py`, `prompts.py`): done 2026-11-13 (slot 1). 48 tests pass, ruff clean.
- Task 7, message router and report logging (`router.py`, `reports.py`): done 2026-11-13 (slot 1). 62 tests pass, ruff clean.
- Task 8, daily session message and scheduler (`scheduler.py`, `messages.py`): done 2026-11-13 (slot 1). 72 tests pass, ruff clean.
- Task 9, main program and logon start (`app.py`, `__main__.py`, `scripts\`): done 2026-11-13 (slot 1). 79 tests pass, ruff clean. Logon task not registered: Brian runs `scripts\install-logon-task.ps1` himself.
- Task 9a, bot pairs with the first private sender (`telegram.py`, `config.py`): done 2026-11-13 (slot 1). 83 tests pass, ruff clean; `--check` prints "config ok (owner not paired yet)".
- Task 9b, bot hang and Stop-ScheduledTask leftover: code fixed 2026-11-13 (slot 1), 87 tests pass, ruff clean. Not verified against real Telegram (orchestrator's order); waiting for Brian to restart the bot, orchestrator checks bot.log.
- Task 9c, /start proposes the first week (`router.py` `/propose`): done 2026-11-13 (slot 1). 88 tests pass, ruff clean. Not run on the real bot: Brian restarts it, orchestrator checks.
- Task 9d, Stop-ScheduledTask really ends the bot: done 2026-11-13 (slot 1). The logon task now starts `pythonw.exe -m gym_coach` directly (no powershell/conhost); 86 tests pass, ruff clean. Not run on the real task: Brian stops the old bot, re-runs `scripts\install-logon-task.ps1`, orchestrator checks.
