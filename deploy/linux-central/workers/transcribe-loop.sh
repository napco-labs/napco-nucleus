#!/bin/bash
# Transcribe loop -- mirrors the MVPACCESS 2-min Scheduled Task.
#
# Walks /data/nucleus-central/*/<date>/calls/ for completed sessions
# (signal: <session>.json present + <session>_transcript.md missing)
# and transcribes them in place.
#
# Backend selection happens inside tools.transcribe_calls:
#   - Primary: Groq API (whisper-large-v3 on GPU, free tier)
#   - Fallback: faster-whisper int8 local (lazy-loaded only on failure)

set -u
INTERVAL_SECONDS="${TRANSCRIBE_INTERVAL_SECONDS:-120}"

# Clean exit on SIGTERM so `docker stop` doesn't take 10s.
trap 'echo "[transcribe-loop] received SIGTERM, exiting"; exit 0' TERM INT

echo "[transcribe-loop] starting -- interval=${INTERVAL_SECONDS}s, $(date -Iseconds)"

while true; do
    echo "[transcribe-loop] tick $(date -Iseconds)"
    python -m tools.transcribe_calls
    rc=$?
    if [ $rc -ne 0 ]; then
        echo "[transcribe-loop] tools.transcribe_calls exited rc=$rc (will retry next tick)"
    fi
    sleep "$INTERVAL_SECONDS" &
    wait $!
done
