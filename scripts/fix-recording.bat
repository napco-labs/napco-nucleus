@echo off
REM ============================================================
REM  NAPCO Nucleus - one-click recording fix
REM ============================================================
REM  Symptom this repairs: calls record a MIC track but the
REM  SPEAKER track comes up empty (~44 bytes) -> the client's
REM  voice is lost. Cause is almost always a daemon running code
REM  from before the 2026-06-09 loopback self-heal (da0d698) plus
REM  Teams holding the output device in exclusive mode.
REM
REM  What it does:
REM    1. self-elevates to Administrator (needed for the HKLM
REM       exclusive-mode registry fix)
REM    2. stops the stale voice daemon
REM    3. git pull  (pulls the speaker self-heal + exclusive-mode fixes)
REM    4. re-registers the daemon + watchdog scheduled tasks
REM    5. starts the daemon
REM
REM  Site-agnostic: no machine / dev / device hardcoded. Run on
REM  ANY dev PC showing the empty-speaker symptom.
REM
REM  Just double-click it. Then RESTART TEAMS and make a test call.
REM ============================================================

REM --- self-elevate to admin if not already ---
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator rights...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

REM --- repo root is the parent of this script's folder ---
cd /d "%~dp0\.."
echo.
echo === Repo: %CD%
echo.

echo === [1/5] Stopping the stale voice daemon...
schtasks /End /TN "NAPCO Nucleus - Voice Daemon" >nul 2>&1
taskkill /F /IM python.exe >nul 2>&1
taskkill /F /IM pythonw.exe >nul 2>&1

echo === [2/5] Updating to latest code (speaker self-heal + exclusive-mode fix)...
git pull
if errorlevel 1 (
    echo.
    echo  WARNING: git pull failed. Resolve the repo state above, then re-run.
    echo.
    pause
    exit /b 1
)

echo === [3/5] Re-registering the voice daemon task...
powershell -ExecutionPolicy Bypass -File "scripts\register-voice-daemon-task.ps1"

echo === [4/5] Re-registering the watchdog task...
powershell -ExecutionPolicy Bypass -File "scripts\register-voice-watchdog-task.ps1"

echo === [5/5] Starting the daemon now...
start "" "scripts\start-daemon-hidden.vbs"

echo.
echo ============================================================
echo  DONE. Two manual steps remain:
echo    1. RESTART MS Teams  (so it reopens audio WITHOUT the
echo       exclusive-mode lock the fix just cleared)
echo    2. Make a short TEST CALL, then confirm the new
echo       *_speaker.wav is MB-sized, not 44 bytes.
echo.
echo  Verify capture in the log:
echo    powershell -c "Get-Content logs\voice_daemon.log -Tail 40 ^| Select-String 'exclusive^|loopback'"
echo ============================================================
echo.
pause
