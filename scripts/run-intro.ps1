# One-shot: register + start the intro broadcast in the INTERACTIVE session
# (so UI automation can reach Teams). Runs teams/intro_broadcast.py once.
$taskName = "NAPCO Nucleus - Intro"
$pyw = "C:\Users\assad\AppData\Local\Programs\Python\Python313\pythonw.exe"
if (-not (Test-Path $pyw)) { $pyw = (Get-Command pythonw.exe -ErrorAction Stop).Source }
$action = New-ScheduledTaskAction -Execute $pyw -Argument "-m teams.intro_broadcast" -WorkingDirectory "E:\napco-nucleus"
$trigger = New-ScheduledTaskTrigger -Once -At ([datetime]"2026-01-01T00:00:00")   # past, won't auto-refire
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { Unregister-ScheduledTask -TaskName $taskName -Confirm:$false }
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal | Out-Null
Start-ScheduledTask -TaskName $taskName
Write-Host "Intro broadcast started in interactive session"
