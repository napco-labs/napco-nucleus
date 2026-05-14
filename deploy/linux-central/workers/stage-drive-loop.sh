#!/bin/bash
# Stage-drive loop -- mirrors the MVPACCESS 15-min Scheduled Task.
# Captures Google Drive content (incl. Drive audio via Groq) into central.

set -u
INTERVAL_SECONDS="${STAGE_DRIVE_INTERVAL_SECONDS:-900}"

trap 'echo "[stage-drive-loop] received SIGTERM, exiting"; exit 0' TERM INT

echo "[stage-drive-loop] starting -- interval=${INTERVAL_SECONDS}s, $(date -Iseconds)"

while true; do
    echo "[stage-drive-loop] tick $(date -Iseconds)"
    python -m tools.stage_drive
    rc=$?
    if [ $rc -ne 0 ]; then
        echo "[stage-drive-loop] tools.stage_drive exited rc=$rc (will retry next tick)"
    fi
    sleep "$INTERVAL_SECONDS" &
    wait $!
done
