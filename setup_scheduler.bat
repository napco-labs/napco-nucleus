@echo off
REM Registers the AI Agent nightly run with Windows Task Scheduler.
REM Runs once as Administrator. Scheduled time is LOCAL time — make sure your
REM Windows clock is set to Bangladesh (UTC+6) so 01:00 local = 01:00 BD time.

schtasks /create ^
  /tn "MVP Access AI Agent - Daily" ^
  /tr "\"%~dp0nightly.bat\"" ^
  /sc daily ^
  /st 01:00 ^
  /rl HIGHEST ^
  /f

echo.
echo Task "MVP Access AI Agent - Daily" created successfully.
echo It will run nightly.bat every day at 01:00 local time.
echo.
echo To verify:  schtasks /query /tn "MVP Access AI Agent - Daily"
echo To delete:  schtasks /delete /tn "MVP Access AI Agent - Daily" /f
echo To run now: schtasks /run /tn "MVP Access AI Agent - Daily"
pause
