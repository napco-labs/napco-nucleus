#!/bin/bash
# Requirement pipeline + email — fires after call transcription completes.
#
# RULE: never send email without call transcript data.
# 90% of requirements come from calls. Email only fires when at least
# one call transcript exists for the current lookback window.
#
# Flow:
#   transcribe-loop.sh writes /data/nucleus-central/.pipeline_trigger
#   after transcribing >= 1 session. This loop polls every 2 minutes.
#   When trigger found:
#     1. Verify at least 1 call transcript exists — abort if none
#     2. Delete trigger
#     3. Run collect_central.py (collects transcripts + chat + email)
#     4. Send email (always — even if 0 requirements found, but only
#        when call data is present)

set -uo pipefail
LOOKBACK_MINUTES="${DAILY_DRAFT_LOOKBACK_MINUTES:-1440}"
POLL_SECONDS="${PIPELINE_POLL_SECONDS:-120}"
TRIGGER_FILE="/data/nucleus-central/.pipeline_trigger"
CENTRAL="/data/nucleus-central"

trap 'echo "[draft-loop] received SIGTERM, exiting"; exit 0' TERM INT

echo "[draft-loop] starting — polling every ${POLL_SECONDS}s for transcription trigger"

has_call_transcripts() {
    # Returns 0 (true) if at least 1 *_transcript.md exists in the last
    # LOOKBACK_MINUTES worth of call folders across all dev folders.
    local cutoff
    cutoff=$(date -d "-${LOOKBACK_MINUTES} minutes" +%s)
    while IFS= read -r f; do
        local mtime
        mtime=$(stat -c %Y "$f" 2>/dev/null || echo 0)
        if [ "$mtime" -ge "$cutoff" ]; then
            return 0
        fi
    done < <(find "$CENTRAL" -path "*/calls/*_transcript.md" 2>/dev/null)
    return 1
}

while true; do
    sleep "$POLL_SECONDS" &
    wait $!

    if [ ! -f "$TRIGGER_FILE" ]; then
        continue
    fi

    echo "[draft-loop] trigger detected at $(date -Iseconds)"

    if ! has_call_transcripts; then
        echo "[draft-loop] no call transcripts in last ${LOOKBACK_MINUTES} min — skipping pipeline. Will retry next trigger."
        rm -f "$TRIGGER_FILE"
        continue
    fi

    echo "[draft-loop] call transcripts confirmed — running pipeline"
    rm -f "$TRIGGER_FILE"

    python collect_central.py --client all --last-minutes "$LOOKBACK_MINUTES"
    rc=$?
    echo "[draft-loop] collect_central.py exited rc=$rc"

    if [ -n "${NUCLEUS_ROLLUP_TO:-}" ]; then
        echo "[draft-loop] sending email"
        python -m mail.daily_rollup
        echo "[draft-loop] email sent rc=$?"
    else
        echo "[draft-loop] NUCLEUS_ROLLUP_TO not set — skipping email"
    fi
done
