@echo off
REM setup-central.bat
REM
REM Double-click on a dev PC to give it access to the NN central share and
REM restart the recorder. You type only the dev name and the Napco share
REM password (masked); it handles .env, the Windows credential, the daemon
REM restart, the backlog push, and the healthcheck.
REM
REM Optional: pass the dev name as an argument, e.g.  setup-central.bat Atik
REM
REM Run as administrator if the daemon-restart step reports it can't stop or
REM start the scheduled task.

powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0setup-central.ps1" %*

echo.
echo ============================================================
echo  Setup finished. Review the output above (especially the
echo  [4/6] share check and the healthcheck smb-share line).
echo ============================================================
pause
