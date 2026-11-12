# Registers the logon task "gym-coach-bot": starts the bot with no window when you log on.
$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot 'run-bot.ps1'
$action = New-ScheduledTaskAction -Execute 'conhost.exe' `
    -Argument "--headless powershell.exe -NoProfile -File `"$script`""
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
