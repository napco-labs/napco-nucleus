#!/bin/bash
# Stage-drive loop -- mirrors the MVPACCESS 15-min Scheduled Task.
# Captures Google Drive content (incl. Drive audio via Groq) into central.

set -u
INTERVAL_SECONDS="${STAGE_DRIVE_INTERVAL_SECONDS:-900}"

trap 'echo "[stage-drive-loop] received SIGTERM, exiting"; exit 0' TERM INT

echo "[stage-drive-loop] starting -- interval=${INTERVAL_SECONDS}s, $(date -Iseconds)"

while true; do
    echo "[stage-drive-loop] tick $(date -Iseconds)"

    # Off-network dev bridge: mirror raw call/chat artifacts that off-LAN
    # devs (e.g. Assad) drop into the NN-Offnet Google Drive folder down
    # into central, so the normal transcribe + collect pipeline picks them
    # up identically to on-LAN SMB devs. No-op unless NN_OFFNET_FOLDER_ID
    # is set in .env. Failures are non-fatal -- retried next tick.
    if [ -n "${NN_OFFNET_FOLDER_ID:-}" ]; then
        python -m drive.offnet_sync \
            || echo "[stage-drive-loop] drive.offnet_sync failed (will retry next tick)"
    fi

    python -m tools.stage_drive
    rc=$?
    if [ $rc -ne 0 ]; then
        echo "[stage-drive-loop] tools.stage_drive exited rc=$rc (will retry next tick)"
    fi
    sleep "$INTERVAL_SECONDS" &
    wait $!
done
