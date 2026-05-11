@echo off
REM Double-clickable trigger: push my chat, transcribe any pending
REM calls, identify requirements, draft the verification email.
REM Wraps `py -3 do_it_now.py` with a sensible default window.
REM
REM Defaults:
REM   --client all           (process everything; narrow later if needed)
REM   --last-minutes 2880    (48 hours — covers yesterday's emails/drive)
REM
REM Override either by passing on the command line:
REM   do-it-now.bat NAPCO 120
REM     -> client="NAPCO", last_minutes=120

cd /d "%~dp0\.."
if not exist ".venv\Scripts\python.exe" (
    REM Fall back to system python if the venv hasn't been set up yet.
    set "PY=py -3"
) else (
    call ".venv\Scripts\activate.bat"
    set "PY=python"
)

set "CLIENT=%~1"
if "%CLIENT%"=="" set "CLIENT=all"

set "WINDOW=%~2"
if "%WINDOW%"=="" set "WINDOW=2880"

echo.
echo === NAPCO Nucleus: Do It Now ===
echo Client:        %CLIENT%
echo Window:        last %WINDOW% minutes
echo.

%PY% do_it_now.py --client "%CLIENT%" --last-minutes %WINDOW%

set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
    echo Done. Open your [Gmail]/Drafts to review the verification email.
) else (
    echo Pipeline exited with code %RC%. Scroll up to see the error.
)
echo.
pause
exit /b %RC%
