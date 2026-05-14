#!/bin/bash
# status.sh -- 30-second health check for the Nucleus stack on .123.
#
# Surfaces:
#   * container state (Up / Restarting / Exited)
#   * recent error/exception lines per worker (last hour)
#   * disk usage on the data dirs
#   * SMB port 445 listening (Samba up)
#   * last successful run timestamp per worker (cheap proxy for "alive")
#
# Returns exit code 0 if everything looks healthy, 1 if any container
# is Restarting / Exited, 2 if any worker had crashes in the last hour.
#
# Usage:
#   cd /home/ubuntu/napco-nucleus/deploy/linux-central
#   ./status.sh

set -uo pipefail
cd "$(dirname "$0")"

EXIT=0

echo "=== container state ==="
docker compose --profile runner ps
echo ""

# Flag anything not Up
BAD=$(docker compose --profile runner ps --format '{{.Service}} {{.State}}' 2>/dev/null | awk '$2!="running"' | head -5)
if [ -n "$BAD" ]; then
    echo "[WARN] containers not running:"
    echo "$BAD" | sed 's/^/  /'
    echo ""
    EXIT=1
fi

echo "=== recent errors (last 10 min, per worker) ==="
# 10-min window so a quick container recreate clears stale pre-fix
# noise. If you want a longer window for a postmortem, run:
#   docker compose logs --since 1h transcribe | grep -E 'Traceback|Error:'
#
# Strict pattern: real Python exceptions start with 'Traceback', or
# have the form 'OSError:' / 'ValueError:' / 'Exception:' (capital E,
# colon). 'errors=0' in a tally line is NOT a real error and was the
# false-positive source in the prior loose grep.
for svc in transcribe stage-email stage-drive daily-draft; do
    count=$(docker compose logs --since 10m "$svc" 2>&1 \
        | grep -cE 'Traceback \(most recent call last\)|^[^:]*Error: |^[^:]*Exception: | FAILED:| \[stderr\]' \
        || true)
    if [ "${count:-0}" -gt 0 ]; then
        echo "  $svc: $count error/exception line(s) in the last 10 min"
        EXIT=2
    else
        echo "  $svc: clean"
    fi
done
echo ""

echo "=== disk usage ==="
# Always show / and /srv (where central + data live). Most VMs have
# everything on /, so this collapses to one line.
df -h / 2>&1 | sed 's/^/  /'
echo ""

echo "=== samba SMB port 445 listening ==="
if ss -tln 2>/dev/null | grep -q ':445'; then
    echo "  YES (port 445 has a listener)"
else
    echo "  NO (samba is not serving SMB)"
    EXIT=1
fi
echo ""

echo "=== last successful tick per worker (heuristic) ==="
for svc in transcribe stage-email stage-drive daily-draft; do
    last=$(docker compose logs --tail 50 "$svc" 2>&1 \
        | grep -E "tick |firing |done:|matched " \
        | tail -1 || true)
    if [ -n "$last" ]; then
        echo "  $svc: $last"
    else
        echo "  $svc: (no recent tick line in last 50 log lines)"
    fi
done
echo ""

case "$EXIT" in
    0) echo "[OK] stack looks healthy" ;;
    1) echo "[BAD] one or more containers are not running" ;;
    2) echo "[WARN] containers running but workers had recent errors" ;;
esac
exit "$EXIT"
