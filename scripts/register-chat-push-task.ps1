<#
.SYNOPSIS
Register the Teams chat-push as two Windows Scheduled Tasks split by
BD time-of-day, matching the daily rhythm of US-client interaction.

.DESCRIPTION
Two Task Scheduler entries on each dev machine:

  "NAPCO Nucleus - Chat Push (Day)"         every  2 hr,  BD 10:00 -> 17:00
                                             fires at 10:00, 12:00, 14:00, 16:00
                                             window = last 120 min

  "NAPCO Nucleus - Chat Push (Transition)"  once daily,   BD 17:30
                                             window = last  90 min
                                             (closes the 16:00-17:30 BD gap
                                             between Day and Evening)

  "NAPCO Nucleus - Chat Push (Evening)"     every 30 min, BD 18:00 -> 24:00
                                             window = last  30 min

Day stops at 16:00 (not 18:00) so its last fire doesn't collide with
Evening's first fire at 18:00. The Transition task bridges the gap.
Net coverage: continuous from BD 08:00 -> 24:00.

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
$transTask = "NAPCO Nucleus - Chat Push (Transition)"
$eveTask = "NAPCO Nucleus - Chat Push (Evening)"
$legacyTasks = @(
    "NAPCO Nucleus - Chat Push",
    "NAPCO Nucleus - Chat Push (Backfill)"
)

if ($Unregister) {
    foreach ($name in @($dayTask, $transTask, $eveTask) + $legacyTasks) {
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
#
# Two cleanup paths because they catch different kinds of leftovers:
#   - Unregister-ScheduledTask (CIM): clean unregister of tasks the
#     modern API can see, but misses orphan XML files that have lost
#     their CIM index entry.
#   - schtasks /delete /f (legacy CLI): catches those orphans and is
#     what unblocks "ERROR_ALREADY_EXISTS (0x800700b7)" on the
#     subsequent Register-ScheduledTask call.
foreach ($name in @($dayTask, $transTask, $eveTask) + $legacyTasks) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
        try {
            Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction Stop
        } catch {
            Write-Warning "Unregister-ScheduledTask failed for '$name': $($_.Exception.Message). Falling back to schtasks /delete."
            schtasks /delete /tn "$name" /f 2>$null | Out-Null
        }
    } else {
        # CIM doesn't see one with this name, but an orphan may still be
        # on disk. schtasks /delete will quietly succeed if the orphan
        # exists, quietly fail if it doesn't — either way we're clean.
        schtasks /delete /tn "$name" /f 2>$null | Out-Null
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

    try {
        Register-ScheduledTask `
            -TaskName $Name `
            -Action $action `
            -Trigger $dailyTrigger `
            -Settings $settings `
            -Description $Description `
            -RunLevel Limited `
            -ErrorAction Stop `
            | Out-Null
    } catch {
        Write-Error "FAILED to register '$Name': $($_.Exception.Message)"
        return
    }

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

# Transition: one fire daily at 17:30 BD to bridge the 16:00-17:30 gap.
$transAnchor = (Get-Date).Date.AddHours(17).AddMinutes(30)
if ((Get-Date) -gt $transAnchor) {
    $transAnchor = $transAnchor.AddDays(1)
}

$transArgString = $pyArgPrefix + "-m teams.push_chat --last-minutes 90"
$transAction = New-ScheduledTaskAction `
    -Execute $pyExe `
    -Argument $transArgString `
    -WorkingDirectory $repoRoot

$transTrigger = New-ScheduledTaskTrigger -Daily -At $transAnchor

$transSettings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

try {
    Register-ScheduledTask `
        -TaskName $transTask `
        -Action $transAction `
        -Trigger $transTrigger `
        -Settings $transSettings `
        -Description "Bridges the 16:00-17:30 BD gap between the Day and Evening chat-push windows. Fires once daily at 17:30 with --last-minutes 90." `
        -RunLevel Limited `
        -ErrorAction Stop `
        | Out-Null
    Write-Host ("Registered: {0,-44} once daily    BD 17:30        --last-minutes 90  first run {1}" -f $transTask, $transAnchor)
} catch {
    Write-Error "FAILED to register '$transTask': $($_.Exception.Message)"
}

Write-Host ""
Write-Host "Coverage: continuous BD 08:00-24:00. Only gap is BD 00:00-10:00."
Write-Host "Overnight catch-up if needed:"
Write-Host "    py -3 -m teams.push_chat --last-minutes 600"
Write-Host ""
Write-Host "View:    Task Scheduler -> Task Scheduler Library"
Write-Host "Run now: Start-ScheduledTask -TaskName '$eveTask'"
Write-Host "Remove:  .\scripts\register-chat-push-task.ps1 -Unregister"
