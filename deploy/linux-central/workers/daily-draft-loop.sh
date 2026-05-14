#!/bin/bash
# Daily Requirement Management draft -- mirrors the MVPACCESS daily
# 23:45 BD Scheduled Task.
#
# IMPORTANT: this runs collect_central.py directly, NOT do_it_now.py.
# do_it_now.py is the dev-side wrapper that SSHes to the agent host
# (MVPACCESS) to run collect_central.py remotely. Since we ARE the
# agent host now, we skip the SSH hop and call the workhorse directly.
#
# Container TZ=Asia/Dhaka so `date` already speaks BD.
# No cron daemon -- simple sleep-until-target loop.

set -uo pipefail
TARGET_TIME="${DAILY_DRAFT_TARGET_TIME:-23:45}"
LOOKBACK_MINUTES="${DAILY_DRAFT_LOOKBACK_MINUTES:-1440}"

# Guard against malformed env overrides. `date -d "today <bad>"` returns
# empty + nonzero; `sleep ""` then errors and the loop would spin.
if ! date -d "today ${TARGET_TIME}" +%s >/dev/null 2>&1; then
    echo "[daily-draft-loop] FATAL: DAILY_DRAFT_TARGET_TIME='${TARGET_TIME}' is not parseable by GNU date. Aborting." >&2
    exit 2
fi
if ! [[ "$LOOKBACK_MINUTES" =~ ^[0-9]+$ ]]; then
    echo "[daily-draft-loop] FATAL: DAILY_DRAFT_LOOKBACK_MINUTES='${LOOKBACK_MINUTES}' is not an integer. Aborting." >&2
    exit 2
fi

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
    python collect_central.py --client all --last-minutes "$LOOKBACK_MINUTES"
    rc=$?
    echo "[daily-draft-loop] collect_central.py exited rc=$rc"

    # Sleep past the target by 60s so the next iteration's
    # "today $TIME" doesn't re-fire immediately.
    sleep 60 &
    wait $!
done
