@echo off
REM ============================================================================
REM  NAPCO Nucleus - COMPLETE uninstall from a developer PC
REM
REM  Removes, in order:
REM    1. Running voice daemon + any Nucleus python/wscript processes
REM    2. ALL "NAPCO Nucleus - *" scheduled tasks (daemon + chat-push + watchdog)
REM    3. The GLOBAL Python packages Nucleus installed (this is the "global"
REM       install you are dropping in favour of a local .venv setup)
REM    4. The NN user environment variable
REM    5. (optional, prompted) the repo folder itself, which holds the
REM       secrets .env + google-credentials.json
REM
REM  HOW TO RUN:  right-click this file > "Run as administrator"
REM              (run it while logged in as the SAME user Nucleus was set up
REM               under -- on Rocky's PC that's Rocky).
REM ============================================================================
setlocal EnableDelayedExpansion

REM --- Repo location: use the NN env var if present, else Rocky's known path ---
if not defined NN set "NN=D:\POC Projects\napco-nucleus"

echo.
echo ============================================================
echo   NAPCO Nucleus - complete uninstall
echo   Repo folder: "%NN%"
echo ============================================================
echo.

REM --- 1) Stop the running daemon + related Nucleus processes -----------------
echo [1/5] Stopping Nucleus processes (voice daemon, chat push, vbs wrapper)...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'voice_daemon|start-daemon-hidden|napco-nucleus|teams\.push_chat|record_call' } | ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop; Write-Host ('      killed PID ' + $_.ProcessId) } catch {} }"

REM --- 2) Remove every "NAPCO Nucleus *" scheduled task ----------------------
echo [2/5] Removing scheduled tasks...
powershell -NoProfile -Command "$t = Get-ScheduledTask | Where-Object { $_.TaskName -like 'NAPCO Nucleus*' }; if (-not $t) { Write-Host '      (none found)' } else { $t | ForEach-Object { Write-Host ('      removing: ' + $_.TaskName); Unregister-ScheduledTask -TaskName $_.TaskName -Confirm:$false } }"

REM --- 3) Uninstall the GLOBAL Python packages -------------------------------
echo [3/5] Uninstalling global Python packages (requirements.txt)...
if exist "%NN%\requirements.txt" (
    python -m pip uninstall -y -r "%NN%\requirements.txt"
) else (
    echo       requirements.txt not found under "%NN%" - skipping.
)

REM --- 4) Remove the NN user environment variable ----------------------------
echo [4/5] Removing NN environment variable...
powershell -NoProfile -Command "[Environment]::SetEnvironmentVariable('NN', $null, 'User')"

REM --- 5) Optionally delete the repo folder (holds secrets) ------------------
echo [5/5] Repo folder holds secrets: .env + google-credentials.json
set /p DELREPO="      Delete \"%NN%\" completely now? [y/N] "
if /i "!DELREPO!"=="y" (
    if exist "%NN%" (
        rmdir /s /q "%NN%"
        echo       Deleted "%NN%".
    ) else (
        echo       Folder not found - nothing to delete.
    )
) else (
    echo       Kept the repo folder ^(re-usable for the new local setup^).
    echo       To wipe it later:  rmdir /s /q "%NN%"
)

echo.
echo ============================================================
echo   Uninstall complete.
echo   Verify nothing remains:
echo       schtasks /query ^| findstr /i "NAPCO Nucleus"
echo ============================================================
echo.
pause
