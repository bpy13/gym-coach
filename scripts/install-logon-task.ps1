# Registers the logon task "gym-coach-bot": starts the bot with no window when you log on.
$ErrorActionPreference = 'Stop'
$script = Join-Path $PSScriptRoot 'run-bot.ps1'
$action = New-ScheduledTaskAction -Execute 'conhost.exe' `
    -Argument "--headless powershell.exe -NoProfile -File `"$script`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'gym-coach-bot' -Action $action -Trigger $trigger `
    -Settings $settings -Description 'Gym coach Telegram bot' -Force | Out-Null
Write-Output 'Registered task gym-coach-bot'
