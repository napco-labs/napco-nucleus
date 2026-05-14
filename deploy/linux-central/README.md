# NAPCO Nucleus -- Linux central host deployment

The Linux replacement for the `.209` Windows agent host. Runs as a
docker-compose stack on `172.16.205.123` alongside the existing
OpenProject workload.

## What this stack does

| Container | Cadence | Replaces on .209 |
|---|---|---|
| `nucleus-samba` | always-on | `\\172.16.205.209\nucleus-central\` SMB share |
| `nucleus-transcribe` | every 2 min | Scheduled Task "NAPCO Nucleus - Transcribe Calls" |
| `nucleus-stage-email` | every 15 min | Scheduled Task "NAPCO Nucleus - Stage Email" |
| `nucleus-stage-drive` | every 15 min | Scheduled Task "NAPCO Nucleus - Stage Drive" |
| `nucleus-daily-draft` | daily at BD 23:45 | Scheduled Task "NAPCO Nucleus - Requirement Management (Daily)" |
| `nucleus-gha-runner` (optional, `--profile runner`) | always-on | MVPACCESS Windows runner at `C:\actions-runner\` |

All Python workers run from one image (`Dockerfile.worker`). The repo
itself is bind-mounted from the host (`/home/ubuntu/napco-nucleus`)
read-only, so `git pull` on the host updates every container without
a rebuild.

## First-time deploy on .123

```bash
# As ubuntu@172.16.205.123:

# 1. Clone the repo at the expected path.
cd /home/ubuntu
git clone https://github.com/napco-labs/napco-nucleus.git

# 2. Prepare the central data dir (Samba serves this, workers read/write it).
sudo mkdir -p /srv/nucleus-central
sudo chown 1001:1001 /srv/nucleus-central   # ubuntu uid:gid

# 3. Cd into the deploy dir.
cd /home/ubuntu/napco-nucleus/deploy/linux-central

# 4. Seed .env. Easiest path is to copy the existing .env from
#    .209 wholesale -- they're the same trust boundary -- and append
#    the Linux-only knobs (SAMBA_*, GHA_*).
#
#    From a Windows dev PC with WinRM access to .209 (saves a hop):
#       scp ubuntu@172.16.205.123:/dev/stdin << 'EOF' > .env
#       <paste contents of .209's C:\napco-nucleus\.env here>
#       EOF
#    Then append the Linux-only knobs from .env.example:
#       SAMBA_USER, SAMBA_PASSWORD, GHA_RUNNER_*, REPO_PATH, CLAUDE_HOME
#
#    Or: copy by hand from the .env.example template and fill in.
cp .env.example .env
nano .env
#   - SAMBA_PASSWORD: strong password (dev PCs need this)
#   - GROQ_API_KEY: copy from .209 .env  (C:\napco-nucleus\.env)
#   - Google creds: copy from .209
#   - GHA_RUNNER_TOKEN: leave empty for first deploy, fill before --profile runner

# 5. Confirm the Claude Max-tier login is in place at ~/.claude/.
ls -la ~/.claude ~/.claude.json
#   If not present, run `claude` interactively once to log in.

# 6. Build + start the core stack (no GHA runner yet).
docker compose build
docker compose up -d

# 7. Watch the logs to confirm clean startup.
docker compose logs -f
```

## Verify from a dev PC

From any Windows dev PC, paste into File Explorer:

```
\\172.16.205.123\nucleus-central
```

Authenticate as the Samba user (`nucleus` + the `SAMBA_PASSWORD` from
`.env`). You should see the same `<dev>/<date>/` layout `.209` had.

## Day-2 operations

| Task | Command |
|---|---|
| Update code | `cd /home/ubuntu/napco-nucleus && git pull` (no restart needed; workers re-read the repo on next tick) |
| Restart one worker | `docker compose restart transcribe` |
| Restart everything | `docker compose restart` |
| Rebuild after Dockerfile/requirements change | `docker compose build && docker compose up -d` |
| Tail logs | `docker compose logs -f --tail 100 <service>` |
| Inspect Samba auth | `docker compose exec samba pdbedit -L` |
| Force a transcribe pass | `docker compose exec transcribe python -m tools.transcribe_calls` |
| Force daily draft now | `docker compose exec daily-draft python do_it_now.py --client all --last-minutes 1440` |
| Add GHA runner | Set `GHA_RUNNER_TOKEN` in `.env`, then `docker compose --profile runner up -d` |

## Rollback to .209

If anything goes wrong during the parallel-cutover window, dev PCs
revert by editing `.env` on their machine:

```
NUCLEUS_CENTRAL_PATH=\\172.16.205.209\nucleus-central
```

No code change required. `.209`'s Scheduled Tasks keep running through
the cutover window for exactly this reason.

## Stack lifecycle

```bash
# Stop everything, keep volumes (whisper models, GHA runner work dir).
docker compose down

# Stop and DESTROY volumes too (whisper re-downloads on next start).
docker compose down -v

# Bring up only specific services (e.g. just Samba for SMB testing).
docker compose up -d samba
```

## Why these design choices

- **Single worker image** (`Dockerfile.worker`): all workers share the
  same Python deps, so we build once and run six times with different
  commands. Cuts disk + build time.
- **Repo bind-mounted read-only**: code updates via `git pull` on the
  host, no image rebuild. The trade is workers can't `pip install`
  new deps without a rebuild -- that's intentional, dep changes go
  through CI.
- **`/srv/nucleus-central` outside the compose dir**: easier to
  back up, doesn't get nuked by `docker compose down -v`, survives
  re-clones of the repo.
- **GHA runner gated behind a profile**: a `docker compose up` for
  smoke-testing doesn't accidentally register a runner against the
  org before we're ready.
- **`network_mode: host` on Samba**: SMB's NetBIOS broadcast doesn't
  cross Docker bridge networks cleanly. Host networking is the
  default for SMB-on-Docker for good reason.
