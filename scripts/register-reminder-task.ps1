<#
.SYNOPSIS
Register "NAPCO Nucleus - Dev Reminder" - runs teams/remind_devs.py every 30
minutes. The script self-gates: weekdays only, 17:00-22:00 BST, max twice/day,
spaced >= 2h, skips devs who already added the assistant, and does nothing
while dev_list.json is empty. So it is safe to leave registered.

.PARAMETER Unregister  Remove the task and exit.
#>
param([switch]$Unregister)
$ErrorActionPreference = "Stop"
$taskName = "NAPCO Nucleus - Dev Reminder"

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

$action  = New-ScheduledTaskAction -Execute $pyw -Argument "-m teams.remind_devs" -WorkingDirectory $repoRoot
$start   = [datetime]"2026-01-01T00:00:00"
$trigger = New-ScheduledTaskTrigger -Once -At $start `
    -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal | Out-Null
Write-Host "Registered: $taskName (runs every 30 min, self-gated; empty dev_list = no-op)"
