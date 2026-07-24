<#
.SYNOPSIS
Register the live-heartbeat scheduled task ("NAPCO Nucleus - Live Heartbeat").

Runs teams/live_heartbeat.py at logon of the daemon account. While a call is
recording it pushes a status beacon to central .../<dev>/<date>/live/<stamp>.json
every few seconds so the capture can be watched live. Auto-restarts on crash.
Idempotent: re-running drops + recreates the task, then starts it now.

.PARAMETER Unregister
Remove the task and exit.
#>
param([switch]$Unregister)
$ErrorActionPreference = "Stop"
$taskName = "NAPCO Nucleus - Live Heartbeat"

if ($Unregister) {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "Removed: $taskName"
    } else { Write-Host "Not present: $taskName" }
    return
}

$repoRoot = "E:\napco-nucleus"
$pyw = "C:\Users\assad\AppData\Local\Programs\Python\Python313\pythonw.exe"
if (-not (Test-Path $pyw)) { $pyw = (Get-Command pythonw.exe -ErrorAction Stop).Source }

$action = New-ScheduledTaskAction -Execute $pyw -Argument "-m teams.live_heartbeat" -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -RestartInterval (New-TimeSpan -Minutes 1) -RestartCount 999 `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal | Out-Null
Start-ScheduledTask -TaskName $taskName
Start-Sleep 2
$state = (Get-ScheduledTask -TaskName $taskName).State
Write-Host "Registered + started: $taskName (state=$state)"
