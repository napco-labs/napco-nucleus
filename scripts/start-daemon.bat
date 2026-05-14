@echo off
REM Launch the voice daemon. stdout/stderr go to logs\voice_daemon.log
REM (append mode -- preserves history across restarts).
REM
REM Tail live:    powershell -c "Get-Content logs\voice_daemon.log -Wait -Tail 50"
REM Stop:         stop-daemon.bat (or kill the python process)

cd /d "%~dp0\.."
if not exist "logs" mkdir "logs"

REM Force UTF-8 for stdout/stderr so Whisper transcripts containing
REM non-Latin characters (Arabic / Bangla / CJK / etc.) don't crash
REM print() on Windows' default cp1252 console encoding. Child
REM processes (record_call subprocess) inherit this env.
set PYTHONIOENCODING=utf-8

REM Separator + start marker so multiple runs in one file are easy to scan.
echo. >> "logs\voice_daemon.log"
echo ============================================================ >> "logs\voice_daemon.log"
echo [start-daemon.bat] %DATE% %TIME% -- launching voice_daemon >> "logs\voice_daemon.log"
echo ============================================================ >> "logs\voice_daemon.log"

REM Enable delayed expansion so `!ERRORLEVEL!` inside the if-block below
REM reflects the exit code of the just-finished python invocation -- with
REM `%ERRORLEVEL%` cmd would expand at parse time of the whole `(...)`
REM block, capturing a stale value (typically 0) and reporting "OK" to
REM Task Scheduler even when the daemon crashed.
setlocal enabledelayedexpansion

if not exist ".venv\Scripts\python.exe" (
    REM No venv on this machine - fall back to system python or, failing
    REM that, the Python Launcher. Fresh devs often have only py.exe on
    REM PATH, not bare python.exe.
    where python.exe >nul 2>&1
    if errorlevel 1 (
        py -3 -u -m teams.voice_daemon >> "logs\voice_daemon.log" 2>&1
    ) else (
        python -u -m teams.voice_daemon >> "logs\voice_daemon.log" 2>&1
    )
    echo [start-daemon.bat] %DATE% %TIME% -- voice_daemon exited rc=!ERRORLEVEL! >> "logs\voice_daemon.log"
    exit /b !ERRORLEVEL!
)
call ".venv\Scripts\activate.bat"
python -u -m teams.voice_daemon >> "logs\voice_daemon.log" 2>&1
echo [start-daemon.bat] %DATE% %TIME% -- voice_daemon exited rc=!ERRORLEVEL! >> "logs\voice_daemon.log"
exit /b !ERRORLEVEL!
