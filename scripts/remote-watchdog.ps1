<#
.SYNOPSIS
Remote health check + auto-restart for Atik and Rocky dev PCs.

.DESCRIPTION
Runs from Titu's PC (172.16.205.71) on a 30-min schedule, 19:00-22:00 BD.
For each remote PC:
  - Checks voice daemon alive (python + wscript running)
  - Checks NAPCO Nucleus Chat Push (Evening) task is not Disabled
  - Restarts daemon via Start-ScheduledTask if dead
  - Re-enables + runs Chat Push if disabled
Logs to <repo>\logs\remote-watchdog.log. Exits 0 if all healthy, 1 if any problem.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"
$secpw = ConvertTo-SecureString '606549' -AsPlainText -Force
$cred  = New-Object PSCredential('AEL\khasan', $secpw)

$logPath = Join-Path $PSScriptRoot "..\logs\remote-watchdog.log"
$logDir  = Split-Path $logPath -Parent
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

function Write-Log([string]$msg) {
    $stamp = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    "$stamp  $msg" | Out-File -FilePath $logPath -Append -Encoding utf8
    Write-Host "$stamp  $msg"
}

$devs = @(
    @{ name = "Atik";  ip = "172.16.205.108" }
    @{ name = "Rocky"; ip = "172.16.205.195" }
)

$allOk = $true

foreach ($d in $devs) {
    $name = $d.name
    $ip   = $d.ip

    # --- probe ---
    $probe = {
        $py     = Get-Process python, pythonw -ErrorAction SilentlyContinue
        $ws     = Get-Process wscript -ErrorAction SilentlyContinue
        $alive  = ($py -and $ws)
        $pid0   = if ($py) { $py[0].Id } else { 0 }

        # Use schtasks (not Get-ScheduledTask) -- works without CIM admin rights
        $rawDaemon  = (schtasks /Query /TN "NAPCO Nucleus - Voice Daemon"    /FO LIST 2>$null) -join "`n"
        $rawEvening = (schtasks /Query /TN "NAPCO Nucleus - Chat Push (Evening)" /FO LIST 2>$null) -join "`n"

        $daemonStatus  = if ($rawDaemon  -match 'Status:\s+(.+)')  { $Matches[1].Trim() } else { "NOT_FOUND" }
        $eveningStatus = if ($rawEvening -match 'Status:\s+(.+)')  { $Matches[1].Trim() } else { "NOT_FOUND" }

        [PSCustomObject]@{
            DaemonAlive    = [bool]$alive
            DaemonPid      = $pid0
            DaemonStatus   = $daemonStatus
            EveningStatus  = $eveningStatus
        }
    }

    try {
        $r = Invoke-Command -ComputerName $ip -Credential $cred `
             -Authentication Negotiate -ScriptBlock $probe -ErrorAction Stop
    } catch {
        Write-Log "[WARN] $name ($ip) UNREACHABLE: $($_.Exception.Message)"
        $allOk = $false
        continue
    }

    Write-Log "[$name] daemon=$($r.DaemonStatus) alive=$($r.DaemonAlive) pid=$($r.DaemonPid) | evening=$($r.EveningStatus)"

    # --- restart voice daemon if dead ---
    if (-not $r.DaemonAlive) {
        $allOk = $false
        Write-Log "[WARN] $name voice daemon DEAD -- restarting"
        try {
            Invoke-Command -ComputerName $ip -Credential $cred `
                -Authentication Negotiate -ErrorAction Stop -ScriptBlock {
                    Start-ScheduledTask -TaskName "NAPCO Nucleus - Voice Daemon" -ErrorAction Stop
                    Start-Sleep -Seconds 4
                    $py = Get-Process python, pythonw -ErrorAction SilentlyContinue
                    if ($py) { "restart OK pid=$($py[0].Id)" } else { "restart attempted but python not seen" }
                } | ForEach-Object { Write-Log "  ${name}: $_" }
        } catch {
            Write-Log "[ERROR] $name restart failed: $($_.Exception.Message)"
        }
    }

    # --- re-enable Evening chat-push if disabled ---
    if ($r.EveningStatus -eq "Disabled") {
        $allOk = $false
        Write-Log "[WARN] $name Chat Push (Evening) is Disabled -- re-enabling"
        try {
            Invoke-Command -ComputerName $ip -Credential $cred `
                -Authentication Negotiate -ErrorAction Stop -ScriptBlock {
                    Enable-ScheduledTask  -TaskName "NAPCO Nucleus - Chat Push (Evening)" -ErrorAction Stop
                    Start-ScheduledTask   -TaskName "NAPCO Nucleus - Chat Push (Evening)" -ErrorAction SilentlyContinue
                }
            Write-Log "  ${name}: Chat Push (Evening) re-enabled"
        } catch {
            Write-Log "[ERROR] $name Chat Push re-enable failed: $($_.Exception.Message)"
        }
    }
}

if ($allOk) {
    Write-Log "[OK] all dev PCs healthy"
    exit 0
} else {
    exit 1
}
