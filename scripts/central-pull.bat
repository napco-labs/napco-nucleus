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

REM Force UTF-8 so transcripts / chat / email content with non-Latin
REM characters (Bangla, Arabic, CJK) don't crash print() on Windows'
REM cp1252 default console encoding.
set PYTHONIOENCODING=utf-8

if not exist ".venv\Scripts\python.exe" (
    REM No venv - try system python, then py launcher.
    where python.exe >nul 2>&1
    if errorlevel 1 (
        set "PY=py -3"
    ) else (
        set "PY=python"
    )
) else (
    call ".venv\Scripts\activate.bat"
    set "PY=python"
)

set "CLIENT=%~1"
if "%CLIENT%"=="" (
    set /p CLIENT="Client name (or 'all'): "
)
set "DAY=%~2"
if "%DAY%"=="" (
    %PY% collect_central.py --client "%CLIENT%"
) else (
    %PY% collect_central.py --client "%CLIENT%" --day %DAY%
)
echo.
pause
