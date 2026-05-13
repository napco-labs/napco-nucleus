@echo off
REM Remove the voice daemon autostart task. The daemon's current
REM session keeps running until you close its window or log off.

cd /d "%~dp0\.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0register-voice-daemon-task.ps1" -Unregister
pause
