<#
.SYNOPSIS
Quick health probe across all NAPCO Nucleus dev PCs.

.DESCRIPTION
Run from Titu's dev PC just before a boss-facing email is expected
(e.g., 22:25 BD before the 22:30 daily roll-up fires). Probes each
dev PC over WinRM as AEL\khasan and reports per-PC:

  - voice daemon process alive (python + wscript present)
  - registered NAPCO Nucleus scheduled tasks count (expect 5-6)
  - last upload to central today (chat docx and/or call session)

Output is one line per PC plus a final colour-coded summary so you
can glance and either relax or trigger restarts. Exits 0 if all
machines are healthy, 1 otherwise.

.EXAMPLE
    .\scripts\team-health.ps1

.NOTES
Hardcoded host list is Titu/Atik/Rocky. Update $devs to add machines
as the team grows.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Continue"
$secpw = ConvertTo-SecureString '606549' -AsPlainText -Force
$cred = New-Object PSCredential('AEL\khasan', $secpw)

$today = (Get-Date -Format "yyyy-MM-dd")
$centralRoot = "\\172.16.205.123\nucleus-central"

$devs = @(
    @{ name = "Titu";  ip = "127.0.0.1"; remote = $false }
    @{ name = "Atik";  ip = "172.16.205.108"; remote = $true }
    @{ name = "Rocky"; ip = "172.16.205.195"; remote = $true }
)

$allHealthy = $true

foreach ($d in $devs) {
    $name = $d.name
    $ip = $d.ip

    $sb = {
        $py = Get-Process python, pythonw -ErrorAction SilentlyContinue
        $ws = Get-Process wscript -ErrorAction SilentlyContinue
        $alive = ($py -and $ws)
        $tasks = (schtasks /Query /FO CSV 2>$null | ConvertFrom-Csv |
                  Where-Object { $_.TaskName -match 'Nucleus|NAPCO|Chat|Self-Heal|Watchdog' }).Count
        [PSCustomObject]@{
            DaemonAlive = [bool]$alive
            DaemonPid = if ($py) { $py[0].Id } else { 0 }
            NNTaskCount = $tasks
        }
    }

    try {
        if ($d.remote) {
            $r = Invoke-Command -ComputerName $ip -Credential $cred `
                -Authentication Negotiate -ScriptBlock $sb -ErrorAction Stop
        } else {
            $r = & $sb
        }
    } catch {
        Write-Host ("{0,-7} {1,-16}  UNREACHABLE: {2}" -f $name, $ip, $_.Exception.Message) -ForegroundColor Red
        $allHealthy = $false
        continue
    }

    # Central uploads today (probe the share directly)
    $chatPath = Join-Path $centralRoot "$name\$today\chat"
    $callPath = Join-Path $centralRoot "$name\$today\calls"
    $chatCount = if (Test-Path $chatPath) {
        (Get-ChildItem $chatPath -Filter "chat_*.docx" -ErrorAction SilentlyContinue).Count
    } else { 0 }
    $callCount = if (Test-Path $callPath) {
        (Get-ChildItem $callPath -Filter "*.json" -ErrorAction SilentlyContinue).Count
    } else { 0 }

    $daemonStr = if ($r.DaemonAlive) { "alive(pid=$($r.DaemonPid))" } else { "DEAD" }
    $taskStr = "$($r.NNTaskCount) NN tasks"
    $centralStr = "$chatCount chat / $callCount calls today"

    $status = if ($r.DaemonAlive -and $r.NNTaskCount -ge 5) { "OK   " } else { "WARN " }
    $colour = if ($status -eq "OK   ") { "Green" } else { "Yellow" }
    if (-not $r.DaemonAlive) { $allHealthy = $false }

    Write-Host ("{0} {1,-7} {2,-16}  voice {3,-22}  {4,-12}  {5}" -f `
        $status, $name, $ip, $daemonStr, $taskStr, $centralStr) -ForegroundColor $colour
}

Write-Host ""
if ($allHealthy) {
    Write-Host "All voice daemons alive. Pipeline ready." -ForegroundColor Green
    exit 0
} else {
    Write-Host "At least one daemon is DOWN -- restart before the next email fires." -ForegroundColor Yellow
    exit 1
}
