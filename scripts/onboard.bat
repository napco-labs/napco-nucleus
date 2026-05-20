@echo off
setlocal enabledelayedexpansion

echo.
echo ============================================================
echo   NAPCO Nucleus - One-Click Setup
echo ============================================================
echo.

REM ── Install location ─────────────────────────────────────────
set "NN=E:\Projects\NAPCO-Nucleus"
echo Repo will be cloned to: %NN%
echo Press Enter to keep this path, or type a new path:
set /p "CUSTOM=>> "
if not "!CUSTOM!"=="" set "NN=!CUSTOM!"
echo.

REM ── Step 1: Git ───────────────────────────────────────────────
echo [1/7] Git...
where git >nul 2>&1
if %errorlevel%==0 (
    echo       Already installed. Skipping.
) else (
    winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements
    if errorlevel 1 ( echo ERROR: Git install failed. & pause & exit /b 1 )
)

REM ── Step 2: Python ───────────────────────────────────────────
echo [2/7] Python 3.12...
where python >nul 2>&1
if %errorlevel%==0 (
    echo       Already installed. Skipping.
) else (
    winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements
    if errorlevel 1 ( echo ERROR: Python install failed. & pause & exit /b 1 )
)

REM Refresh PATH from registry so git/python are visible in this session
for /f "tokens=2*" %%a in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do set "SYS_PATH=%%b"
for /f "tokens=2*" %%a in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "USR_PATH=%%b"
if defined USR_PATH ( set "PATH=!SYS_PATH!;!USR_PATH!" ) else ( set "PATH=!SYS_PATH!" )

REM ── Step 3: Clone ────────────────────────────────────────────
echo [3/7] Cloning repo to %NN%...
if exist "%NN%\.git" (
    echo       Repo already exists. Skipping clone.
) else (
    mkdir "%NN%" 2>nul
    "C:\Program Files\Git\cmd\git.exe" clone https://github.com/napco-labs/napco-nucleus.git "%NN%"
    if errorlevel 1 ( echo ERROR: git clone failed. Check internet/VPN. & pause & exit /b 1 )
)
setx NN "%NN%" >nul
echo       NN saved as user environment variable.

REM ── Step 4: .env + google-credentials.json ───────────────────
echo [4/7] Placing .env and google-credentials.json...

if exist "%~dp0.env" (
    copy /Y "%~dp0.env" "%NN%\.env" >nul
    echo       .env copied.
) else (
    echo.
    echo       ACTION REQUIRED: Copy .env into %NN%
    echo       Press any key when done...
    pause >nul
)

if exist "%~dp0google-credentials.json" (
    copy /Y "%~dp0google-credentials.json" "%NN%\google-credentials.json" >nul
    echo       google-credentials.json copied.
) else (
    echo.
    echo       ACTION REQUIRED: Copy google-credentials.json into %NN%
    echo       Press any key when done...
    pause >nul
)

echo.
echo       Enter your dev name (Assad / Rocky / Ferdows / Titu / Atik / Isruk / Amin):
set /p "DEV_NAME=>> "
powershell -NoProfile -Command "(Get-Content '%NN%\.env') -replace 'NUCLEUS_DEV_NAME=.*', 'NUCLEUS_DEV_NAME=%DEV_NAME%' | Set-Content '%NN%\.env'"
echo       NUCLEUS_DEV_NAME set to %DEV_NAME%.

REM ── Step 5: pip install ───────────────────────────────────────
echo [5/7] Installing Python packages...
python -m pip install -r "%NN%\requirements.txt"
if errorlevel 1 ( echo ERROR: pip install failed. & pause & exit /b 1 )

REM ── Step 6: Voice daemon ─────────────────────────────────────
echo [6/7] Installing voice daemon...
powershell -NoProfile -ExecutionPolicy Bypass -File "%NN%\scripts\register-voice-daemon-task.ps1"
if errorlevel 1 ( echo ERROR: Voice daemon registration failed. & pause & exit /b 1 )
powershell -NoProfile -Command "Start-ScheduledTask -TaskName 'NAPCO Nucleus - Voice Daemon'" >nul 2>&1

REM ── Step 7: Chat-push tasks ───────────────────────────────────
echo [7/7] Installing chat-push tasks...
powershell -NoProfile -ExecutionPolicy Bypass -File "%NN%\scripts\register-chat-push-task.ps1"
if errorlevel 1 ( echo ERROR: Chat-push registration failed. & pause & exit /b 1 )

echo.
echo ============================================================
echo   Setup complete! Tell Titu you are done.
echo ============================================================
echo.
pause
