@echo off
REM Pull the latest code + reinstall any new dependencies.
REM Safe to run anytime -- re-runs setup.ps1 in idempotent mode so any
REM new pip dep gets picked up and any missing model gets pre-warmed.

cd /d "%~dp0\.."
echo Pulling latest code...
git pull --ff-only
if errorlevel 1 (
    echo.
    echo git pull failed. Resolve any conflicts and re-run.
    pause
    exit /b 1
)
echo.
echo Re-running setup (idempotent)...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" -SkipModelPrewarm
echo.
pause
