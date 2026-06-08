<#
.SYNOPSIS
Register the end-of-day Requirement Management run on MVPACCESS.

.DESCRIPTION
One Windows Scheduled Task, fires once daily at BD 23:00 (11:00 PM sharp):

  "NAPCO Nucleus - Requirement Management (Daily)"
      py -3 collect_central.py --client all --last-minutes 1440

What it does (per the operator rules):
  - Reads everything staged into central + local inbox over the last
    24 hours (today's entire day, plus a buffer into yesterday evening).
  - Produces the aggregation .docx (audit trail), extracts the day's
    distinct requirements, writes the verification .docx, drafts both
    .eml files, and APPENDs them into Gmail Drafts.
  - "Whole day" coverage: includes every requirement seen today,
    even if an earlier ad-hoc 'do it right now' already drafted them.

Operator-rule alignment:
  - Rule 1 (on-demand): unaffected — keep using do_it_now.py /
    requirement-management.bat / 'do it right now' any time.
  - Rule 2 (daily auto): this task IS rule 2.
  - Rule 3 (whole-day include): the 1440-min window + the accumulated
    inbox guarantee that 23:00's draft sees the full day of inputs.
    If you want the 23:00 draft to OVERWRITE earlier same-day Gmail
    drafts (rather than appending another draft), that's a follow-up
    code change to draft_verification_email — flag if you want it.

Run on MVPACCESS as Administrator:

    .\scripts\register-daily-draft-task.ps1
    .\scripts\register-daily-draft-task.ps1 -Unregister

Re-running this script is idempotent — drops + re-creates the entry,
so it doubles as the upgrade path. Uses both Unregister-ScheduledTask
and schtasks /delete as cleanup paths to dodge the orphan-task trap
(ERROR_ALREADY_EXISTS that CIM-only cleanup misses).
#>
param(
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"

$taskName = "NAPCO Nucleus - Requirement Management (Daily)"

# schtasks.exe writes harmless stderr (e.g. "task not found",
# "syntax incorrect") that PowerShell 5.1 promotes to NativeCommandError
# under -ErrorAction Stop. Wrap each call in try/catch so a non-fatal
# cleanup line can't halt the registration flow.
function Invoke-SchtasksDelete {
    param([string]$TaskName)
    try {
        schtasks /delete /tn "$TaskName" /f 2>&1 | Out-Null
    } catch {
        # Non-fatal — orphan absent OR schtasks chokes on the name.
        # CIM unregister has already had its turn; we tried our best.
    }
}

if ($Unregister) {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        try {
            Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop
            Write-Host "Removed: $taskName"
        } catch {
            Write-Warning "Unregister-ScheduledTask failed: $($_.Exception.Message). Falling back to schtasks /delete."
            Invoke-SchtasksDelete -TaskName $taskName
        }
    } else {
        Invoke-SchtasksDelete -TaskName $taskName
        Write-Host "Not present: $taskName"
    }
    return
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir

# Resolve a usable python — venv preferred, system py as fallback.
# Call collect_central.py directly rather than the do_it_now.py wrapper.
# do_it_now.py is the developer-facing entry: it (1) pushes the local
# dev's Teams chat to central, then (2) SSHes to MVPACCESS to run
# collect_central.py. When the daily task runs ON MVPACCESS itself,
# step 1 has no Teams cache to push and step 2 SSHes back to itself
# with an interactive password prompt that would hang the unattended
# 23:45 run. Calling collect_central.py directly is correct + clean.
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
    $pyExe = $venvPython
    $argString = "collect_central.py --client all --last-minutes 1440"
} else {
    $pyExe = "py"
    $argString = "-3 collect_central.py --client all --last-minutes 1440"
}

# Drop any existing entry (CIM-first, schtasks fallback to clear orphans).
if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    try {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction Stop
    } catch {
        Write-Warning "Unregister-ScheduledTask failed: $($_.Exception.Message). Falling back to schtasks /delete."
        Invoke-SchtasksDelete -TaskName $taskName
    }
} else {
    Invoke-SchtasksDelete -TaskName $taskName
}

# Anchor: today at 23:00 BD-local (11:00 PM sharp). If past, anchor tomorrow.
$anchor = (Get-Date).Date.AddHours(23)
if ((Get-Date) -gt $anchor) {
    $anchor = $anchor.AddDays(1)
}

$action = New-ScheduledTaskAction `
    -Execute $pyExe `
    -Argument $argString `
    -WorkingDirectory $repoRoot

$trigger = New-ScheduledTaskTrigger -Daily -At $anchor

# Pipeline can legitimately take a while: Whisper backlog, multi-stage
# Claude calls, Gmail Drafts APPEND. 2 hours is a comfortable cap.
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2)

try {
    Register-ScheduledTask `
        -TaskName $taskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description "Daily end-of-day Requirement Management pipeline. Fires once daily at BD 23:00 (11:00 PM sharp) and includes the whole day's requirements (even if 'do it right now' already drafted earlier in the day). Writes the verification email to Gmail Drafts for manual send." `
        -RunLevel Limited `
        -ErrorAction Stop `
        | Out-Null
} catch {
    Write-Error "FAILED to register '$taskName': $($_.Exception.Message)"
    exit 1
}

Write-Host "Registered: $taskName"
Write-Host "    Fires:    once daily at BD 23:00 - 11:00 PM sharp (next: $anchor)"
Write-Host "    Command:  $pyExe $argString"
Write-Host "    Window:   --last-minutes 1440 (24 h, covers whole day)"
Write-Host ""
Write-Host "Verify:  Get-ScheduledTask -TaskName '$taskName' | Format-List"
Write-Host "Run now: Start-ScheduledTask -TaskName '$taskName'"
Write-Host "Remove:  .\scripts\register-daily-draft-task.ps1 -Unregister"
