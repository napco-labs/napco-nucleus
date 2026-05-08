@echo off
REM Launch the voice daemon. Window stays open so logs are visible.
REM Press Ctrl+C in the window to stop the daemon.

cd /d "%~dp0\.."
if not exist ".venv\Scripts\python.exe" (
    echo Virtualenv missing. Run scripts\setup.bat first.
    pause
    exit /b 1
)
call ".venv\Scripts\activate.bat"
python -m teams.voice_daemon
echo.
echo Daemon stopped.
pause
