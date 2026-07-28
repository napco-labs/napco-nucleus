$ErrorActionPreference = "Stop"
$name = "NAPCO Nucleus - Ensure Teams"
$act  = New-ScheduledTaskAction -Execute "powershell.exe" `
        -Argument "-NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File E:\napco-nucleus\scripts\nn-ensure-teams.ps1"

# 1) at logon, after Teams has had a chance to start (covers reboots)
$t1 = New-ScheduledTaskTrigger -AtLogOn
$t1.Delay = "PT90S"

# 2) every 5 minutes, all day (covers Teams closed by hand, or crashing)
$t2 = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddMinutes(1) `
      -RepetitionInterval (New-TimeSpan -Minutes 5) -RepetitionDuration (New-TimeSpan -Days 3650)

# 3) 11:20, just after the 11:00-11:10 wake, so the window is guaranteed for
#    the working day rather than waiting on the 5-minute cycle.
$t3 = New-ScheduledTaskTrigger -Daily -At 11:20

$set  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 3) -MultipleInstances IgnoreNew
$prin = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest
if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) { Unregister-ScheduledTask -TaskName $name -Confirm:$false }
Register-ScheduledTask -TaskName $name -Action $act -Trigger $t1,$t2,$t3 -Settings $set -Principal $prin | Out-Null

$t = Get-ScheduledTask -TaskName $name
Write-Output ("{0} | State={1} | Triggers={2} | Next={3}" -f $name, $t.State, $t.Triggers.Count, ($t | Get-ScheduledTaskInfo).NextRunTime)
