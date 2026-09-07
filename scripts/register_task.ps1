# Registers (or re-registers) the daily collection task.
#
# run_collection.bat referenced this script from day one, but it was never
# actually written — so the scheduled task existed only as a one-off manual
# registration that nothing could reproduce or review. That is how it ended
# up with the settings that silently broke collection:
#
#   DisallowStartIfOnBatteries = True   -> on a laptop running on battery at
#                                          06:00 the task is REFUSED outright,
#                                          surfacing as LastTaskResult
#                                          0x800710E0 ("The operator or
#                                          administrator has refused the
#                                          request") and no log line at all.
#   StopIfGoingOnBatteries     = True   -> a run that starts on AC dies if the
#                                          charger is pulled mid-fetch.
#   StartWhenAvailable         = False  -> a run missed because the machine was
#                                          asleep or off at 06:00 is never made
#                                          up. Three of the first four
#                                          scheduled days produced nothing.
#
# For a daily data collector on a personal laptop, all three defaults are
# wrong: a missed day is a permanent hole in a time series that cannot be
# backfilled (see IMPLEMENTATION.md §0 — the collection window is wall-clock
# bound). Run this from an elevated-or-not PowerShell in the repo root:
#
#     powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1
#
# The task runs as the current interactive user, so it only fires while that
# user is logged on. Running whether-logged-on-or-not requires storing
# credentials with the task; that is a deliberate decision for the operator to
# make, not something this script does silently.

$ErrorActionPreference = 'Stop'

$TaskName = 'APIx-DailyCollection'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$BatPath  = Join-Path $RepoRoot 'scripts\run_collection.bat'

if (-not (Test-Path $BatPath)) {
    throw "Cannot find $BatPath"
}

$action = New-ScheduledTaskAction -Execute $BatPath -WorkingDirectory $RepoRoot

# 06:00 daily. RandomDelay spreads the request off an exact-hour boundary —
# politeness, consistent with the rate limiting in acquisition/compliance.py.
$trigger = New-ScheduledTaskTrigger -Daily -At 6am
$trigger.RandomDelay = 'PT10M'

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

$principal = New-ScheduledTaskPrincipal `
    -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description 'APIx daily airfare collection (scripts/run_collection.py)' `
    -Force | Out-Null

Write-Host "Registered '$TaskName'."
$info = Get-ScheduledTaskInfo -TaskName $TaskName
Write-Host ("  Next run : {0}" -f $info.NextRunTime)
Write-Host ("  Last run : {0} (result {1})" -f $info.LastRunTime, $info.LastTaskResult)
