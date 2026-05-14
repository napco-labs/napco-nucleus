@echo off
REM Ad-hoc / manual entry-point: pushes the dev's last 15 min of Teams chat
REM to the central store. Equivalent to `python -m teams.push_chat --last-minutes 15`.
REM
REM Scheduled chat-push (Day / Transition / Evening windows) is registered
REM separately by scripts\register-chat-push-task.ps1 and goes through
REM scripts\push-chat-hidden.vbs (hidden window, log to logs\chat_push.log).
REM This .bat is just for manual invocations like a voice-trigger
REM "push my chat right now" or a quick CLI debug -- it opens a cmd window
REM by design so you can see the output.

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
