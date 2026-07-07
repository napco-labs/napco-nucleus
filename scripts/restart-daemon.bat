@echo off
REM restart-daemon.bat
REM
REM Restart the voice daemon after a `git pull` so the running process picks
REM up new code. The daemon runs as the scheduled task "NAPCO Nucleus - Voice
REM Daemon" (task -> wscript -> cmd -> python), so ending the task alone can
REM leave the python grandchild alive. This script: ends the task, force-kills
REM any lingering voice_daemon python, restarts the task, then lists what's up.
REM
REM Usage: double-click, or run  scripts\restart-daemon.bat  from a terminal.

setlocal
set TASK=NAPCO Nucleus - Voice Daemon

echo [restart-daemon] Ending scheduled task "%TASK%"...
schtasks /End /TN "%TASK%" >nul 2>&1

echo [restart-daemon] Killing any lingering voice_daemon python processes...
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'voice_daemon' } | ForEach-Object { Write-Host ('  -> killing PID ' + $_.ProcessId); Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"

REM Give the OS a moment to release the audio/loopback device before relaunch.
REM ping-based sleep (works even where timeout.exe can't grab the console).
ping -n 3 127.0.0.1 >nul

echo [restart-daemon] Starting scheduled task "%TASK%"...
schtasks /Run /TN "%TASK%" >nul 2>&1

ping -n 5 127.0.0.1 >nul

echo.
echo [restart-daemon] Running voice_daemon processes (expect 1):
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'voice_daemon' } | Select-Object ProcessId, ExecutablePath | Format-Table -AutoSize"

echo [restart-daemon] Done. Live log:  powershell -c \"Get-Content logs\voice_daemon.log -Wait -Tail 50\"
endlocal
