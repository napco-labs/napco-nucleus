@echo off
REM One-click installer for the voice daemon autostart task.
REM Registers a Windows Scheduled Task that launches the daemon at every
REM logon, restarts it on crash, and immediately starts it once so you
REM don't have to log out and back in.

setlocal
set "TASK_NAME=NAPCO Nucleus - Voice Daemon"
cd /d "%~dp0\.."

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0register-voice-daemon-task.ps1"
if errorlevel 1 (
    echo.
    echo Registration failed. See the error above.
    pause
    exit /b 1
)

powershell -NoProfile -Command "Start-ScheduledTask -TaskName '%TASK_NAME%'"
if errorlevel 1 (
    echo.
    echo Task registered, but failed to start immediately.
    echo Log out and back in, or run:
    echo     Start-ScheduledTask -TaskName "%TASK_NAME%"
    pause
    exit /b 1
)

echo.
echo Voice daemon autostart installed and running.
echo The console window will appear at every logon from now on.
echo.
echo Remove with:  scripts\uninstall-voice-daemon.bat
pause
