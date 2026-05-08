<#
.SYNOPSIS
Register the Teams chat-push as a Windows scheduled task that runs every 15 min.

.DESCRIPTION
Creates a Task Scheduler entry named "NAPCO Nucleus - Chat Push" that
executes scripts\push-chat.bat every 15 minutes, starting at the next
quarter-hour. Runs whether the user is logged in or not (on the same
account that registered the task).

Re-running this script removes any existing task with the same name
and re-creates it, so it doubles as the upgrade path.

.EXAMPLE
    .\scripts\register-chat-push-task.ps1
    .\scripts\register-chat-push-task.ps1 -IntervalMinutes 30
    .\scripts\register-chat-push-task.ps1 -Unregister
#>
param(
    [int]$IntervalMinutes = 15,
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"
$taskName = "NAPCO Nucleus - Chat Push"

if ($Unregister) {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "Removed scheduled task: $taskName"
    } else {
        Write-Host "No task named '$taskName' to remove."
    }
    return
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$batPath = Join-Path $scriptDir "push-chat.bat"

if (-not (Test-Path $batPath)) {
    Write-Error "push-chat.bat not found at $batPath"
    exit 1
}

# Drop any existing task with the same name so this is idempotent.
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$batPath`"" `
    -WorkingDirectory $repoRoot

# Start at the next quarter-hour boundary so multiple devs don't all
# hit the central share at the same second.
$now = Get-Date
$nextQuarter = $now.AddMinutes(15 - ($now.Minute % 15)).Date.AddHours($now.Hour).AddMinutes(15 * [int](($now.Minute) / 15) + 15)
if ($nextQuarter -lt $now.AddSeconds(30)) { $nextQuarter = $nextQuarter.AddMinutes(15) }

$trigger = New-ScheduledTaskTrigger -Once -At $nextQuarter `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) `
    -RepetitionDuration ([TimeSpan]::FromDays(365 * 5))

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Pushes the last $IntervalMinutes min of Teams chat into NUCLEUS_CENTRAL_PATH for the agent host." `
    -RunLevel Limited `
    | Out-Null

Write-Host "Registered '$taskName' to run every $IntervalMinutes min, starting $nextQuarter."
Write-Host "View it: Task Scheduler -> Task Scheduler Library -> $taskName"
Write-Host "Run now: Start-ScheduledTask -TaskName '$taskName'"
Write-Host "Remove:  scripts\register-chat-push-task.ps1 -Unregister"
