#!/bin/bash
# Requirement pipeline + email — fires after call transcription completes,
# OR at DAILY_DRAFT_TARGET_TIME as a catch-all even if no trigger arrived.
#
# Two trigger paths:
#   1. EVENT:  transcribe-loop.sh writes .pipeline_trigger after transcribing
#              >= 1 session. Fires within 2 min of transcription completing.
#   2. CLOCK:  fires once per BD calendar day at DAILY_DRAFT_TARGET_TIME
#              (default 00:05) — always runs regardless of whether there
#              are call transcripts (sends a daily summary either way).

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
        echo "[draft-loop] clock trigger at ${current_hm} BD (target ${CLOCK_TARGET})"
        run_pipeline "clock:${CLOCK_TARGET}"
        continue
    fi

    # ── Event-based trigger ───────────────────────────────────────
    if [ ! -f "$TRIGGER_FILE" ]; then
        continue
    fi

    echo "[draft-loop] event trigger detected at $(date -Iseconds)"
    run_pipeline "event:transcription-complete"
done
