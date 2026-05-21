@echo off
setlocal enabledelayedexpansion
title NAPCO Nucleus - Self-Heal

REM ============================================================
REM  NAPCO Nucleus - Self-Heal
REM  Drop this file ANYWHERE on your PC (Desktop, Downloads, etc.)
REM  and double-click to run. Idempotent -- safe to re-run any time
REM  voice or chat capture stops working.
REM
REM  Repo location is auto-detected. If it can't be found, you'll
REM  be prompted once -- the path is then saved as %NN% so future
REM  runs find it instantly.
REM ============================================================

echo.
echo ============================================================
echo   NAPCO Nucleus - Self-Heal
echo   User: %USERNAME%   PC: %COMPUTERNAME%
echo ============================================================
echo.

REM ── Locate the napco-nucleus repo ──────────────────────────
REM Candidate paths in priority order:
REM   %NN%                          - env var, set by onboard.bat
REM   E:\Projects\NAPCO-Nucleus     - Titu (standard layout)
REM   F:\Titu vai\napco-nucleus     - Atik
REM   D:\POC Projects\napco-nucleus - Rocky
REM   <drive>:\napco-nucleus        - other common layouts
REM Last resort: prompt user, then persist via setx.

set "NN_FOUND="
for %%P in (
    "%NN%"
    "E:\Projects\NAPCO-Nucleus"
    "F:\Titu vai\napco-nucleus"
    "D:\POC Projects\napco-nucleus"
    "C:\napco-nucleus"
    "D:\napco-nucleus"
    "E:\napco-nucleus"
    "F:\napco-nucleus"
    "G:\napco-nucleus"
) do (
    if not defined NN_FOUND if exist "%%~P\.git" (
        set "NN_FOUND=%%~P"
    )
)

if not defined NN_FOUND (
    echo Could not auto-detect your napco-nucleus repo.
    echo Please type the full path and press Enter.
    echo Example:  F:\Titu vai\napco-nucleus
    echo.
    set /p "NN_FOUND=Path to your napco-nucleus repo: "
)

if not exist "%NN_FOUND%\.git" (
    echo.
    echo ERROR: "%NN_FOUND%\.git" does not exist.
    echo Make sure you cloned the repo, then re-run this script.
    echo.
    pause
    exit /b 1
)

set "NN=%NN_FOUND%"
setx NN "%NN%" >nul 2>&1
echo Repo: %NN%
echo.

pushd "%NN%" >nul

set "FAIL_COUNT=0"

REM ── 1/6 git pull ────────────────────────────────────────────
echo [1/6] Updating repo (git pull --ff-only)...
git pull --ff-only
if errorlevel 1 (
    echo       WARN: git pull failed -- continuing with current code.
    set /a FAIL_COUNT+=1
)
echo.

REM ── 2/6 central share ───────────────────────────────────────
echo [2/6] Checking central share is reachable...
powershell -NoProfile -Command "if (Test-Path '\\172.16.205.123\nucleus-central') { 'OK: share reachable.' } else { Write-Error 'cannot reach \\172.16.205.123\nucleus-central -- check VPN/network.'; exit 1 }"
if errorlevel 1 (
    set /a FAIL_COUNT+=1
    echo       This is a HARD failure -- voice and chat cannot upload
    echo       until the share comes back. Try opening this in Explorer:
    echo           \\172.16.205.123\nucleus-central
    echo       If prompted for username/password, see SAMBA_USER and
    echo       SAMBA_PASSWORD in %NN%\.env. Then re-run this script.
)
echo.

REM ── 3/6 voice daemon scheduled task ────────────────────────
echo [3/6] Re-registering voice-daemon scheduled task...
powershell -NoProfile -ExecutionPolicy Bypass -File "%NN%\scripts\register-voice-daemon-task.ps1"
if errorlevel 1 (
    echo       WARN: voice-daemon task registration failed.
    set /a FAIL_COUNT+=1
)
echo.

REM ── 4/6 chat-push scheduled tasks ──────────────────────────
echo [4/6] Re-registering chat-push scheduled tasks...
powershell -NoProfile -ExecutionPolicy Bypass -File "%NN%\scripts\register-chat-push-task.ps1"
if errorlevel 1 (
    echo       WARN: chat-push task registration failed.
    set /a FAIL_COUNT+=1
)
echo.

REM ── 5/6 start voice daemon now ─────────────────────────────
echo [5/6] Starting voice daemon now (no need to log out)...
powershell -NoProfile -Command "Start-ScheduledTask -TaskName 'NAPCO Nucleus - Voice Daemon'; Start-Sleep -Seconds 2; $proc = Get-Process pythonw, python -ErrorAction SilentlyContinue; if ($proc) { 'OK: python is running (' + $proc.Count + ' proc).' } else { Write-Warning 'voice daemon did not appear -- check logs\voice_daemon.log' }"
echo.

REM ── 6/6 chat backfill ──────────────────────────────────────
echo [6/6] Pushing the last 4 hours of chat to central as a backfill...
python -m teams.push_chat --last-minutes 240
if errorlevel 1 (
    echo       WARN: chat backfill failed -- the scheduled tasks above
    echo       will still push automatically on the next tick.
    set /a FAIL_COUNT+=1
)
echo.

echo ============================================================
if !FAIL_COUNT! GTR 0 (
    echo   Self-heal finished with !FAIL_COUNT! warning(s) above.
    echo   Send a screenshot of this window to Titu if unsure.
) else (
    echo   Self-heal complete. All systems healthy.
    echo   Voice will record on your next Teams call automatically.
    echo   Chat will push every 30 min - 2 hr from now on.
)
echo ============================================================
echo.

popd >nul
endlocal
pause
