<#
.SYNOPSIS
Register the Teams voice daemon as a Windows Scheduled Task that
autostarts on every user logon.

.DESCRIPTION
One Task Scheduler entry on the dev's machine:

  "NAPCO Nucleus - Voice Daemon"   triggers: At logon (current user)
                                   action:   wscript scripts\start-daemon-hidden.vbs
                                             -> hidden cmd -> scripts\start-daemon.bat
                                             -> python -m teams.voice_daemon
                                             (logs to logs\voice_daemon.log)
                                   restart:  5 times, 1 min apart
                                   limit:    none (long-running)
                                   single-instance: yes (new fires ignored)

The daemon listens for start/stop phrases (English wake-words plus
Bangla/Arabic call-bookends) and only fires the recorder when MS
Teams has an active audio session. No BD-time-window gate -- the
daemon runs 24x7.

The .bat is launched via a hidden-window VBS wrapper so devs don't
see a cmd console pop up at logon. stdout/stderr land in
logs\voice_daemon.log (append mode) — tail it with:
    Get-Content logs\voice_daemon.log -Wait -Tail 50

Re-running this script is idempotent -- the entry is dropped and
re-created so it doubles as the upgrade path.

.PARAMETER Unregister
Remove the task and exit.

.EXAMPLE
    .\scripts\register-voice-daemon-task.ps1
    .\scripts\register-voice-daemon-task.ps1 -Unregister
#>
param(
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"

$taskName = "NAPCO Nucleus - Voice Daemon"

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
$batPath = Join-Path $scriptDir "start-daemon.bat"
$vbsPath = Join-Path $scriptDir "start-daemon-hidden.vbs"

if (-not (Test-Path $batPath)) {
    Write-Error "Cannot find $batPath. Aborting."
    return
}
if (-not (Test-Path $vbsPath)) {
    Write-Error "Cannot find $vbsPath. Aborting."
    return
}

# Idempotent cleanup. Two paths because they catch different leftovers:
#   - Unregister-ScheduledTask (CIM): clean unregister of tasks the
#     modern API can see, but misses orphan XML files that have lost
#     their CIM index entry.
#   - schtasks /delete /f (legacy CLI): catches those orphans and is
#     what unblocks "ERROR_ALREADY_EXISTS (0x800700b7)" on the
#     subsequent Register-ScheduledTask call.
#
# Note: schtasks stderr is routed through cmd /c so PowerShell 5.1
# does NOT escalate "file not found" to a terminating NativeCommandError
# under $ErrorActionPreference = "Stop".
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

# Action runs wscript.exe against a tiny VBS that launches start-daemon.bat
# with a hidden window (no cmd flash). wscript stays alive for the daemon's
# lifetime so Task Scheduler can track + restart on failure correctly.
$action = New-ScheduledTaskAction `
    -Execute "wscript.exe" `
    -Argument ('"{0}"' -f $vbsPath) `
    -WorkingDirectory $repoRoot

# Use domain-qualified name if on a domain, plain username otherwise
$domainUser = if ($env:USERDOMAIN -and $env:USERDOMAIN -ne $env:COMPUTERNAME) {
    "$env:USERDOMAIN\$env:USERNAME"
} else {
    $env:USERNAME
}
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $domainUser

# Long-running listener: no execution time limit, restart on crash,
# never two instances at once, run even on battery.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew

try {
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description "Autostart the Teams voice daemon at logon. Listens 24x7 for start/stop phrases; the Teams-active gate inside the daemon decides whether to record." `
        -RunLevel Limited `
        -ErrorAction Stop `
        | Out-Null
} catch {
    Write-Error "FAILED to register '$taskName': $($_.Exception.Message)"
    return
}

Write-Host "Registered: $taskName"
Write-Host "  Trigger:  At logon of $domainUser"
Write-Host "  Action:   wscript.exe `"$vbsPath`""
Write-Host "             -> hidden cmd -> $batPath"
Write-Host "             -> python -u -m teams.voice_daemon"
Write-Host "             logs:   $repoRoot\logs\voice_daemon.log"
Write-Host "  WorkDir:  $repoRoot"
Write-Host ""
Write-Host "Start now (without re-logging on):"
Write-Host "    Start-ScheduledTask -TaskName '$taskName'"
Write-Host ""
Write-Host "Remove:"
Write-Host "    .\scripts\register-voice-daemon-task.ps1 -Unregister"
