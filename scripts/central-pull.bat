@echo off
REM Run on the AGENT HOST (where Claude is authenticated).
REM Aggregates every dev's central uploads for a given client + day,
REM transcribes the call recordings, builds one session doc, runs
REM identify, and drafts the verification email.
REM
REM Usage:
REM    scripts\central-pull.bat                       (today, prompts for client)
REM    scripts\central-pull.bat "Susmoy"              (today, client "Susmoy")
REM    scripts\central-pull.bat "Susmoy" 2026-05-08

cd /d "%~dp0\.."
if not exist ".venv\Scripts\python.exe" (
    python collect_central.py --client %1 --day %2
    pause
    exit /b %ERRORLEVEL%
)
call ".venv\Scripts\activate.bat"

set "CLIENT=%~1"
if "%CLIENT%"=="" (
    set /p CLIENT="Client name (or 'all'): "
)
set "DAY=%~2"
if "%DAY%"=="" (
    python collect_central.py --client "%CLIENT%"
) else (
    python collect_central.py --client "%CLIENT%" --day %DAY%
)
echo.
pause
