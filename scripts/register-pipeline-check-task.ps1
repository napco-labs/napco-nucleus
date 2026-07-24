<#
.SYNOPSIS
Register "NAPCO Nucleus - Pipeline Check" - runs the daily 1 PM pipeline health
check + alerting agent (agent/tasks/daily-pipeline-check.md). Only alerts if the
pipeline is genuinely broken (email khasan@ael-bd.com + Teams ping to Titu).

Needs: Claude logged in on this box + the screen UNLOCKED. Idempotent.

.PARAMETER Unregister   Remove the task and exit.
#>
param([switch]$Unregister)
$ErrorActionPreference = "Stop"
$taskName = "NAPCO Nucleus - Pipeline Check"

if ($Unregister) {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "Removed: $taskName"
    } else { Write-Host "Not present: $taskName" }
    return
}

$runner = "E:\napco-nucleus\agent\agent-run.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -File `"$runner`" -Autonomous -Task daily-pipeline-check" `
    -WorkingDirectory "E:\napco-nucleus"
$trigger = New-ScheduledTaskTrigger -Daily -At "1:00PM"     # local time (Dhaka)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal | Out-Null
$state = (Get-ScheduledTask -TaskName $taskName).State
Write-Host "Registered: $taskName (daily 1:00 PM local; state=$state)"
