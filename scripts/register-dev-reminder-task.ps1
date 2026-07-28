$ErrorActionPreference = "Stop"
$name = "NAPCO Nucleus - Dev Reminder"
$act = New-ScheduledTaskAction `
       -Execute "C:\Users\assad\AppData\Local\Programs\Python\Launcher\py.exe" `
       -Argument "-3 -m teams.remind_devs" -WorkingDirectory "E:\napco-nucleus"

# WEEKLY Mon-Fri, so the trigger renews itself every day.
#
# The original was a one-shot starting 2026-07-27 17:00 with a 5-minute
# repetition and a limited duration. It ran that one evening, the duration
# expired, NextRunTime went blank, and the reminder never fired again. Nobody
# noticed for a day because a task in that state still reports State=Ready.
#
# 16:00-17:00 BD, checked every 5 minutes. remind_devs reminds exactly ONE
# colleague per run and enforces the spacing itself, so the repetition here is
# just "look again", not "send again".
$trg = New-ScheduledTaskTrigger -Weekly -At 16:00 `
       -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday
$trg.Repetition = (New-ScheduledTaskTrigger -Once -At (Get-Date) `
       -RepetitionInterval (New-TimeSpan -Minutes 5) `
       -RepetitionDuration (New-TimeSpan -Minutes 60)).Repetition

$set  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 4) -MultipleInstances IgnoreNew
$prin = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Highest

if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
}
Register-ScheduledTask -TaskName $name -Action $act -Trigger $trg -Settings $set -Principal $prin | Out-Null

$t = Get-ScheduledTask -TaskName $name
Write-Output ("NextRun={0} | every {1} for {2} | days={3}" -f `
    ($t | Get-ScheduledTaskInfo).NextRunTime, `
    $t.Triggers[0].Repetition.Interval, `
    $t.Triggers[0].Repetition.Duration, `
    $t.Triggers[0].DaysOfWeek)
