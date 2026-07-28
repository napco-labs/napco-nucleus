# NAPCO Nucleus - nightly shutdown of MASTAN2 (.72) at 23:00 BD time.
#
# Matches the assistant's away window (active_hours 11:00-23:00): once it stops
# answering, the box has nothing left to do, and a machine that is off cannot
# leak presence, cannot be automated, and cannot record anything.
#
# One guard: never cut a call that is still being recorded. record_call.py
# drops .recording_active while capturing, and the finalizer needs to run to
# encode and mirror the tracks to central. Losing a client call to a scheduled
# power-off would cost far more than a late shutdown.
$ErrorActionPreference = "Continue"
$repo   = "E:\napco-nucleus"
$marker = Join-Path $repo "data\teams\.recording_active"
$log    = Join-Path $repo "logs\nightly_shutdown.log"

function Write-Log($m) {
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m
    Add-Content -Path $log -Value $line -Encoding utf8
}

$maxWaitMinutes = 60
$waited = 0
while ((Test-Path $marker) -and ($waited -lt $maxWaitMinutes)) {
    Write-Log "call in progress, holding shutdown ($waited/$maxWaitMinutes min)"
    Start-Sleep -Seconds 300
    $waited += 5
}

if (Test-Path $marker) {
    Write-Log "call STILL recording after $maxWaitMinutes min - shutting down anyway"
} else {
    Write-Log "no call in progress"
}

Write-Log "shutting down now"
shutdown.exe /s /t 90 /c "NAPCO Nucleus nightly shutdown (23:00). Save your work."
