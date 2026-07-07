@echo off
REM first-time-setup.bat
REM
REM One-click onboarding for a BRAND-NEW record-and-push dev PC. Run it ONCE,
REM right after cloning the repo. Prerequisites you must install manually
REM first: Git and Python 3.12 (the 'py' launcher).
REM
REM It: creates the project venv, installs the recorder dependencies, makes
REM .env from the dev template, registers the voice-daemon autostart task,
REM then runs setup-central (you enter the dev name + Napco share password).
REM
REM Existing PCs do NOT need this -- they just 'git pull' + setup-central.bat.
REM If the task/credential steps error, right-click -> Run as administrator.

setlocal
set "REPO=%~dp0.."
pushd "%REPO%"

echo ============================================================
echo  NAPCO Nucleus - first-time dev PC setup
echo  repo: %CD%
echo ============================================================
echo.

REM --- 0. Python present? --------------------------------------------------
py -3 --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python 3 not found. Install Python 3.12 with the 'py' launcher
    echo        and Git, then re-run this script.
    popd
    pause
    exit /b 1
)

REM --- 1. project venv -----------------------------------------------------
if exist ".venv\Scripts\python.exe" (
    echo [1/5] venv already exists - skipping.
) else (
    echo [1/5] creating .venv ...
    py -3 -m venv .venv
    if errorlevel 1 (
        echo   venv creation FAILED.
        popd
        pause
        exit /b 1
    )
)

REM --- 2. recorder dependencies -------------------------------------------
echo [2/5] installing recorder dependencies ^(may take a minute^)...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\pip.exe" install -r requirements-recorder.txt
if errorlevel 1 (
    echo   pip install FAILED - check internet / proxy and re-run.
    popd
    pause
    exit /b 1
)

REM --- 3. .env from the dev template --------------------------------------
if exist ".env" (
    echo [3/5] .env already exists - leaving it as-is.
) else (
    echo [3/5] creating .env from .env.example.dev ...
    copy /y ".env.example.dev" ".env" >nul
)

REM --- 4. register the voice-daemon autostart task ------------------------
echo [4/5] registering the voice-daemon autostart task...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0register-voice-daemon-task.ps1"
if errorlevel 1 (
    echo   task registration FAILED - try running this script as administrator.
    popd
    pause
    exit /b 1
)

REM --- 5. central access + dev name + start + backfill + healthcheck ------
echo [5/5] configuring central access ^(enter the dev name + share password when asked^)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-central.ps1"

echo.
echo ============================================================
echo  First-time setup finished. In the healthcheck output above,
echo  smb-share should read samba_creds=set and the rest all-green.
echo ============================================================
popd
pause
