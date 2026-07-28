# NAPCO Nucleus - put MASTAN2 (.72) to sleep for the night.
#
# Sleep rather than shutdown, so the logged-in session survives. Every Nucleus
# daemon is an at-logon task; sleeping keeps the session, so the 11:00 wake
# timer brings everything back with nobody touching the machine.
#
# Presence-wise this is identical to shutting down: Teams stops talking to
# Microsoft, so it shows Away and then Offline. Going dark overnight is what a
# person looks like. A bot is the thing that is Available at 04:00.
#
# Guard: never cut a live call. record_call drops .recording_active while
# capturing and the finalizer still has to encode and mirror to central.
$ErrorActionPreference = "Continue"
$repo   = "E:\napco-nucleus"
$marker = Join-Path $repo "data\teams\.recording_active"
$log    = Join-Path $repo "logs\nightly_sleep.log"

function Write-Log($m) {
    Add-Content -Path $log -Encoding utf8 -Value ("{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m)
}

$maxWaitMinutes = 60
$waited = 0
while ((Test-Path $marker) -and ($waited -lt $maxWaitMinutes)) {
    Write-Log "call in progress, holding sleep ($waited/$maxWaitMinutes min)"
    Start-Sleep -Seconds 300
    $waited += 5
}
if (Test-Path $marker) {
    Write-Log "call STILL recording after $maxWaitMinutes min - sleeping anyway"
} else {
    Write-Log "no call in progress"
}

Write-Log "going to sleep now"
# SetSuspendState HIBERNATES instead of sleeping whenever hibernation is
# enabled, whatever the first argument says. Hibernation is turned off by the
# register script so this is a real S3 sleep that a wake timer can bring back.
rundll32.exe powrprof.dll,SetSuspendState 0,1,0
