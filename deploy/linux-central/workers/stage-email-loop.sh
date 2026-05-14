#!/bin/bash
# Stage-email loop -- mirrors the MVPACCESS 15-min Scheduled Task.
# Captures Gmail content into central. One-shot tool, periodically invoked.

set -u
INTERVAL_SECONDS="${STAGE_EMAIL_INTERVAL_SECONDS:-900}"

trap 'echo "[stage-email-loop] received SIGTERM, exiting"; exit 0' TERM INT

echo "[stage-email-loop] starting -- interval=${INTERVAL_SECONDS}s, $(date -Iseconds)"

while true; do
    echo "[stage-email-loop] tick $(date -Iseconds)"
    python -m tools.stage_email
    rc=$?
    if [ $rc -ne 0 ]; then
        echo "[stage-email-loop] tools.stage_email exited rc=$rc (will retry next tick)"
    fi
    sleep "$INTERVAL_SECONDS" &
    wait $!
done
