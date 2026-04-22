@echo off
REM Registers the Morning Brief with Windows Task Scheduler.
REM Runs once as Administrator. Scheduled time is LOCAL — adjust /st if
REM you're on a different timezone. Default 08:30 local = morning standup-ish.

schtasks /create ^
  /tn "MVP Access AI Agent - Morning Brief" ^
  /tr "\"%~dp0morning_brief.bat\"" ^
  /sc daily ^
  /st 08:30 ^
  /rl HIGHEST ^
  /f

echo.
echo Task "MVP Access AI Agent - Morning Brief" created successfully.
echo It will run morning_brief.bat every day at 08:30 local time.
echo.
echo Set MORNING_BRIEF_TO in MVP-Access-API-Test\.env to restrict the brief
echo to a specific audience (e.g. just you).
echo.
echo To verify:  schtasks /query /tn "MVP Access AI Agent - Morning Brief"
echo To delete:  schtasks /delete /tn "MVP Access AI Agent - Morning Brief" /f
echo To run now: schtasks /run /tn "MVP Access AI Agent - Morning Brief"
echo Dry-run :   set MORNING_BRIEF_DRY_RUN=1 ^&^& python morning_brief.py
pause
