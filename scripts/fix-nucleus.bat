@echo off
setlocal enabledelayedexpansion
title NAPCO Nucleus - Self-Heal

REM ============================================================
REM  NAPCO Nucleus - Self-Heal
REM
REM  Interactive run (double-click):
REM    Drop this file anywhere (Desktop, Downloads, ...) and
REM    double-click. It auto-detects the repo, fixes everything,
REM    and registers itself to auto-run at every future logon.
REM
REM  Quiet run (--quiet, used by the auto-logon task):
REM    No prompts, no pause, skips the chat-backfill step, logs
REM    silently to <repo>\logs\fix-nucleus.log.
REM ============================================================

set "QUIET=0"
if /I "%~1"=="--quiet" set "QUIET=1"
if /I "%~1"=="/quiet"  set "QUIET=1"

if "%QUIET%"=="0" (
    echo.
    echo ============================================================
    echo   NAPCO Nucleus - Self-Heal
    echo   User: %USERNAME%   PC: %COMPUTERNAME%
    echo ============================================================
    echo.
) else (
    echo [%date% %time%] --- self-heal --quiet run starting on %COMPUTERNAME% as %USERNAME% ---
)

REM ── Locate the napco-nucleus repo ──────────────────────────
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
    if "%QUIET%"=="1" (
        echo ERROR: --quiet mode and could not auto-detect the repo. Aborting.
        endlocal & exit /b 1
    )
    echo Could not auto-detect your napco-nucleus repo.
    echo Please type the full path and press Enter.
    echo Example:  F:\Titu vai\napco-nucleus
    echo.
    set /p "NN_FOUND=Path to your napco-nucleus repo: "
)

if not exist "%NN_FOUND%\.git" (
    echo.
    echo ERROR: "%NN_FOUND%\.git" does not exist. Aborting.
    if "%QUIET%"=="0" pause
    endlocal & exit /b 1
)

set "NN=%NN_FOUND%"
setx NN "%NN%" >nul 2>&1
echo Repo: %NN%
echo.

pushd "%NN%" >nul

set "FAIL_COUNT=0"

REM ── 1/7 git pull ────────────────────────────────────────────
REM A plain --ff-only aborts the moment ANY tracked file is locally
REM modified, and this used to just print WARN and carry on. That is how
REM every recorder quietly stopped updating: on 2026-07-30 .72 was 6
REM commits behind with two hand-edited files, ROCKY-PRO was 94 behind
REM and .209 was 180 behind -- all of them pulling on every logon, all of
REM them failing on the same error nobody reads in a --quiet log.
REM So: retry once behind an auto-stash. The stash is kept (never
REM dropped), named with a timestamp, so a real local edit is recoverable
REM with `git stash list`; code advancing matters more than a working
REM tree nobody meant to edit.
echo [1/7] Updating repo (git pull --ff-only)...
git pull --ff-only
if errorlevel 1 (
    echo       pull blocked -- stashing local changes and retrying once...
    for /f "tokens=* delims=" %%S in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "NN_STAMP=%%S"
    git stash push -m "self-heal auto-stash !NN_STAMP!"
    git pull --ff-only
    if errorlevel 1 (
        echo       WARN: git pull STILL failed -- continuing with current code.
        echo       Run `git status` and `git stash list` in %NN% by hand.
        set /a FAIL_COUNT+=1
    ) else (
        echo       OK: pulled after stashing. Local edits kept in the stash --
        echo       recover with: git stash list ^&^& git stash show -p stash@{0}
    )
)

REM Say out loud if this machine is still behind. A recorder running old
REM code produces silently wrong output -- stale .opus files, the old
REM client resolver returning (unknown) -- rather than an error, so the
REM only way anyone notices is a line like this.
for /f "tokens=* delims=" %%B in ('git rev-list --count HEAD..origin/main 2^>nul') do set "NN_BEHIND=%%B"
if not "!NN_BEHIND!"=="0" if not "!NN_BEHIND!"=="" (
    echo       *** WARNING: this machine is !NN_BEHIND! commit^(s^) BEHIND origin/main.
    echo       *** It is recording with old code. Fix before trusting its output.
    set /a FAIL_COUNT+=1
)
echo.

REM ── 2/7 central share ───────────────────────────────────────
echo [2/7] Checking central share is reachable...
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

REM ── 3/7 voice daemon scheduled task ────────────────────────
echo [3/7] Re-registering voice-daemon scheduled task...
powershell -NoProfile -ExecutionPolicy Bypass -File "%NN%\scripts\register-voice-daemon-task.ps1"
if errorlevel 1 (
    echo       WARN: voice-daemon task registration failed.
    set /a FAIL_COUNT+=1
)
echo.

REM ── 4/7 chat-push scheduled tasks ──────────────────────────
echo [4/7] Re-registering chat-push scheduled tasks...
powershell -NoProfile -ExecutionPolicy Bypass -File "%NN%\scripts\register-chat-push-task.ps1"
if errorlevel 1 (
    echo       WARN: chat-push task registration failed.
    set /a FAIL_COUNT+=1
)
echo.

REM ── 5/8 self-heal at-logon task (only installs once; idempotent) ──
echo [5/8] Re-registering self-heal at-logon task...
powershell -NoProfile -ExecutionPolicy Bypass -File "%NN%\scripts\register-self-heal-task.ps1"
if errorlevel 1 (
    echo       WARN: self-heal task registration failed.
    set /a FAIL_COUNT+=1
)
echo.

REM ── 6/8 voice watchdog (every 5 min crash detector) ────────
echo [6/8] Re-registering voice watchdog task...
powershell -NoProfile -ExecutionPolicy Bypass -File "%NN%\scripts\register-voice-watchdog-task.ps1"
if errorlevel 1 (
    echo       WARN: voice watchdog task registration failed.
    set /a FAIL_COUNT+=1
)
echo.

REM ── 7/8 start voice daemon now ─────────────────────────────
echo [7/8] Starting voice daemon now (no need to log out)...
powershell -NoProfile -Command "Start-ScheduledTask -TaskName 'NAPCO Nucleus - Voice Daemon'; Start-Sleep -Seconds 2; $proc = Get-Process pythonw, python -ErrorAction SilentlyContinue; if ($proc) { 'OK: python is running (' + $proc.Count + ' proc).' } else { Write-Warning 'voice daemon did not appear -- check logs\voice_daemon.log' }"
echo.

REM ── call backfill: re-push any local calls missing from central ──
REM  Always runs (incl. --quiet logon self-heal) so a call stranded
REM  by a failed live push self-heals on the next logon, no manual step.
echo [*] Backfilling any local calls missing from central...
python -m teams.backfill_central
if errorlevel 1 (
    echo       WARN: call backfill reported a failure -- see output above.
    set /a FAIL_COUNT+=1
)
echo.

REM ── 8/8 chat backfill (interactive only; auto-run skips) ───
if "%QUIET%"=="0" (
    echo [8/8] Pushing the last 4 hours of chat to central as a backfill...
    python -m teams.push_chat --last-minutes 240
    if errorlevel 1 (
        echo       WARN: chat backfill failed -- scheduled tasks will
        echo       still push automatically on their next tick.
        set /a FAIL_COUNT+=1
    )
    echo.
) else (
    echo [8/8] Skipping 4h chat backfill in --quiet mode (scheduled tasks handle it).
    echo.
)

echo ============================================================
if !FAIL_COUNT! GTR 0 (
    echo   Self-heal finished with !FAIL_COUNT! warning(s) above.
    if "%QUIET%"=="0" echo   Send a screenshot of this window to Titu if unsure.
) else (
    echo   Self-heal complete. All systems healthy.
    if "%QUIET%"=="0" (
        echo   Voice will record on your next Teams call automatically.
        echo   Chat will push every 30 min - 2 hr from now on.
        echo   This script will also auto-run at every logon from now on.
    )
)
echo ============================================================
echo.

popd >nul
endlocal
if "%QUIET%"=="0" pause
