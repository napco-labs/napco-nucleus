<#
.SYNOPSIS
Register the auto-reply scheduled task ("NAPCO Nucleus - Auto Reply").

Runs teams/auto_reply.py at logon of the daemon account, INTERACTIVE (it must
drive the Teams UI to type replies). Reads canned Q&A from
teams/auto_reply_rules.json. Registered STOPPED by default -- start it only
when you are ready to test/tune, so it never sends a reply unattended.

Idempotent. Re-running drops + recreates the task (still stopped).

.PARAMETER Start       Also start the task now.
.PARAMETER Unregister  Remove the task and exit.
#>
param([switch]$Start, [switch]$Unregister)
$ErrorActionPreference = "Stop"
$taskName = "NAPCO Nucleus - Auto Reply"

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

$action = New-ScheduledTaskAction -Execute $pyw -Argument "-m teams.auto_reply" -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -RestartInterval (New-TimeSpan -Minutes 1) -RestartCount 999 `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal | Out-Null

if ($Start) { Start-ScheduledTask -TaskName $taskName; Start-Sleep 2 }
$state = (Get-ScheduledTask -TaskName $taskName).State
Write-Host "Registered: $taskName (state=$state)"
