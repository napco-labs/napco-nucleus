@echo off
REM Nightly test run — invoked by Windows Task Scheduler at 00:01 every day.
REM Runs the default full-cycle agent prompt and writes output to logs\nightly_YYYY-MM-DD.log.

cd /d "%~dp0"

if not exist "logs" mkdir "logs"

REM Build timestamp YYYY-MM-DD (locale-safe via PowerShell)
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "Get-Date -Format yyyy-MM-dd"`) do set "STAMP=%%D"

set "LOG=logs\nightly_%STAMP%.log"

if exist ".venv\Scripts\activate.bat" call .venv\Scripts\activate.bat

echo ===== Nightly run started at %DATE% %TIME% ===== >> "%LOG%"
python main.py >> "%LOG%" 2>&1
echo ===== Nightly run finished at %DATE% %TIME% ===== >> "%LOG%"
