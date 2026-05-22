#!/bin/bash
# Refresh the self-hosted GitHub Actions runner on .123.
#
# The runner uses a one-shot RUNNER_TOKEN that expires in ~1h. When
# the runner falls into a restart loop with HTTP 404 on
# "POST /actions/runner-registration", that's the symptom -- token
# is gone, run this script.
#
# Usage:
#   On .123:  bash scripts/refresh-gha-runner.sh
#   Locally:  ssh ubuntu@172.16.205.123 'cd /home/ubuntu/napco-nucleus && bash scripts/refresh-gha-runner.sh'
#
# Prereq: `gh auth login` once on .123 with a token that has admin:org
# on napco-labs (one-time setup; gh caches the credential).
# Without gh, you can paste a manually-fetched token via REGISTRATION_TOKEN env.

set -euo pipefail

DEPLOY_DIR="/home/ubuntu/napco-nucleus/deploy/linux-central"
ORG="${GHA_RUNNER_ORG:-napco-labs}"

if [ -n "${REGISTRATION_TOKEN:-}" ]; then
    TOKEN="$REGISTRATION_TOKEN"
    echo "[refresh-gha-runner] using REGISTRATION_TOKEN from env"
elif command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
    echo "[refresh-gha-runner] fetching fresh registration token via gh for org=$ORG"
    TOKEN=$(gh api -X POST "/orgs/$ORG/actions/runners/registration-token" --jq .token)
else
    cat <<EOF
[refresh-gha-runner] no token source available.

Either:
  (a) Run 'gh auth login' once (use a PAT with admin:org on $ORG), then re-run this script.
  (b) Fetch a token manually:
        https://github.com/organizations/$ORG/settings/actions/runners
        -> "New self-hosted runner" -> copy the token from the config command
      Then re-run:
        REGISTRATION_TOKEN=<paste> bash scripts/refresh-gha-runner.sh

EOF
    exit 1
fi

if [ -z "${TOKEN:-}" ]; then
    echo "[refresh-gha-runner] token fetch returned empty" >&2
    exit 1
fi

cd "$DEPLOY_DIR"

# Backup .env, replace GHA_RUNNER_TOKEN line (or append if missing).
sudo cp .env ".env.bak.$(date +%Y%m%d-%H%M%S)"
if grep -q "^GHA_RUNNER_TOKEN=" .env; then
    sudo sed -i "s|^GHA_RUNNER_TOKEN=.*|GHA_RUNNER_TOKEN=$TOKEN|" .env
else
    echo "GHA_RUNNER_TOKEN=$TOKEN" | sudo tee -a .env >/dev/null
fi

echo "[refresh-gha-runner] .env updated; recreating runner container"
docker compose --profile runner up -d --force-recreate gha-runner

echo "[refresh-gha-runner] tailing runner logs for 15s to confirm registration"
timeout 15 docker logs -f nucleus-gha-runner 2>&1 | head -40 || true

echo "[refresh-gha-runner] done. Check status:"
echo "  docker ps --filter name=nucleus-gha-runner --format '{{.Status}}'"
echo "  https://github.com/organizations/$ORG/settings/actions/runners"
