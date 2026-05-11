<#
.SYNOPSIS
Register the Teams chat-push as Windows scheduled tasks restricted to
BD 18:00 -> 01:00.

.DESCRIPTION
Two Task Scheduler entries on each dev machine:

  "NAPCO Nucleus - Chat Push"            every 15 min, 18:00 -> 01:00
                                         window = last 15 min
  "NAPCO Nucleus - Chat Push (Backfill)" once daily at 18:00
                                         window = last 1080 min (18 hr)

The backfill catches any chat that arrived during the BD daytime gap
(01:00 -> 18:00) when the regular cron is intentionally off. Both
tasks run on the dev's local clock, which is BD time.

Re-running this script is idempotent — both entries are dropped and
re-created so it doubles as the upgrade path.

.EXAMPLE
    .\scripts\register-chat-push-task.ps1
    .\scripts\register-chat-push-task.ps1 -IntervalMinutes 30
    .\scripts\register-chat-push-task.ps1 -Unregister
#>
param(
    [int]$IntervalMinutes = 15,
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"
$mainTask = "NAPCO Nucleus - Chat Push"
$backfillTask = "NAPCO Nucleus - Chat Push (Backfill)"

if ($Unregister) {
    foreach ($name in @($mainTask, $backfillTask)) {
        if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $name -Confirm:$false
            Write-Host "Removed: $name"
        } else {
            Write-Host "Not present: $name"
        }
    }
    return
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$mainBat = Join-Path $scriptDir "push-chat.bat"
$backfillBat = Join-Path $scriptDir "push-chat-backfill.bat"

foreach ($p in @($mainBat, $backfillBat)) {
    if (-not (Test-Path $p)) {
        Write-Error "Missing helper: $p"
        exit 1
    }
}

# Drop existing entries so this script is idempotent.
foreach ($name in @($mainTask, $backfillTask)) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
    }
}

# BD window: anchor today at 18:00 local time. If that's in the past,
# anchor tomorrow. Repeats every $IntervalMinutes for 7 hours, so the
# final fire is at 01:00 the next morning (window close).
$today6pm = (Get-Date).Date.AddHours(18)
if ($today6pm -lt (Get-Date)) {
    $today6pm = $today6pm.AddDays(1)
}

$mainAction = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$mainBat`"" `
    -WorkingDirectory $repoRoot

# Repeats every $IntervalMinutes for the 7-hour BD window. RepetitionDuration
# is inclusive of the trigger fire, so 7h covers 18:00..01:00.
$mainTrigger = New-ScheduledTaskTrigger -Daily -At $today6pm
$mainTrigger.Repetition = (New-ScheduledTaskTrigger `
    -Once -At $today6pm `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Hours 7)).Repetition

$mainSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

Register-ScheduledTask `
    -TaskName $mainTask `
    -Action $mainAction `
    -Trigger $mainTrigger `
    -Settings $mainSettings `
    -Description "Pushes the last $IntervalMinutes min of Teams chat into NUCLEUS_CENTRAL_PATH. Runs every $IntervalMinutes min during BD 18:00-01:00 window." `
    -RunLevel Limited `
    | Out-Null

Write-Host "Registered: $mainTask  every $IntervalMinutes min, BD 18:00-01:00, first run $today6pm"

# Backfill: once per day at 18:00, last-minutes=1080 to sweep the daytime gap.
$backfillAction = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$backfillBat`"" `
    -WorkingDirectory $repoRoot

$backfillTrigger = New-ScheduledTaskTrigger -Daily -At $today6pm

$backfillSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

Register-ScheduledTask `
    -TaskName $backfillTask `
    -Action $backfillAction `
    -Trigger $backfillTrigger `
    -Settings $backfillSettings `
    -Description "Once-daily 18:00 BD backfill: pushes the last 1080 min of chat to cover the 01:00-18:00 daytime gap." `
    -RunLevel Limited `
    | Out-Null

Write-Host "Registered: $backfillTask  daily at $today6pm  (--last-minutes 1080)"
Write-Host ""
Write-Host "View:    Task Scheduler -> Task Scheduler Library"
Write-Host "Run now: Start-ScheduledTask -TaskName '$mainTask'"
Write-Host "Remove:  .\scripts\register-chat-push-task.ps1 -Unregister"
