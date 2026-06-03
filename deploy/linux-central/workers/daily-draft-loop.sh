#!/bin/bash
# Requirement pipeline + email — fires after call transcription completes,
# OR at DAILY_DRAFT_TARGET_TIME as a catch-all even if no trigger arrived.
#
# RULE: never send email without call transcript data.
# 90% of requirements come from calls. Email only fires when at least
# one call transcript exists for the current lookback window.
#
# Two trigger paths:
#   1. EVENT:  transcribe-loop.sh writes .pipeline_trigger after transcribing
#              >= 1 session. Fires within 2 min of transcription completing.
#   2. CLOCK:  fires once per BD calendar day at DAILY_DRAFT_TARGET_TIME
#              (default 00:05) as a safety catch-all — ensures the pipeline
#              runs even if the event trigger was missed (e.g. transcribe
#              container was down all day and recovered late).
#              Requires call transcripts to exist (same rule as event path).

set -uo pipefail
LOOKBACK_MINUTES="${DAILY_DRAFT_LOOKBACK_MINUTES:-1440}"
POLL_SECONDS="${PIPELINE_POLL_SECONDS:-120}"
TRIGGER_FILE="/data/nucleus-central/.pipeline_trigger"
CENTRAL="/data/nucleus-central"
CLOCK_TARGET="${DAILY_DRAFT_TARGET_TIME:-00:05}"
LAST_CLOCK_RUN_DATE=""

trap 'echo "[draft-loop] received SIGTERM, exiting"; exit 0' TERM INT

echo "[draft-loop] starting — polling every ${POLL_SECONDS}s"
echo "[draft-loop] event trigger: ${TRIGGER_FILE}"
echo "[draft-loop] clock catch-all: ${CLOCK_TARGET} BD daily"

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

run_pipeline() {
    local reason="$1"
    echo "[draft-loop] running pipeline — reason: ${reason}"
    rm -f "$TRIGGER_FILE"

    python collect_central.py --client all --last-minutes "$LOOKBACK_MINUTES"
    local rc=$?
    echo "[draft-loop] collect_central.py exited rc=${rc}"

    if [ -n "${NUCLEUS_ROLLUP_TO:-}" ]; then
        echo "[draft-loop] sending email"
        python -m mail.daily_rollup
        echo "[draft-loop] email rc=$?"
    else
        echo "[draft-loop] NUCLEUS_ROLLUP_TO not set — skipping email"
    fi
}

while true; do
    sleep "$POLL_SECONDS" &
    wait $!

    # ── Clock-based catch-all ─────────────────────────────────────
    # Fires once per day at CLOCK_TARGET even if no event trigger arrived.
    today=$(date +%Y-%m-%d)
    current_hm=$(date +%H:%M)
    if [[ "$current_hm" > "$CLOCK_TARGET" || "$current_hm" == "$CLOCK_TARGET" ]] \
       && [[ "$LAST_CLOCK_RUN_DATE" != "$today" ]]; then
        LAST_CLOCK_RUN_DATE="$today"
        if has_call_transcripts; then
            echo "[draft-loop] clock trigger at ${current_hm} BD (target ${CLOCK_TARGET})"
            run_pipeline "clock:${CLOCK_TARGET}"
        else
            echo "[draft-loop] clock trigger at ${current_hm} — no transcripts in lookback window, skipping."
        fi
        continue
    fi

    # ── Event-based trigger ───────────────────────────────────────
    if [ ! -f "$TRIGGER_FILE" ]; then
        continue
    fi

    echo "[draft-loop] event trigger detected at $(date -Iseconds)"

    if ! has_call_transcripts; then
        echo "[draft-loop] no call transcripts in last ${LOOKBACK_MINUTES} min — skipping pipeline."
        rm -f "$TRIGGER_FILE"
        continue
    fi

    run_pipeline "event:transcription-complete"
done
