<#
.SYNOPSIS
Register the fix-nucleus self-heal as a Windows Scheduled Task that fires
at every user logon.

.DESCRIPTION
  Task name : "NAPCO Nucleus - Self-Heal at Logon"
  Trigger   : At logon (current user), 60s delay so the voice-daemon
              task fires first and the network is settled.
  Action    : wscript scripts\fix-nucleus-hidden.vbs
              -> cmd /c scripts\fix-nucleus.bat --quiet
              -> logs\fix-nucleus.log
  RunLevel  : Limited (no admin needed -- runs in the user's own context)

The task complements the existing voice-daemon + chat-push tasks. If
either of those is missing or has drifted, fix-nucleus.bat --quiet
re-registers them. So once this single self-heal task is in place,
every other piece of the local pipeline is auto-repaired on every login.

Idempotent -- the task is dropped and re-created so this script doubles
as the upgrade path.

.PARAMETER Unregister
Remove the task and exit.

.EXAMPLE
    .\scripts\register-self-heal-task.ps1
    .\scripts\register-self-heal-task.ps1 -Unregister
#>
param(
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"
$taskName = "NAPCO Nucleus - Self-Heal at Logon"

if ($Unregister) {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "Removed: $taskName"
    } else {
        Write-Host "Not present: $taskName"
    }
    return
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$vbsPath = Join-Path $scriptDir "fix-nucleus-hidden.vbs"

if (-not (Test-Path $vbsPath)) {
    Write-Error "Cannot find $vbsPath. Aborting."
    return
}

function Invoke-SchtasksDelete {
    param([string]$Name)
    cmd /c "schtasks /delete /tn `"$Name`" /f >nul 2>&1"
}

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    try {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop
    } catch {
        Write-Warning "Unregister-ScheduledTask failed for '$taskName': $($_.Exception.Message). Falling back to schtasks /delete."
        Invoke-SchtasksDelete -Name $taskName
    }
} else {
    Invoke-SchtasksDelete -Name $taskName
}

$action = New-ScheduledTaskAction `
    -Execute "wscript.exe" `
    -Argument ('"{0}"' -f $vbsPath) `
    -WorkingDirectory $repoRoot

$domainUser = if ($env:USERDOMAIN -and $env:USERDOMAIN -ne $env:COMPUTERNAME) {
    "$env:USERDOMAIN\$env:USERNAME"
} else {
    $env:USERNAME
}

# 60s delay after logon so voice-daemon's own At-Logon task fires first,
# and the network is fully up before we test the central share.
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $domainUser
$trigger.Delay = 'PT1M'

# Short-running heal pass. 5-min ceiling stops a stuck git pull from
# hanging the task forever.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -MultipleInstances IgnoreNew

try {
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description "At every logon, run the NAPCO Nucleus self-heal pass: confirm central share is reachable, re-register voice + chat scheduled tasks if missing, start the voice daemon if not already running. Logs to logs\fix-nucleus.log." `
        -RunLevel Limited `
        -ErrorAction Stop `
        | Out-Null
} catch {
    Write-Error "FAILED to register '$taskName': $($_.Exception.Message)"
    return
}

Write-Host "Registered: $taskName"
Write-Host "  Trigger:  At logon of $domainUser  (+1 min delay)"
Write-Host "  Action:   wscript $vbsPath"
Write-Host "  Logs:     $repoRoot\logs\fix-nucleus.log"
