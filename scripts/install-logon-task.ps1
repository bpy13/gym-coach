# Registers the logon task "gym-coach-bot": starts the bot with no window when you log on.
# The task starts pythonw.exe directly (no powershell or conhost between), so
# Stop-ScheduledTask ends the bot itself.
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $env:USERPROFILE 'miniconda3\envs\gym-coach\pythonw.exe'
if (-not (Test-Path $pythonw)) { throw "pythonw.exe not found: $pythonw" }
$action = New-ScheduledTaskAction -Execute $pythonw -Argument '-m gym_coach' `
    -WorkingDirectory $project
# Task Scheduler needs DOMAIN\user here; a bare user name fails with "The parameter is incorrect".
$user = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'gym-coach-bot' -Action $action -Trigger $trigger `
    -Settings $settings -Description 'Gym coach Telegram bot' -Force -ErrorAction Stop | Out-Null
# Confirm from Task Scheduler itself, so a failed registration never reports success.
Get-ScheduledTask -TaskName 'gym-coach-bot' -ErrorAction Stop | Out-Null
Write-Output 'Registered task gym-coach-bot'
