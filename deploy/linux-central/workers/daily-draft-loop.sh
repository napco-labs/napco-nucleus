#!/bin/bash
# Requirement pipeline + email — fires after transcription completes.
#
# Flow:
#   transcribe-loop.sh writes /data/nucleus-central/.pipeline_trigger
#   after transcribing at least 1 session. This loop polls every 2 minutes
#   for that trigger file. When found:
#     1. Delete the trigger (so we don't re-fire for the same batch)
#     2. Run collect_central.py — extract requirements from transcripts
#     3. Send email (always — even if 0 requirements found)
#
# No fixed clock time. Email arrives minutes after the call is transcribed.

set -uo pipefail
LOOKBACK_MINUTES="${DAILY_DRAFT_LOOKBACK_MINUTES:-1440}"
POLL_SECONDS="${PIPELINE_POLL_SECONDS:-120}"
TRIGGER_FILE="/data/nucleus-central/.pipeline_trigger"

trap 'echo "[draft-loop] received SIGTERM, exiting"; exit 0' TERM INT

echo "[draft-loop] starting — polling every ${POLL_SECONDS}s for transcription trigger"

while true; do
    sleep "$POLL_SECONDS" &
    wait $!

    if [ ! -f "$TRIGGER_FILE" ]; then
        continue
    fi

    echo "[draft-loop] trigger detected at $(date -Iseconds) — running pipeline"
    rm -f "$TRIGGER_FILE"

    python collect_central.py --client all --last-minutes "$LOOKBACK_MINUTES"
    rc=$?
    echo "[draft-loop] collect_central.py exited rc=$rc"

    if [ -n "${NUCLEUS_ROLLUP_TO:-}" ]; then
        echo "[draft-loop] sending email (rc=$rc)"
        python -m mail.daily_rollup
        echo "[draft-loop] email sent rc=$?"
    else
        echo "[draft-loop] NUCLEUS_ROLLUP_TO not set — skipping email"
    fi
done
