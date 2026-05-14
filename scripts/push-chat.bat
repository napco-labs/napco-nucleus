@echo off
REM Pushes the dev's last 15 min of Teams chat to the central store.
REM Designed to run from Windows Task Scheduler every 15 minutes.
REM
REM Task Scheduler setup (one-time, per teammate):
REM   1. Open Task Scheduler -> Create Basic Task
REM   2. Name: NAPCO Nucleus - Chat Push
REM   3. Trigger: Daily, recur every 1 day, repeat every 15 minutes
REM      indefinitely, starting at 9:00 AM
REM   4. Action: Start a program
REM      Program/script:  cmd.exe
REM      Arguments:       /c "%~dp0push-chat.bat"  (replace %~dp0 with the
REM                       absolute path to the napco-nucleus\scripts dir)
REM      Start in:        absolute path to the napco-nucleus folder
REM   5. Conditions: uncheck "Start the task only if the computer is on AC"
REM   6. Settings: check "Run task as soon as possible after a scheduled
REM      start is missed" so a sleeping laptop catches up on wake.
REM
REM Or use the helper: scripts\register-chat-push-task.ps1

cd /d "%~dp0\.."

REM Force UTF-8 so chat content with Bangla/Arabic/CJK characters doesn't
REM crash print() on Windows' cp1252 default console encoding.
set PYTHONIOENCODING=utf-8

REM Delayed expansion so `!ERRORLEVEL!` inside the if-block reflects the
REM python exit code, not the (parse-time) stale value `%ERRORLEVEL%` gives.
setlocal enabledelayedexpansion

if not exist ".venv\Scripts\python.exe" (
    REM No venv on this machine - try system python, then py launcher.
    where python.exe >nul 2>&1
    if errorlevel 1 (
        py -3 -m teams.push_chat --last-minutes 15
    ) else (
        python -m teams.push_chat --last-minutes 15
    )
    exit /b !ERRORLEVEL!
)
call ".venv\Scripts\activate.bat"
python -m teams.push_chat --last-minutes 15
exit /b !ERRORLEVEL!
