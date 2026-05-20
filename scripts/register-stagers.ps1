<#
.SYNOPSIS
Register the email + Drive staging Tasks on MVPACCESS.

.DESCRIPTION
Two Windows Task Scheduler entries, each runs every 15 min:

  "NAPCO Nucleus - Stage Email"   py -3 -m tools.stage_email
  "NAPCO Nucleus - Stage Drive"   py -3 -m tools.stage_drive

These are CAPTURE tasks (move email + Drive content to central), not
identify. Background, automatic, no operator intervention — matches
the chat-push cron model. The requirement-management workflow itself
stays manual.

Run on MVPACCESS:

    .\scripts\register-stagers.ps1
    .\scripts\register-stagers.ps1 -IntervalMinutes 30
    .\scripts\register-stagers.ps1 -Unregister   # remove both

Re-running this script is idempotent — existing entries are dropped
and re-created so it doubles as the upgrade path.
#>
param(
    [int]$IntervalMinutes = 15,
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"

$tasks = @(
    @{ Name = "NAPCO Nucleus - Stage Email"; Module = "tools.stage_email" },
    @{ Name = "NAPCO Nucleus - Stage Drive"; Module = "tools.stage_drive" }
)

if ($Unregister) {
    foreach ($t in $tasks) {
        if (Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $t.Name -Confirm:$false
            Write-Host "Removed: $($t.Name)"
        } else {
            Write-Host "Not present: $($t.Name)"
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
} else {
    $pyExe = "py"
}

# Stagger the two tasks by 5 minutes so they don't compete for IMAP
# bandwidth / Drive API quota at the same second.
$now = Get-Date
$base = $now.AddMinutes(15 - ($now.Minute % 15)).Date.AddHours($now.Hour).AddMinutes(15 * [int](($now.Minute) / 15) + 15)
if ($base -lt $now.AddSeconds(30)) { $base = $base.AddMinutes(15) }

$offsets = 0, 5

for ($i = 0; $i -lt $tasks.Count; $i++) {
    $t = $tasks[$i]
    $offset = $offsets[$i]
    $start = $base.AddMinutes($offset)

    if (Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $t.Name -Confirm:$false
    }

    $argString = if ($pyExe -eq "py") {
        "-3 -m $($t.Module)"
    } else {
        "-m $($t.Module)"
    }
    $action = New-ScheduledTaskAction `
        -Execute $pyExe `
        -Argument $argString `
        -WorkingDirectory $repoRoot

    $trigger = New-ScheduledTaskTrigger -Once -At $start `
        -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
        -RepetitionDuration ([TimeSpan]::FromDays(365 * 5))

    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 10)

    Register-ScheduledTask `
        -TaskName $t.Name `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description "Stage $($t.Module) output to NUCLEUS_CENTRAL_PATH every $IntervalMinutes min." `
        -RunLevel Limited `
        -ErrorAction Stop `
        | Out-Null

    Write-Host "Registered: $($t.Name)  every $IntervalMinutes min  first run $start"
}

Write-Host ""
Write-Host "View:    Task Scheduler -> Task Scheduler Library"
Write-Host "Run now: Start-ScheduledTask -TaskName '<task name>'"
Write-Host "Remove:  .\scripts\register-stagers.ps1 -Unregister"
