<#
Register "NAPCO Nucleus - Watchdog" - every 5 minutes runs nn-watchdog.ps1,
which restarts auto_reply / live_heartbeat / auto_answer / voice_daemon if their
process has died. Complements the existing Voice Watchdog. Idempotent.
.PARAMETER Unregister  Remove the task and exit.
#>
param([switch]$Unregister)
$ErrorActionPreference = "Stop"
$taskName = "NAPCO Nucleus - Watchdog"

if ($Unregister) {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "Removed: $taskName"
    } else { Write-Host "Not present: $taskName" }
    return
}

$ps1 = "E:\napco-nucleus\scripts\nn-watchdog.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ps1`""
$start = [datetime]"2026-01-01T00:00:00"
$trigger = New-ScheduledTaskTrigger -Once -At $start `
    -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 4)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal | Out-Null
Write-Host "Registered: $taskName (every 5 min; state=$((Get-ScheduledTask -TaskName $taskName).State))"
