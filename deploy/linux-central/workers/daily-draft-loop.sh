#!/bin/bash
# Daily Requirement Management draft -- mirrors the MVPACCESS daily
# 23:45 BD Scheduled Task. Runs do_it_now.py for all clients over
# the last 24h. Container TZ=Asia/Dhaka so `date` already speaks BD.
#
# Implementation: simple sleep-until-target loop. Cheap and obvious;
# no cron daemon needed inside the container.

set -u
TARGET_TIME="${DAILY_DRAFT_TARGET_TIME:-23:45}"
LOOKBACK_MINUTES="${DAILY_DRAFT_LOOKBACK_MINUTES:-1440}"

trap 'echo "[daily-draft-loop] received SIGTERM, exiting"; exit 0' TERM INT

echo "[daily-draft-loop] starting -- target ${TARGET_TIME} BD, $(date -Iseconds)"

while true; do
    now_epoch=$(date +%s)
    target_epoch=$(date -d "today ${TARGET_TIME}" +%s)
    if [ "$now_epoch" -ge "$target_epoch" ]; then
        # Already past today's window -- aim for tomorrow.
        target_epoch=$(date -d "tomorrow ${TARGET_TIME}" +%s)
    fi
    sleep_for=$((target_epoch - now_epoch))
    echo "[daily-draft-loop] next fire in ${sleep_for}s ($(date -d "@${target_epoch}" -Iseconds))"
    sleep "$sleep_for" &
    wait $!

    echo "[daily-draft-loop] firing $(date -Iseconds)"
    python do_it_now.py --client all --last-minutes "$LOOKBACK_MINUTES"
    rc=$?
    echo "[daily-draft-loop] do_it_now.py exited rc=$rc"

    # Sleep past the target by 60s so the next iteration's
    # "today $TIME" doesn't re-fire immediately.
    sleep 60 &
    wait $!
done
