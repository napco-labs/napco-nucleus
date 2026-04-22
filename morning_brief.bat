@echo off
REM Morning Brief — invoked by Windows Task Scheduler at 08:30 local time.
REM Reads last night's nightly artifacts, classifies failures, computes
REM 7-day trend, emails a 1-page HTML brief (with the full PDF attached)
REM to MORNING_BRIEF_TO (or TEAM_EMAILS as fallback).

cd /d "%~dp0"

if not exist "logs" mkdir "logs"

for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"`) do set "STAMP=%%D"
set "LOG=logs\morning_brief_%STAMP%.log"

if exist ".venv\Scripts\activate.bat" call .venv\Scripts\activate.bat

echo ===== Morning brief started at %DATE% %TIME% ===== >> "%LOG%"
python morning_brief.py >> "%LOG%" 2>&1
echo ===== Morning brief finished at %DATE% %TIME% ===== >> "%LOG%"
