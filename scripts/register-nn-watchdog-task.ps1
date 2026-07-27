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
# RunLevel MUST be Highest. The daemons this watchdog guards are registered
# -RunLevel Highest, and a non-elevated process cannot read
# Win32_Process.CommandLine of an elevated one. At Limited the liveness test in
# nn-watchdog.ps1 saw an empty command line for every daemon and logged
# "process was dead" every 5 minutes while they were all running fine (.203,
# 2026-07-27). Start-ScheduledTask on a Running task is a no-op so nothing
# actually restarted, which made the log worse than useless: it could never
# tell a real death from a permissions blind spot.
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal | Out-Null
Write-Host "Registered: $taskName (every 5 min; state=$((Get-ScheduledTask -TaskName $taskName).State))"
