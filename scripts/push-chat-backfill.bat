@echo off
REM Once-per-day backfill push at BD 18:00. Covers the gap between the
REM previous evening's 01:00 window-close and today's 18:00 reopen.
REM
REM Window: --last-minutes 1080 (18 hours).

cd /d "%~dp0\.."
if not exist ".venv\Scripts\python.exe" (
    python -m teams.push_chat --last-minutes 1080
    exit /b %ERRORLEVEL%
)
call ".venv\Scripts\activate.bat"
python -m teams.push_chat --last-minutes 1080
exit /b %ERRORLEVEL%
