#!/bin/bash
# Requirement pipeline + email — sends EXACTLY ONE rollup email per day,
# on the clock at DAILY_DRAFT_TARGET_TIME (default 23:30 BD = 11:30 PM).
#
# HARD RULE (set by Titu 2026-06-15): never send email except this single
# nightly run. The old per-call EVENT email (fired within 2 min of every
# transcription) is DISABLED — transcription still happens continuously,
# but its .pipeline_trigger no longer triggers an email. The nightly clock
# run collects the whole day (--last-minutes 1440) and sends one summary.
#
# Trigger paths:
#   1. EVENT:  transcribe-loop.sh still writes .pipeline_trigger after
#              transcribing. We CONSUME (delete) it so it doesn't pile up,
#              but we do NOT run the pipeline or send email on it.
#   2. CLOCK:  fires once per BD calendar day at DAILY_DRAFT_TARGET_TIME —
#              the only path that collects + emails. Always sends, even on
#              a 0-requirement day (one daily summary either way).

set -uo pipefail
LOOKBACK_MINUTES="${DAILY_DRAFT_LOOKBACK_MINUTES:-1440}"
POLL_SECONDS="${PIPELINE_POLL_SECONDS:-120}"
TRIGGER_FILE="/data/nucleus-central/.pipeline_trigger"
CENTRAL="/data/nucleus-central"
CLOCK_TARGET="${DAILY_DRAFT_TARGET_TIME:-23:30}"
LAST_CLOCK_RUN_DATE=""

trap 'echo "[draft-loop] received SIGTERM, exiting"; exit 0' TERM INT

echo "[draft-loop] starting — polling every ${POLL_SECONDS}s"
echo "[draft-loop] event email: DISABLED (per-call emails off)"
echo "[draft-loop] single daily send: ${CLOCK_TARGET} BD"

run_pipeline() {
    local reason="$1"
    local email_args="${2:-}"   # extra args for daily_rollup (e.g. --require-new)
    echo "[draft-loop] running pipeline — reason: ${reason}"
    rm -f "$TRIGGER_FILE"

    python collect_central.py --client all --last-minutes "$LOOKBACK_MINUTES"
    local rc=$?
    echo "[draft-loop] collect_central.py exited rc=${rc}"

    if [ -n "${NUCLEUS_ROLLUP_TO:-}" ]; then
        echo "[draft-loop] sending email ${email_args}"
        python -m mail.daily_rollup ${email_args}
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
        # The ONE daily send: collect the whole day + email, even on a
        # 0-requirement day. This is the only path that sends email.
        run_pipeline "clock:${CLOCK_TARGET}"
        continue
    fi

    # ── Event trigger — email DISABLED ────────────────────────────
    # transcribe-loop still writes .pipeline_trigger after each call. We
    # consume it so it doesn't pile up, but we do NOT collect or email —
    # all sending is deferred to the single nightly clock run above.
    # (Manual "send now" still works: run `python -m mail.daily_rollup`.)
    if [ -f "$TRIGGER_FILE" ]; then
        rm -f "$TRIGGER_FILE"
        echo "[draft-loop] transcription complete — email deferred to nightly ${CLOCK_TARGET} run"
    fi
done
