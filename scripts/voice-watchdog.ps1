<#
.SYNOPSIS
Restart the NAPCO Nucleus voice daemon if it's dead.

.DESCRIPTION
Fires every 5 minutes via the "NAPCO Nucleus - Voice Watchdog"
scheduled task. The watchdog catches the gap between "daemon died
randomly mid-day" and "user next logs in" -- without this, a crashed
daemon stays crashed for hours.

Logic:
  - If the "NAPCO Nucleus - Voice Daemon" scheduled task isn't even
    registered, do nothing (this PC isn't onboarded yet).
  - Else check: is python+wscript running?
      yes  -> log "alive" once an hour, exit
      no   -> Start-ScheduledTask 'NAPCO Nucleus - Voice Daemon',
              log the restart, exit

Idempotent + cheap. Logs to <repo>\logs\voice-watchdog.log so a
post-mortem can see the timeline of any restarts.

Runs under the dev's own user (RunLevel Limited from the registration
script), so it has the right ACL to start a task owned by them.

.PARAMETER WhatIf
Print what it would do without actually restarting.
#>
[CmdletBinding()]
param(
    [switch]$WhatIfMode
)

# Locate the repo. Same priority order the bat uses.
$repoCandidates = @(
    $env:NN,
    "E:\Projects\NAPCO-Nucleus",
    "F:\Titu vai\napco-nucleus",
    "D:\POC Projects\napco-nucleus",
    "C:\napco-nucleus",
    "D:\napco-nucleus",
    "E:\napco-nucleus",
    "F:\napco-nucleus"
) | Where-Object { $_ -and (Test-Path "$_\.git") }
$repo = $repoCandidates | Select-Object -First 1

if (-not $repo) {
    # Can't locate the repo -- the watchdog has nowhere to log to. Best
    # we can do is exit quietly so the scheduled task doesn't keep
    # firing visible errors. The self-heal at logon will repair this.
    exit 0
}

$logDir = Join-Path $repo "logs"
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}
$logPath = Join-Path $logDir "voice-watchdog.log"

function Write-WatchdogLog([string]$msg) {
    $stamp = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    "$stamp  $msg" | Out-File -FilePath $logPath -Append -Encoding utf8
}

$task = Get-ScheduledTask -TaskName "NAPCO Nucleus - Voice Daemon" -ErrorAction SilentlyContinue
if (-not $task) {
    # Not onboarded yet -- the bat hasn't been run successfully on this
    # PC. Exit quietly; the self-heal task at logon will register the
    # voice-daemon task, after which the watchdog has something to do.
    exit 0
}

$python = Get-Process python, pythonw -ErrorAction SilentlyContinue
$wscript = Get-Process wscript -ErrorAction SilentlyContinue
$daemonAlive = ($python -and $wscript)

if ($daemonAlive) {
    # Only log "alive" once an hour to avoid filling the log -- check
    # whether the most recent log line is from this hour.
    $lastLog = if (Test-Path $logPath) {
        Get-Content $logPath -Tail 1 -ErrorAction SilentlyContinue
    } else { "" }
    $hourTag = (Get-Date -Format "yyyy-MM-dd HH")
    if ($lastLog -notmatch "^$hourTag") {
        Write-WatchdogLog "alive: python pid=$($python[0].Id) wscript pid=$($wscript[0].Id)"
    }
    exit 0
}

# Daemon is dead. Restart.
if ($WhatIfMode) {
    Write-WatchdogLog "WHATIF: daemon dead, would Start-ScheduledTask"
    Write-Output "WHATIF: would restart"
    exit 0
}

Write-WatchdogLog "daemon DEAD -- restarting via Start-ScheduledTask"
try {
    Start-ScheduledTask -TaskName "NAPCO Nucleus - Voice Daemon" -ErrorAction Stop
    Start-Sleep -Seconds 3
    $newPy = Get-Process python, pythonw -ErrorAction SilentlyContinue
    if ($newPy) {
        Write-WatchdogLog "restart OK: python pid=$($newPy[0].Id)"
    } else {
        Write-WatchdogLog "restart attempted but python did NOT appear within 3s"
    }
} catch {
    Write-WatchdogLog "restart FAILED: $($_.Exception.Message)"
}
