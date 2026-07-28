# Register the Teams auto-answer watcher as a logon Scheduled Task.
# Runs in the interactive session so it can click the Teams "Accept" button.
$ErrorActionPreference = "Stop"
$taskName = "NAPCO Nucleus - Auto Answer"
$pw = "C:\Users\assad\AppData\Local\Programs\Python\Python313\pythonw.exe"
$script = "E:\napco-nucleus\teams\auto_answer.py"

cmd /c "schtasks /delete /tn `"$taskName`" /f >nul 2>&1"

$action = New-ScheduledTaskAction -Execute $pw -Argument $script -WorkingDirectory "E:\napco-nucleus"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "ael\assad"
$principal = New-ScheduledTaskPrincipal -UserId "ael\assad" -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings `
    -Description "Auto-accept incoming Teams calls for the Meeting Assistant" -Force | Out-Null

Start-ScheduledTask -TaskName $taskName
Write-Host "Registered and started: $taskName"
