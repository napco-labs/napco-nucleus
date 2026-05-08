@echo off
REM Run collect_all for the last N minutes. Asks for the window if not provided.

cd /d "%~dp0\.."
if not exist ".venv\Scripts\python.exe" (
    echo Virtualenv missing. Run scripts\setup.bat first.
    pause
    exit /b 1
)
call ".venv\Scripts\activate.bat"
set "MINS=%~1"
if "%MINS%"=="" (
    set /p MINS="Pull window in minutes [30]: "
)
if "%MINS%"=="" set MINS=30
python collect_all.py --last-minutes %MINS%
echo.
pause
