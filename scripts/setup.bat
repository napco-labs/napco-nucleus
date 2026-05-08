@echo off
REM Double-clickable wrapper around setup.ps1.
REM Bypasses the default PowerShell ExecutionPolicy so the teammate
REM doesn't have to do `Set-ExecutionPolicy` themselves.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
if errorlevel 1 (
    echo.
    echo Setup failed. Scroll up to see the error.
    pause
    exit /b 1
)
echo.
pause
