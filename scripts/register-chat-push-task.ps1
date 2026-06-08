<#
.SYNOPSIS
Register the Teams chat-push as ONE Windows Scheduled Task that fires
every 20 minutes across the BD working day.

.DESCRIPTION
One Task Scheduler entry on each dev machine:

  "NAPCO Nucleus - Chat Push"   every 20 min, BD 04:00 -> 22:50
                                 window = last 30 min per push
                                 (20-min cadence + 10-min overlap so a
                                  single missed/late tick self-heals)

Rationale (set 2026-06-08 by Titu):
  - Flat 20-minute cadence all working day — simpler + fresher than the
    old 2h-day / 30m-evening / 17:30-transition split.
  - Window 04:00 -> 22:50: last push lands ~22:40, just before the
    23:00 (11 PM) daily Requirement Management run picks up the day.
  - The 30-min lookback (vs the 20-min cadence) overlaps consecutive
    pushes so a skipped or late tick can't drop a 20-min slice of chat.

Note on the grid: repetitions sit on the 20-min grid anchored at 04:00
(04:00, 04:20, ... 22:40). 22:50 is the repetition-duration cut-off, so
the final effective push is 22:40 — 20 min before the 23:00 daily run,
which itself reads the whole day (--last-minutes 1440) from central.

Coverage gap (by design): BD 22:50 -> 04:00 is NOT auto-pushed. If
overnight chat must land before the next 04:00 tick, run manually:
    py -3 -m teams.push_chat --last-minutes 600

Both the task and the daily run use the dev's local clock — dev machines
are on BD time.

push-chat.bat (--last-minutes 15) remains the ad-hoc "push my chat now"
entry point and is untouched by this script.

Re-running this script is idempotent — the entry (and any older
Day/Evening/Transition entries) are dropped and re-created, so it
doubles as the upgrade path.

.PARAMETER Unregister
Remove the task (and legacy entries) and exit.

.EXAMPLE
    .\scripts\register-chat-push-task.ps1
    .\scripts\register-chat-push-task.ps1 -Unregister
#>
param(
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"

$chatTask = "NAPCO Nucleus - Chat Push"
# Older split-window entries this script supersedes. Listed so a
# re-run cleanly removes them (upgrade path from the pre-2026-06-08
# Day/Evening/Transition schedule and the original single-window one).
$legacyTasks = @(
    "NAPCO Nucleus - Chat Push (Day)",
    "NAPCO Nucleus - Chat Push (Evening)",
    "NAPCO Nucleus - Chat Push (Transition)",
    "NAPCO Nucleus - Chat Push (Backfill)"
)

# Chat-push cadence + window (BD local).
$startHour = 4          # 04:00
$startMinute = 0
$intervalMinutes = 20   # every 20 min
$lastMinutes = 30       # 30-min lookback (20-min cadence + 10-min overlap)
# Window length 04:00 -> 22:50 = 18 h 50 m.
$windowHours = 18
$windowMinutes = 50

if ($Unregister) {
    foreach ($name in @($chatTask) + $legacyTasks) {
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
$vbsPath = Join-Path $scriptDir "push-chat-hidden.vbs"

if (-not (Test-Path $vbsPath)) {
    Write-Error "Cannot find $vbsPath. Aborting."
    return
}

# Drop the current entry plus all legacy split-window entries so this
# script is idempotent and doubles as the upgrade path.
#
# Two cleanup paths because they catch different kinds of leftovers:
#   - Unregister-ScheduledTask (CIM): clean unregister of tasks the
#     modern API can see, but misses orphan XML files that have lost
#     their CIM index entry.
#   - schtasks /delete /f (legacy CLI): catches those orphans and is
#     what unblocks "ERROR_ALREADY_EXISTS (0x800700b7)" on the
#     subsequent Register-ScheduledTask call.
#
# schtasks is wrapped in cmd /c so PowerShell 5.1 doesn't escalate
# its "file not found" stderr to a NativeCommandError that aborts
# the script under $ErrorActionPreference = "Stop".
function Invoke-SchtasksDelete {
    param([string]$Name)
    cmd /c "schtasks /delete /tn `"$Name`" /f >nul 2>&1"
}

foreach ($name in @($chatTask) + $legacyTasks) {
    if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
        try {
            Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction Stop
        } catch {
            Write-Warning "Unregister-ScheduledTask failed for '$name': $($_.Exception.Message). Falling back to schtasks /delete."
            Invoke-SchtasksDelete -Name $name
        }
    } else {
        Invoke-SchtasksDelete -Name $name
    }
}

# Anchor to today's 04:00 BD-local. If the whole window has already
# closed for today (now is past 22:50), anchor tomorrow.
$anchor = (Get-Date).Date.AddHours($startHour).AddMinutes($startMinute)
$windowClose = $anchor.AddHours($windowHours).AddMinutes($windowMinutes)
if ((Get-Date) -gt $windowClose) {
    $anchor = $anchor.AddDays(1)
}

# Hidden launcher: wscript.exe runs push-chat-hidden.vbs which spawns
# `python -m teams.push_chat --last-minutes <N>` with a hidden window
# and tees output to logs\chat_push.log.
$action = New-ScheduledTaskAction `
    -Execute "wscript.exe" `
    -Argument ('"{0}" --last-minutes {1}' -f $vbsPath, $lastMinutes) `
    -WorkingDirectory $repoRoot

# Daily trigger carrying a sub-day repetition: fire at $anchor, then
# every $intervalMinutes for the $windowHours/$windowMinutes duration.
$dailyTrigger = New-ScheduledTaskTrigger -Daily -At $anchor
$dailyTrigger.Repetition = (New-ScheduledTaskTrigger `
    -Once -At $anchor `
    -RepetitionInterval (New-TimeSpan -Minutes $intervalMinutes) `
    -RepetitionDuration (New-TimeSpan -Hours $windowHours -Minutes $windowMinutes)).Repetition

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

# Inline belt-and-suspenders cleanup right before Register, in case the
# parens-in-name + cmd /c quoting let an orphan survive the loop above.
Invoke-SchtasksDelete -Name $chatTask

try {
    Register-ScheduledTask `
        -TaskName $chatTask `
        -Action $action `
        -Trigger $dailyTrigger `
        -Settings $settings `
        -Description "Pushes the last $lastMinutes min of Teams chat into NUCLEUS_CENTRAL_PATH every $intervalMinutes min, BD 04:00-22:50. Last push ~22:40, just before the 23:00 daily Requirement Management run." `
        -RunLevel Limited `
        -ErrorAction Stop `
        | Out-Null
} catch {
    Write-Error "FAILED to register '$chatTask': $($_.Exception.Message)"
    exit 1
}

Write-Host ("Registered: {0}" -f $chatTask)
Write-Host ("    Fires:   every {0} min, BD 04:00 -> 22:50 (last ~22:40)" -f $intervalMinutes)
Write-Host ("    Window:  --last-minutes {0} (20-min cadence + 10-min overlap)" -f $lastMinutes)
Write-Host ("    First:   $anchor")
Write-Host ""
Write-Host "Overnight (22:50-04:00) is not auto-pushed by design. Catch-up if needed:"
Write-Host "    py -3 -m teams.push_chat --last-minutes 600"
Write-Host ""
Write-Host "View:    Task Scheduler -> Task Scheduler Library"
Write-Host "Run now: Start-ScheduledTask -TaskName '$chatTask'"
Write-Host "Remove:  .\scripts\register-chat-push-task.ps1 -Unregister"
