#!/bin/bash
# deploy.sh -- canonical deploy / redeploy on .123.
#
# Use this script ALWAYS instead of typing `docker compose up -d`
# manually. It eliminates the "partial recreate" failure class
# (one container picks up the new compose, others keep stale config
# and silently crash). The 2026-05-14 incident where transcribe /
# stage-email / stage-drive crashed for 4 hours because only
# daily-draft was recreated after the data-overlay mount change is
# exactly what this script prevents.
#
# Usage (on .123):
#   cd /home/ubuntu/napco-nucleus/deploy/linux-central
#   ./deploy.sh             # core stack only
#   ./deploy.sh --runner    # also include the GHA runner container
#
# What it does:
#   1. git pull on the repo
#   2. docker compose build (worker image rebuild if Dockerfile changed)
#   3. docker compose up -d --force-recreate (ALL services)
#   4. wait + ps + tail logs so you see whether anything failed to start

set -euo pipefail
cd "$(dirname "$0")"

PROFILE_ARGS=()
if [ "${1:-}" = "--runner" ]; then
    PROFILE_ARGS=(--profile runner)
fi

echo "[deploy] step 1/4 -- git pull"
git -C ../.. pull --ff-only

echo ""
echo "[deploy] step 2/4 -- docker compose build (worker image)"
docker compose "${PROFILE_ARGS[@]}" build

echo ""
echo "[deploy] step 3/4 -- recreate ALL services so no container is left on stale config"
docker compose "${PROFILE_ARGS[@]}" up -d --force-recreate

echo ""
echo "[deploy] step 4/4 -- wait + verify"
sleep 5
docker compose "${PROFILE_ARGS[@]}" ps
echo ""
echo "[deploy] recent logs (last 5 lines per service):"
for svc in samba transcribe stage-email stage-drive daily-draft gha-runner; do
    if docker compose "${PROFILE_ARGS[@]}" ps --services 2>/dev/null | grep -q "^${svc}$"; then
        echo "--- $svc ---"
        docker compose "${PROFILE_ARGS[@]}" logs --tail 5 "$svc" 2>&1 | sed 's/^/  /'
    fi
done

echo ""
echo "[deploy] done. Run ./status.sh anytime to re-check stack health."
