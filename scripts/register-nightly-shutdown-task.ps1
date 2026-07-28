$ErrorActionPreference = "Stop"
$name = "NAPCO Nucleus - Nightly Shutdown"
$act  = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NonInteractive -ExecutionPolicy Bypass -File E:\napco-nucleus\scripts\nn-nightly-shutdown.ps1"
$trg  = New-ScheduledTaskTrigger -Daily -At 23:00
$set  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew
# SYSTEM so the shutdown happens regardless of who is logged on.
$prin = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
}
Register-ScheduledTask -TaskName $name -Action $act -Trigger $trg -Settings $set -Principal $prin | Out-Null
$t = Get-ScheduledTask -TaskName $name
Write-Output ("Registered: {0} | State={1} | Next={2}" -f $name, $t.State, ($t | Get-ScheduledTaskInfo).NextRunTime)
