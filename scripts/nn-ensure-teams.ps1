# NAPCO Nucleus - make sure Teams actually has a WINDOW.
#
# After a reboot Teams auto-starts into the background: the ms-teams processes
# are running but no window exists, so every UI-automation daemon is alive and
# blind. Proven on .72 2026-07-28 after the auto-logon reboot -- the desktop had
# exactly three windows (taskbar, a console, Program Manager) and none of them
# were Teams, so nothing could be read or replied to.
#
# Process presence is NOT the test. MainWindowHandle is.
$ErrorActionPreference = "Continue"
$log = "E:\napco-nucleus\logs\ensure_teams.log"
function Write-Log($m) {
    Add-Content -Path $log -Encoding utf8 -Value ("{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $m)
}

function Get-TeamsWindow {
    Get-Process -Name 'ms-teams' -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
}

if (Get-TeamsWindow) { exit 0 }          # window is there, nothing to do, stay quiet

Write-Log "no Teams window - launching"
# shell:AppsFolder is the reliable way to start the packaged (new) Teams and
# have it actually show a window; starting the exe directly can rejoin the
# existing background instance and stay hidden.
Start-Process "explorer.exe" "shell:AppsFolder\MSTeams_8wekyb3d8bbwe!MSTeams"

for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 3
    $w = Get-TeamsWindow
    if ($w) {
        Write-Log ("Teams window up after {0}s (pid {1})" -f (($i + 1) * 3), $w.Id)
        exit 0
    }
}
Write-Log "Teams still has no window after 60s"
exit 1
