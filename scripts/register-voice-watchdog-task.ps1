<#
.SYNOPSIS
Register the voice-watchdog scheduled task.

.DESCRIPTION
  Task name : "NAPCO Nucleus - Voice Watchdog"
  Trigger   : every 5 minutes, starting 5 minutes after registration
  Action    : powershell.exe -File scripts\voice-watchdog.ps1
              (which restarts the voice daemon if it has died)
  RunLevel  : Limited

The watchdog complements:
  - NAPCO Nucleus - Voice Daemon       (at-logon, starts the daemon)
  - NAPCO Nucleus - Self-Heal at Logon (at-logon, re-registers tasks)
  - NAPCO Nucleus - Voice Watchdog     (THIS: every 5 min, restarts dead daemon)

So a daemon crash now gets caught within 5 minutes instead of waiting
for the next logon. The watchdog also no-ops if the voice-daemon task
isn't registered yet, so it's safe to install on partially-onboarded
machines.

Idempotent. Re-running drops + re-creates the task.

.PARAMETER Unregister
Remove the task and exit.
#>
param(
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"
$taskName = "NAPCO Nucleus - Voice Watchdog"

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
$ps1Path = Join-Path $scriptDir "voice-watchdog.ps1"

if (-not (Test-Path $ps1Path)) {
    Write-Error "Cannot find $ps1Path. Aborting."
    return
}

function Invoke-SchtasksDelete {
    param([string]$Name)
    cmd /c "schtasks /delete /tn `"$Name`" /f >nul 2>&1"
}

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    try {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop
    } catch {
        Write-Warning "Unregister-ScheduledTask failed for '$taskName': $($_.Exception.Message). Falling back to schtasks /delete."
        Invoke-SchtasksDelete -Name $taskName
    }
} else {
    Invoke-SchtasksDelete -Name $taskName
}

$vbsPath = Join-Path $scriptDir "watchdog-hidden.vbs"
$action = New-ScheduledTaskAction `
    -Execute "wscript.exe" `
    -Argument ('"' + $vbsPath + '"') `
    -WorkingDirectory $repoRoot

$domainUser = if ($env:USERDOMAIN -and $env:USERDOMAIN -ne $env:COMPUTERNAME) {
    "$env:USERDOMAIN\$env:USERNAME"
} else {
    $env:USERNAME
}

# Trigger: starts in $intervalMin min, repeats every $intervalMin min
# forever. NUCLEUS_WATCHDOG_INTERVAL_MIN env var overrides; default 5.
# Edit .env + re-run fix-nucleus.bat to change after registration.
$intervalMin = 5
if ($env:NUCLEUS_WATCHDOG_INTERVAL_MIN) {
    $parsed = 0
    if ([int]::TryParse($env:NUCLEUS_WATCHDOG_INTERVAL_MIN, [ref]$parsed) -and $parsed -ge 1) {
        $intervalMin = $parsed
    }
}
$start = (Get-Date).AddMinutes($intervalMin)
$trigger = New-ScheduledTaskTrigger -Once -At $start `
    -RepetitionInterval (New-TimeSpan -Minutes $intervalMin) `
    -RepetitionDuration ([TimeSpan]::FromDays(365 * 5))

# Short-running probe. 2-min ceiling stops a stuck Start-ScheduledTask
# call from pinning the watchdog forever.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2) `
    -MultipleInstances IgnoreNew

try {
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description "Every 5 min, check whether the voice daemon process is alive; restart via Start-ScheduledTask if it has died. Logs to logs\voice-watchdog.log." `
        -RunLevel Limited `
        -ErrorAction Stop `
        | Out-Null
} catch {
    Write-Error "FAILED to register '$taskName': $($_.Exception.Message)"
    return
}

Write-Host "Registered: $taskName"
Write-Host "  Trigger:  every $intervalMin min, starting $($start.ToString('HH:mm'))"
Write-Host "  Action:   powershell -File $ps1Path"
Write-Host "  Logs:     $repoRoot\logs\voice-watchdog.log"
