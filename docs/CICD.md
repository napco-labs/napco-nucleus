# MVP Access CI/CD Pipeline — Setup Guide

## Overview

The `build-deploy.yml` workflow pulls the MVP Access application from
on-prem TFS, builds it on a dedicated "builder" self-hosted runner,
and deploys the output to the IIS server. Runs every night at
**22:00 BDT** (16:00 UTC). The existing E2E tests at 23:59 BDT then
verify the fresh deployment.

```
22:00 BDT  Runner B  ──► TFS (pull)  ──► MSBuild  ──► IIS (UNC copy)
23:59 BDT  Runner A  ──► E2E tests against staging URL
02:00 BDT  ubuntu    ──► API Digest email
```

## Required infrastructure

| Component | Purpose | Owner |
|---|---|---|
| Runner A (MVPACCESS, 172.16.205.209) | Runs tests | Already set up |
| Runner B (new Windows machine) | Builds + deploys the app | **You set this up** |
| TFS server | Source of application code | Exists |
| IIS server | Deploy target | Exists |
| SMTP (Gmail) | Notifications | Already configured |

## Runner B setup

Runner B must have:

1. **Windows runner software** from GitHub, registered with labels
   `self-hosted, Windows, builder`.
2. **Visual Studio Build Tools** or Visual Studio (any edition 2019+),
   with these workloads/components:
   - MSBuild
   - Team Explorer (provides `tf.exe`)
3. **Network access** to:
   - TFS server URL
   - IIS server over SMB (the UNC path in `IIS_DEPLOY_PATH`)
   - SMTP outbound on port 587
4. **Service account permissions** to write to the IIS UNC path.

### Register the runner

```powershell
# On Runner B, in PowerShell as Admin
mkdir C:\actions-runner-builder
cd C:\actions-runner-builder
# Download + extract runner (copy exact commands from GitHub's
# Settings > Actions > Runners > New self-hosted runner page)
.\config.cmd --url https://github.com/titucse/MVP-Access-AI-Agent --token <TOKEN>
# When prompted for additional labels, enter: Windows,builder
# Run as service: Y
# User account: press Enter for NT AUTHORITY\NETWORK SERVICE (or a
# domain service account if that's what has the IIS write perms)
```

### Verify prerequisites

Run `scripts/preflight.ps1` on Runner B (interactive) to sanity-check
tf.exe, MSBuild, TFS reachability, and IIS UNC write access before
the first real pipeline run:

```powershell
cd C:\actions-runner-builder\_work\<scratch>\scripts
.\preflight.ps1 -TfsUrl "http://..." -IisUncPath "\\..." -TfsUsername "..." -TfsPassword "..."
```

## Secrets to configure

Set these on `MVP-Access-AI-Agent` via GitHub UI or `gh` CLI:

| Secret | Example | Notes |
|---|---|---|
| `TFS_URL` | `http://tfs.company.local:8080/tfs/DefaultCollection` | Collection URL |
| `TFS_PROJECT_PATH` | `$/MVPAccess/Main` | Source root path |
| `TFS_USERNAME` | `DOMAIN\ci-svc` or `ci-svc@company.com` | Service account recommended |
| `TFS_PASSWORD` | | |
| `SOLUTION_FILE` | `src\MVPAccess.sln` | Relative to workspace root |
| `IIS_DEPLOY_PATH` | `\\iis-server\c$\inetpub\wwwroot\MVPAccess` | Must be writable by runner service account |

```bash
# One-liner per secret
gh secret set TFS_URL --repo titucse/MVP-Access-AI-Agent
# (paste value when prompted)
```

## First dry-run

1. https://github.com/titucse/MVP-Access-AI-Agent/actions/workflows/build-deploy.yml
2. Click **Run workflow** → `main` → green button.
3. Watch the log. Typical failure modes:
   - `vswhere.exe not found` → install Visual Studio Build Tools.
   - `tf.exe not found` → Team Explorer component missing.
   - `tf get failed` → check `TFS_URL`, credentials, network route.
   - `IIS target UNC path not reachable` → check `net use \\iis-server\c$`
     from Runner B with the service account.
   - `robocopy exit 16` → permission denied on IIS share.

## Rollback / safety

- The pipeline places `app_offline.htm` on the IIS target before
  `robocopy`, so users see a 503 page during the ~30-sec copy window.
  The file is deleted after copy, bringing the site back online.
- If the build fails, nothing is copied and the old deployment stays live.
- If `robocopy` fails mid-way, `app_offline.htm` stays (site stays
  offline) until you manually remove it — prevents half-deployed sites
  from serving traffic.

## Post-deploy tests

The existing `e2e-test.yml` workflow runs at 23:59 BDT and tests against
the public staging URL. Because it runs against whatever is currently
deployed, the fresh build is automatically verified every morning.

If the E2E shows regressions after a deploy, the build likely shipped
a bug. Use the artifact trace zip from the E2E run to investigate.
