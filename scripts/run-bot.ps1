# Starts the gym-coach bot. Run by the logon task; works from any folder.
$project = Split-Path -Parent $PSScriptRoot
Set-Location $project
& 'C:\Users\brian\miniconda3\envs\gym-coach\python.exe' -m gym_coach --exit-with-parent
