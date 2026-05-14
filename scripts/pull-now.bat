@echo off
REM Run collect_all for the last N minutes. Asks for the window if not provided.

cd /d "%~dp0\.."
set "MINS=%~1"
if "%MINS%"=="" (
    set /p MINS="Pull window in minutes [30]: "
)
if "%MINS%"=="" set MINS=30

if not exist ".venv\Scripts\python.exe" (
    REM No venv - try system python, then py launcher.
    where python.exe >nul 2>&1
    if errorlevel 1 (
        py -3 collect_all.py --last-minutes %MINS%
    ) else (
        python collect_all.py --last-minutes %MINS%
    )
    echo.
    pause
    exit /b %ERRORLEVEL%
)
call ".venv\Scripts\activate.bat"
python collect_all.py --last-minutes %MINS%
echo.
pause
