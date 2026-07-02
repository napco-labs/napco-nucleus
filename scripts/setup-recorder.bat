@echo off
REM One-click isolated setup for recording-only dev PCs.
REM
REM What it does:
REM   1. Creates a Python venv inside this repo folder (nothing written globally)
REM   2. Installs recording-only dependencies into the venv
REM   3. Registers the voice daemon as a Windows Scheduled Task
REM
REM Requirements:
REM   - Python 3.12+ must be installed on this PC (one-time system install only)
REM   - Run this script ONCE as your normal user (no admin needed)
REM   - Place .env (from Titu) in the same folder as this script's parent BEFORE running
REM
REM After this script:
REM   - The voice daemon starts automatically when you log in
REM   - Call audio is mirrored to central automatically during Teams calls
REM   - Nothing is installed outside of this folder

setlocal
cd /d "%~dp0\.."
set "REPO=%CD%"

echo.
echo ================================================================
echo  NAPCO Nucleus - Recording-only isolated setup
echo  All files stay inside: %REPO%
echo ================================================================
echo.

REM -- Step 0: Warn if not running elevated. The recorder disables audio
REM    exclusive mode via a HKEY_LOCAL_MACHINE write (needs admin); without
REM    it Teams can grab the device in exclusive mode and produce 0-byte
REM    recordings. net session succeeds only in an elevated context.
net session >nul 2>&1
if errorlevel 1 (
    echo [WARN] This window is NOT running as Administrator.
    echo        Recording may still register, but the audio exclusive-mode fix
    echo        needs admin. Without it you can get 0-byte recordings.
    echo        Recommended: close this, reopen PowerShell as Administrator,
    echo        and re-run this script.
    echo.
    choice /c YN /m "Continue anyway"
    if errorlevel 2 exit /b 1
    echo.
) else (
    echo [OK] Running as Administrator.
)

REM -- Step 1: Check Python is available --
where python.exe >nul 2>&1
if errorlevel 1 (
    where py.exe >nul 2>&1
    if errorlevel 1 (
        echo [FAIL] Python not found on PATH.
        echo        Install Python 3.12 from https://www.python.org/downloads/
        echo        Tick "Add to PATH" during install, then re-run this script.
        pause
        exit /b 1
    )
    set "PYEXE=py -3"
) else (
    set "PYEXE=python"
)
echo [OK] Python found.

REM -- Step 2: Check .env exists --
if not exist "%REPO%\.env" (
    echo [FAIL] .env not found in %REPO%
    echo        Get the .env file from Titu and place it there first.
    pause
    exit /b 1
)
echo [OK] .env found.

REM -- Step 3: Create venv inside the repo folder --
if exist "%REPO%\.venv\Scripts\python.exe" (
    echo [OK] .venv already exists - skipping creation.
) else (
    echo [..] Creating virtual environment in .venv ...
    %PYEXE% -m venv "%REPO%\.venv"
    if errorlevel 1 (
        echo [FAIL] Could not create .venv
        pause
        exit /b 1
    )
    echo [OK] .venv created.
)

REM -- Step 4: Install recording deps into venv --
echo [..] Installing recording dependencies (this takes ~2 min first time) ...
"%REPO%\.venv\Scripts\pip" install --quiet -r "%REPO%\requirements-recorder.txt"
if errorlevel 1 (
    echo [FAIL] pip install failed. See output above.
    pause
    exit /b 1
)
echo [OK] Dependencies installed.

REM -- Step 5: Register voice daemon scheduled task --
echo [..] Registering voice daemon autostart ...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0register-voice-daemon-task.ps1"
if errorlevel 1 (
    echo [FAIL] Could not register scheduled task.
    pause
    exit /b 1
)

REM -- Step 6: Start daemon now (no need to log out) --
powershell -NoProfile -Command "Start-ScheduledTask -TaskName 'NAPCO Nucleus - Voice Daemon'" >nul 2>&1

REM -- Step 7: Save the share credential so File Explorer opens the central
REM    share with NO password prompt. Windows allows one identity per file
REM    server per PC; the recorder already authenticates as this user, so
REM    storing it here means browsing \\<server>\nucleus-central just works
REM    (and survives reboot). Reads user/pass/server from .env.
set "SMB_USER="
set "SMB_PASS="
set "SMB_UNC="
for /f "usebackq tokens=1,* delims==" %%A in ("%REPO%\.env") do (
    if /i "%%A"=="NUCLEUS_SAMBA_USER"     set "SMB_USER=%%B"
    if /i "%%A"=="NUCLEUS_SAMBA_PASSWORD" set "SMB_PASS=%%B"
    if /i "%%A"=="NUCLEUS_CENTRAL_PATH"   set "SMB_UNC=%%B"
)
set "SMB_SRV="
if defined SMB_UNC for /f "tokens=1 delims=\" %%H in ("%SMB_UNC%") do set "SMB_SRV=%%H"
if defined SMB_USER if defined SMB_PASS if defined SMB_SRV (
    cmdkey /add:%SMB_SRV% /user:%SMB_USER% /pass:%SMB_PASS% >nul 2>&1
    echo [OK] Saved share credential - browsing \\%SMB_SRV%\nucleus-central needs no password.
) else (
    echo [WARN] Could not read Samba creds from .env - skipping passwordless-browse setup.
)

REM -- Read NUCLEUS_DEV_NAME from .env so the verify path below is correct --
set "DEVNAME=YOUR_NAME"
for /f "tokens=2 delims==" %%A in ('findstr /b "NUCLEUS_DEV_NAME=" "%REPO%\.env"') do set "DEVNAME=%%A"

echo.
echo ================================================================
echo  Setup complete.
echo  Voice daemon is running. Teams calls will be mirrored to central.
echo.
echo  Verify after a test call:
echo    - Make a Teams call (at least 20 seconds)
echo    - Check: \\172.16.205.123\nucleus-central\%DEVNAME%\TODAY\calls\
echo    - You should see _mic.wav, _speaker.wav, .json
echo.
echo  Daemon log (to check if something is wrong):
echo    Get-Content "%REPO%\logs\voice_daemon.log" -Tail 50
echo ================================================================
echo.
pause
