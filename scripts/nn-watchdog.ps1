# NN Watchdog: restart any critical Napco Nucleus task whose process has died.
# Runs every few minutes via "NAPCO Nucleus - Watchdog" scheduled task.
$log = "E:\napco-nucleus\logs\nn-watchdog.log"
$checks = @(
  @{ Task = "NAPCO Nucleus - Auto Reply";     Match = "auto_reply" },
  @{ Task = "NAPCO Nucleus - Live Heartbeat"; Match = "live_heartbeat" },
  @{ Task = "NAPCO Nucleus - Auto Answer";    Match = "auto_answer" },
  @{ Task = "NAPCO Nucleus - Voice Daemon";   Match = "voice_daemon" }
)
foreach ($c in $checks) {
  $t = Get-ScheduledTask -TaskName $c.Task -ErrorAction SilentlyContinue
  if (-not $t) { continue }
  $proc = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
          Where-Object { $_.CommandLine -match $c.Match }
  if (-not $proc) {
    try {
      Start-ScheduledTask -TaskName $c.Task
      "$(Get-Date -Format s) RESTARTED $($c.Task) (process was dead)" | Out-File -Append -Encoding utf8 $log
    } catch {
      "$(Get-Date -Format s) FAILED to restart $($c.Task): $($_.Exception.Message)" | Out-File -Append -Encoding utf8 $log
    }
  }
}
