$ErrorActionPreference = "Stop"

# Old shutdown task goes away - replaced by sleep.
$old = "NAPCO Nucleus - Nightly Shutdown"
if (Get-ScheduledTask -TaskName $old -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $old -Confirm:$false
}

# Real S3 sleep, and allow timers to wake the machine.
powercfg /hibernate off 2>&1 | Out-Null
powercfg /SETACVALUEINDEX SCHEME_CURRENT SUB_SLEEP RTCWAKE 1 2>&1 | Out-Null
powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_SLEEP RTCWAKE 1 2>&1 | Out-Null

# "Require a password on wakeup" is a HIDDEN setting: without unhiding it first,
# SETACVALUEINDEX silently does nothing and the box wakes to a LOCKED screen,
# where UI automation is blind and Nucleus is dead until somebody types a
# password. Verified on .72 2026-07-28: the first attempt reported success and
# changed nothing.
powercfg /attributes SUB_NONE 0e796bdb-100d-47d6-a2d5-f7d2daa51f51 -ATTRIB_HIDE 2>&1 | Out-Null
powercfg /SETACVALUEINDEX SCHEME_CURRENT SUB_NONE 0e796bdb-100d-47d6-a2d5-f7d2daa51f51 0 2>&1 | Out-Null
powercfg /SETDCVALUEINDEX SCHEME_CURRENT SUB_NONE 0e796bdb-100d-47d6-a2d5-f7d2daa51f51 0 2>&1 | Out-Null
powercfg /SETACTIVE SCHEME_CURRENT 2>&1 | Out-Null

$sleepName = "NAPCO Nucleus - Nightly Sleep"
$act = New-ScheduledTaskAction -Execute "powershell.exe" `
       -Argument "-NonInteractive -ExecutionPolicy Bypass -File E:\napco-nucleus\scripts\nn-nightly-sleep.ps1"
# RandomDelay so it is not 22:30:00 to the second every night. A perfectly
# punctual machine is itself a bot signal.
$trg = New-ScheduledTaskTrigger -Daily -At 22:30
$trg.RandomDelay = "PT15M"
$set = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
       -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2) -MultipleInstances IgnoreNew
$prin = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
if (Get-ScheduledTask -TaskName $sleepName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $sleepName -Confirm:$false
}
Register-ScheduledTask -TaskName $sleepName -Action $act -Trigger $trg -Settings $set -Principal $prin | Out-Null

# The wake timer. The action barely matters, WakeToRun is what powers the box
# back on; the session is still logged in so every daemon is already running.
$wakeName = "NAPCO Nucleus - Morning Wake"
$wact = New-ScheduledTaskAction -Execute "cmd.exe" `
        -Argument "/c echo %DATE% %TIME% woke >> E:\napco-nucleus\logs\nightly_sleep.log"
$wtrg = New-ScheduledTaskTrigger -Daily -At 11:00
$wtrg.RandomDelay = "PT10M"
$wset = New-ScheduledTaskSettingsSet -WakeToRun -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
if (Get-ScheduledTask -TaskName $wakeName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $wakeName -Confirm:$false
}
Register-ScheduledTask -TaskName $wakeName -Action $wact -Trigger $wtrg -Settings $wset -Principal $prin | Out-Null

foreach ($n in @($sleepName, $wakeName)) {
    $t = Get-ScheduledTask -TaskName $n
    $i = $t | Get-ScheduledTaskInfo
    Write-Output ("{0} | State={1} | Next={2} | WakeToRun={3}" -f $n, $t.State, $i.NextRunTime, $t.Settings.WakeToRun)
}
