@echo off
REM Launch the voice daemon. Window stays open so logs are visible.
REM Press Ctrl+C in the window to stop the daemon.

cd /d "%~dp0\.."
if not exist ".venv\Scripts\python.exe" (
    REM No venv on this machine - fall back to system python.
    python -m teams.voice_daemon
    echo.
    echo Daemon stopped.
    pause
    exit /b %ERRORLEVEL%
)
call ".venv\Scripts\activate.bat"
python -m teams.voice_daemon
echo.
echo Daemon stopped.
pause
