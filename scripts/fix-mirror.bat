@echo off
REM ============================================================
REM  NAPCO Nucleus - one-click MIRROR fix (dev PC)
REM ============================================================
REM  Symptom this repairs: calls record locally but do NOT copy
REM  to central during/after the call (\\172.16.205.123\nucleus-
REM  central\<dev>\<date>\calls stays empty), so someone has to
REM  push them by hand.
REM
REM  Root cause it clears: a leftover GUEST session to the central
REM  host blocks the recorder's authenticated `net use /user:nucleus`
REM  with Windows error 1219 ("multiple connections to a server by
REM  the same user with different credentials are not allowed"), so
REM  every live-mirror tick fails silently. Common after anyone
REM  browsed \\172.16.205.123 in Explorer as guest.
REM
REM  What it does:
REM    1. drops ALL stale sessions + saved creds to the central host
REM    2. backfills every local call that never reached central
REM       (re-auths with the nucleus creds from .env; no secrets here)
REM
REM  Site-agnostic: reads NUCLEUS_* from .env. Just double-click it.
REM ============================================================

cd /d "%~dp0\.."
echo.
echo === Repo: %CD%
echo.

echo === [1/2] Dropping stale/guest sessions to central (clears error 1219)...
net use \\172.16.205.123\nucleus-central /delete /y >nul 2>&1
net use \\172.16.205.123\IPC$ /delete /y >nul 2>&1
cmdkey /delete:172.16.205.123 >nul 2>&1
echo     done.
echo.

echo === [2/2] Backfilling local calls that never mirrored...
echo     (preview first)
py -3 -m teams.backfill_central --dry-run
echo.
echo     (now copying anything missing)
py -3 -m teams.backfill_central

echo.
echo ============================================================
echo  DONE. Now make a short TEST CALL and, DURING the call, watch:
echo    \\172.16.205.123\nucleus-central\%USERNAME%\<today>\calls
echo  The *_mic.wav / *_speaker.wav should appear within ~30s and grow.
echo  (If %USERNAME% is not the right dev name, set NUCLEUS_DEV_NAME in .env.)
echo ============================================================
echo.
pause
