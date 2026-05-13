<#
.SYNOPSIS
Register the Teams chat-push as two Windows Scheduled Tasks split by
BD time-of-day, matching the daily rhythm of US-client interaction.

.DESCRIPTION
Two Task Scheduler entries on each dev machine:

  "NAPCO Nucleus - Chat Push (Day)"      every  2 hr,  BD 10:00 -> 17:00
                                          fires at 10:00, 12:00, 14:00, 16:00
                                          window = last 120 min

  "NAPCO Nucleus - Chat Push (Evening)"  every 30 min,  BD 18:00 -> 24:00
                                          window = last  30 min

Day stops at 16:00 (not 18:00) so its last fire doesn't collide with
Evening's first fire at 18:00. Side effect: BD 16:00-17:30 chat is
not auto-pushed by either window (Evening's 18:00 tick only looks back
30 min). Manual catch-up if needed:
    py -3 -m teams.push_chat --last-minutes 90

Rationale: US clients arrive online around BD 19:00, so the evening
window pushes at a higher cadence to surface fresh chat into central
quickly. During BD daytime, internal-only chat doesn't need the same
freshness, so we batch at 2-hr intervals.

Both tasks run on the dev's local clock — dev machines are on BD time.

push-chat.bat (--last-minutes 15) remains the ad-hoc entry point for
"push my chat now" voice commands; that's untouched by this script.

Coverage gap: BD 00:00 -> 10:00 is NOT auto-pushed. If overnight chat
needs to land before the next 10:00 tick, run push-chat.bat manually
or call:
    py -3 -m teams.push_chat --last-minutes 600

Re-running this script is idempotent — both entries are dropped and
re-created so it doubles as the upgrade path.

.PARAMETER Unregister
Remove both tasks and exit.

.EXAMPLE
    .\scripts\register-chat-push-task.ps1
    .\scripts\register-chat-push-task.ps1 -Unregister
#>
param(
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"

$dayTask = "NAPCO Nucleus - Chat Push (Day)"
$eveTask = "NAPCO Nucleus - Chat Push (Evening)"
$legacyTasks = @(
    "NAPCO Nucleus - Chat Push",
    "NAPCO Nucleus - Chat Push (Backfill)"
)

if ($Unregister) {
    foreach ($name in @($dayTask, $eveTask) + $legacyTasks) {
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

# Resolve a usable python — venv preferred, system py as fallback.
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    $pyExe = $venvPython
    $pyArgPrefix = ""
} else {
    $pyExe = "py"
    $pyArgPrefix = "-3 "
}

# Drop ALL prior chat-push entries (new + legacy single-window setup)
# so this script is idempotent and doubles as the upgrade path from
# the pre-split schedule.
foreach ($name in @($dayTask, $eveTask) + $legacyTasks) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
    }
}

function Register-ChatPush {
    param(
        [string]$Name,
        [int]$StartHour,
        [int]$DurationHours,
        [int]$IntervalMinutes,
        [int]$LastMinutes,
        [string]$Description
    )
    # Anchor to today's StartHour BD-local. If that's already past + the
    # window has already closed, anchor tomorrow.
    $anchor = (Get-Date).Date.AddHours($StartHour)
    $windowClose = $anchor.AddHours($DurationHours)
    if ((Get-Date) -gt $windowClose) {
        $anchor = $anchor.AddDays(1)
    }

    $argString = $pyArgPrefix + "-m teams.push_chat --last-minutes $LastMinutes"
    $action = New-ScheduledTaskAction `
        -Execute $pyExe `
        -Argument $argString `
        -WorkingDirectory $repoRoot

    $dailyTrigger = New-ScheduledTaskTrigger -Daily -At $anchor
    $dailyTrigger.Repetition = (New-ScheduledTaskTrigger `
        -Once -At $anchor `
        -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
        -RepetitionDuration (New-TimeSpan -Hours $DurationHours)).Repetition

    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

    Register-ScheduledTask `
        -TaskName $Name `
        -Action $action `
        -Trigger $dailyTrigger `
        -Settings $settings `
        -Description $Description `
        -RunLevel Limited `
        | Out-Null

    Write-Host ("Registered: {0,-40} every {1,3} min  BD {2:D2}:00-{3:D2}:00  --last-minutes {4}  first run {5}" -f `
        $Name, $IntervalMinutes, $StartHour, ($StartHour + $DurationHours), $LastMinutes, $anchor)
}

Register-ChatPush `
    -Name $dayTask `
    -StartHour 10 `
    -DurationHours 7 `
    -IntervalMinutes 120 `
    -LastMinutes 120 `
    -Description "Pushes the last 120 min of Teams chat into NUCLEUS_CENTRAL_PATH. Fires at BD 10:00, 12:00, 14:00, 16:00 — stops at 16:00 so the last tick doesn't collide with the Evening task's 18:00 fire."

Register-ChatPush `
    -Name $eveTask `
    -StartHour 18 `
    -DurationHours 6 `
    -IntervalMinutes 30 `
    -LastMinutes 30 `
    -Description "Pushes the last 30 min of Teams chat into NUCLEUS_CENTRAL_PATH. Runs every 30 min during BD 18:00-24:00 window — peak US-client interaction time."

Write-Host ""
Write-Host "Coverage gap: BD 00:00-10:00 has no auto-push."
Write-Host "Run push-chat.bat manually or:"
Write-Host "    py -3 -m teams.push_chat --last-minutes 600"
Write-Host ""
Write-Host "View:    Task Scheduler -> Task Scheduler Library"
Write-Host "Run now: Start-ScheduledTask -TaskName '$eveTask'"
Write-Host "Remove:  .\scripts\register-chat-push-task.ps1 -Unregister"
