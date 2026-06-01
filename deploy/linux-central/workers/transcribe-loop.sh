#!/bin/bash
# Transcribe loop — runs every 2 minutes, processes new call sessions.
#
# After transcribing at least 1 session, writes a trigger file so the
# draft-loop fires the pipeline + email immediately instead of waiting
# for a fixed clock time.
#
# Backend: faster-whisper (primary). Use --groq flag for speed when needed.

set -u
INTERVAL_SECONDS="${TRANSCRIBE_INTERVAL_SECONDS:-120}"
TRIGGER_FILE="/data/nucleus-central/.pipeline_trigger"

trap 'echo "[transcribe-loop] received SIGTERM, exiting"; exit 0' TERM INT

echo "[transcribe-loop] starting — interval=${INTERVAL_SECONDS}s, $(date -Iseconds)"

while true; do
    echo "[transcribe-loop] tick $(date -Iseconds)"
    output=$(python -m tools.transcribe_calls 2>&1)
    rc=$?
    echo "$output"

    if [ $rc -ne 0 ]; then
        echo "[transcribe-loop] tools.transcribe_calls exited rc=$rc (will retry next tick)"
    else
        # Check if any sessions were actually transcribed this tick.
        # tools.transcribe_calls prints "done: groq=N fw=M failed=K" on success.
        transcribed=$(echo "$output" | grep -oP 'fw=\K[0-9]+' | awk '{s+=$1}END{print s+0}')
        if [ "${transcribed:-0}" -gt 0 ]; then
            echo "[transcribe-loop] transcribed $transcribed session(s) — writing pipeline trigger"
            touch "$TRIGGER_FILE"
        fi
    fi

    sleep "$INTERVAL_SECONDS" &
    wait $!
done
