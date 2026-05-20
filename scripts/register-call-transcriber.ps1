<#
.SYNOPSIS
Register the auto-transcribe-on-arrival task on MVPACCESS.

.DESCRIPTION
One Windows Task Scheduler entry, runs every 2 min, 24x7:

  "NAPCO Nucleus - Transcribe Calls"   py -3 -m tools.transcribe_calls

Walks <NUCLEUS_CENTRAL_PATH>\<dev>\<date>\calls\ for completed call
sessions (signal: <session>.json present, <session>_transcript.md
missing) and transcribes them in place via faster-whisper large-v3.
Cross-process locked, so overlapping cron ticks are safe.

Run on MVPACCESS (the agent host):

    .\scripts\register-call-transcriber.ps1
    .\scripts\register-call-transcriber.ps1 -IntervalMinutes 5
    .\scripts\register-call-transcriber.ps1 -Unregister

Re-running this script is idempotent — the existing entry is dropped
and re-created so it doubles as the upgrade path.
#>
param(
    [int]$IntervalMinutes = 2,
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"

$taskName = "NAPCO Nucleus - Transcribe Calls"
$module = "tools.transcribe_calls"

if ($Unregister) {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "Removed: $taskName"
    } else {
        Write-Host "Not present: $taskName"
    }
    return
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir

# Resolve a usable python — venv preferred, system py as fallback.
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    $pyExe = $venvPython
} else {
    $pyExe = "py"
}

# Start at the next minute boundary so the first tick fires within a minute.
$now = Get-Date
$start = $now.Date.AddHours($now.Hour).AddMinutes($now.Minute + 1)

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

$argString = if ($pyExe -eq "py") {
    "-3 -m $module"
} else {
    "-m $module"
}

$action = New-ScheduledTaskAction `
    -Execute $pyExe `
    -Argument $argString `
    -WorkingDirectory $repoRoot

$trigger = New-ScheduledTaskTrigger -Once -At $start `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration ([TimeSpan]::FromDays(365 * 5))

# ExecutionTimeLimit is generous — a long backlog of long calls can
# legitimately keep one tick busy for an hour. The non-blocking
# file_lock in transcribe_calls prevents the next tick from piling on.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Auto-transcribe new calls landing on NUCLEUS_CENTRAL_PATH. Runs every $IntervalMinutes min, 24x7. Skips this tick if another instance is already running." `
    -RunLevel Limited `
    -ErrorAction Stop `
    | Out-Null

Write-Host "Registered: $taskName  every $IntervalMinutes min  first run $start"
Write-Host ""
Write-Host "View:    Task Scheduler -> Task Scheduler Library"
Write-Host "Run now: Start-ScheduledTask -TaskName '$taskName'"
Write-Host "Remove:  .\scripts\register-call-transcriber.ps1 -Unregister"
