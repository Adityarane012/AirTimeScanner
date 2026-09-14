# Registers (or re-registers) the collection task.
#
# Run from the repo root; no elevation needed:
#
#     powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1
#
# This task has silently lost data twice, each time in a different way, so
# both histories are kept here next to the settings that fix them.
#
# 1. Refused and never made up (found 2026-09-07). The task was first
#    registered by hand, and nothing recorded its settings. The defaults were
#    wrong for a laptop:
#
#      DisallowStartIfOnBatteries = True  -> refused outright on battery at
#                                            06:00 (0x800710E0), no log line
#      StopIfGoingOnBatteries     = True  -> killed if the charger is pulled
#      StartWhenAvailable         = False -> a run missed while off or asleep
#                                            is never made up
#
#    Three of the first four scheduled days produced nothing.
#
# 2. Launched into a window that got closed (found 2026-09-14). With (1)
#    fixed, the laptop was still shut down at 06:00 every day, so every run
#    was a catch-up run shortly after login. Those ran run_collection.bat in a
#    cmd console on the desktop, blank because output went to the log. Runs
#    were killed with 0xC000013A (console closed), and 09-10 to 09-14 were
#    lost. Fixed by launching pythonw through run_collection_scheduled.pyw,
#    which has no console at all.
#
# Why hourly instead of once at 06:00: a single daily slot bets the whole day
# on one moment the machine may not be awake for. run_collection.py skips any
# source already collected today (apix.ops.collection_health.decide), so an
# hourly launch normally costs one small database query and no fetch. It
# catches up within the hour of any boot, and a failure gets retried later
# the same day instead of losing the day.
#
# The task runs as the current interactive user, so it fires only while that
# user is logged on. On this machine that is effectively whenever it is on.
# "Run whether logged on or not" (S4U) would also cover the gap between boot
# and login, but it needs the "log on as a batch job" right and has no
# network credentials. That is a decision for the operator, not something
# this script makes silently.

$ErrorActionPreference = 'Stop'

$TaskName   = 'APIx-DailyCollection'
$RepoRoot   = Split-Path -Parent $PSScriptRoot
$PythonW    = Join-Path $RepoRoot '.venv\Scripts\pythonw.exe'
$Launcher   = Join-Path $RepoRoot 'scripts\run_collection_scheduled.pyw'

foreach ($path in @($PythonW, $Launcher)) {
    if (-not (Test-Path $path)) { throw "Cannot find $path" }
}

$action = New-ScheduledTaskAction `
    -Execute $PythonW `
    -Argument "`"$Launcher`"" `
    -WorkingDirectory $RepoRoot

# Daily from midnight, repeating hourly for the whole day. RandomDelay moves
# each launch off the exact hour, in line with the rate limiting in
# acquisition/compliance.py.
$trigger = New-ScheduledTaskTrigger -Daily -At 12am
$trigger.Repetition = (New-ScheduledTaskTrigger -Once -At 12am `
    -RepetitionInterval (New-TimeSpan -Hours 1) `
    -RepetitionDuration (New-TimeSpan -Days 1)).Repetition
$trigger.RandomDelay = 'PT10M'

# A normal run takes well under a minute. Thirty minutes is generous and
# still ends a hung run before the next hourly launch. MultipleInstances
# IgnoreNew stops launches from stacking up behind a slow run.
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description 'APIx airfare collection, hourly; skips sources already collected today (scripts/run_collection.py)' `
    -Force | Out-Null

Write-Host "Registered '$TaskName'."
$info = Get-ScheduledTaskInfo -TaskName $TaskName
Write-Host ("  Next run : {0}" -f $info.NextRunTime)
Write-Host ("  Last run : {0} (result {1})" -f $info.LastRunTime, $info.LastTaskResult)
