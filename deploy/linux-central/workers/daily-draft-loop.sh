#!/bin/bash
# Requirement pipeline + email — PER-CALL (event) emails.
#
# BEHAVIOR (set by Titu 2026-06-23, replacing the single-nightly rule):
# send a requirement email as soon as a call is processed, containing ONLY
# the new requirements from it. As each dev (Assad / Rocky / Atik / …)
# finishes a call, that call flows transcribe -> collect -> email on its own.
#
# Trigger paths:
#   1. EVENT (default ON): transcribe-loop.sh writes .pipeline_trigger after
#      transcribing a call. We collect the recent window and send a rollup of
#      ONLY new requirements (--require-new skips the send when the call
#      surfaced nothing new). Disable with DAILY_DRAFT_EVENT_EMAIL=0.
#   2. CLOCK (default OFF): a single daily send at DAILY_DRAFT_TARGET_TIME.
#      Only runs if that env is set (e.g. "23:30"); otherwise there is no
#      nightly batch — sending is purely per-call.

set -uo pipefail
# Recent window per event run; dedup + --require-new mean a generous lookback
# is safe (already-seen requirements are never re-sent).
LOOKBACK_MINUTES="${DAILY_DRAFT_LOOKBACK_MINUTES:-360}"
POLL_SECONDS="${PIPELINE_POLL_SECONDS:-120}"
TRIGGER_FILE="/data/nucleus-central/.pipeline_trigger"
CENTRAL="/data/nucleus-central"
EVENT_EMAIL="${DAILY_DRAFT_EVENT_EMAIL:-1}"   # 0 disables per-call emails
# The nightly batch is OFF unless explicitly enabled — independent of any
# DAILY_DRAFT_TARGET_TIME still set in the infra env. Set DAILY_DRAFT_CLOCK=1
# to bring back the single daily send.
CLOCK_ENABLED="${DAILY_DRAFT_CLOCK:-0}"
CLOCK_TARGET="${DAILY_DRAFT_TARGET_TIME:-23:30}"
LAST_CLOCK_RUN_DATE=""

trap 'echo "[draft-loop] received SIGTERM, exiting"; exit 0' TERM INT

echo "[draft-loop] starting — polling every ${POLL_SECONDS}s"
if [ "$EVENT_EMAIL" != 0 ]; then
    echo "[draft-loop] per-call event email: ENABLED (lookback ${LOOKBACK_MINUTES}m, new requirements only)"
else
    echo "[draft-loop] per-call event email: disabled"
fi
if [ "$CLOCK_ENABLED" = 1 ]; then
    echo "[draft-loop] daily clock send: ${CLOCK_TARGET}"
else
    echo "[draft-loop] daily clock send: OFF"
fi

run_pipeline() {
    local reason="$1"
    local email_args="${2:-}"     # extra args for daily_rollup (e.g. --require-new)
    local collect_args="${3:-}"   # extra args for collect_central (e.g. --calls-within-minutes)
    echo "[draft-loop] running pipeline — reason: ${reason}"
    rm -f "$TRIGGER_FILE"

    python collect_central.py --client all --last-minutes "$LOOKBACK_MINUTES" ${collect_args}
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

    # ── Clock send (opt-in) ───────────────────────────────────────
    # Only when DAILY_DRAFT_TARGET_TIME is set. Off by default now that email
    # is per-call. When on, fires once per BD day and always sends a summary.
    today=$(date +%Y-%m-%d)
    current_hm=$(date +%H:%M)
    if [ "$CLOCK_ENABLED" = 1 ] && [ -n "$CLOCK_TARGET" ] \
       && [[ "$current_hm" > "$CLOCK_TARGET" || "$current_hm" == "$CLOCK_TARGET" ]] \
       && [[ "$LAST_CLOCK_RUN_DATE" != "$today" ]]; then
        LAST_CLOCK_RUN_DATE="$today"
        echo "[draft-loop] clock trigger at ${current_hm} BD (target ${CLOCK_TARGET})"
        run_pipeline "clock:${CLOCK_TARGET}"
        continue
    fi

    # ── Event trigger — per-call email ────────────────────────────
    # A finished call's transcription writes .pipeline_trigger; collect the
    # recent window and email a rollup of ONLY new requirements. --require-new
    # means a call that surfaced nothing new sends no email.
    if [ -f "$TRIGGER_FILE" ]; then
        if [ "$EVENT_EMAIL" != 0 ]; then
            # Scope to the just-finished call (transcript mtime < 45 min) so we
            # don't re-transcribe the whole day's calls on every trigger.
            run_pipeline "event:transcription" "--require-new" "--calls-within-minutes ${DAILY_DRAFT_EVENT_CALLS_WITHIN:-45}"
        else
            rm -f "$TRIGGER_FILE"
            echo "[draft-loop] transcription complete — per-call email disabled"
        fi
    fi
done
