# setup-central.ps1
#
# One-shot: give THIS dev PC write access to the NN central share and restart
# the recorder so calls mirror + push automatically. Idempotent — safe to
# re-run. Driven by scripts\setup-central.bat (double-click), or run directly:
#     powershell -ExecutionPolicy Bypass -File scripts\setup-central.ps1 Atik
#
# What it does:
#   1. git pull (main)                      - latest code
#   2. write NUCLEUS_DEV_NAME + Samba creds to .env  (backup at .env.bak)
#   3. clear any stale mapping, store the Windows credential for the server
#   4. verify the share is reachable
#   5. restart the voice daemon (scripts\restart-daemon.bat)
#   6. backfill stranded local calls to central + run the healthcheck
#
# You only type the dev name and the Napco share password (masked). Everything
# else (server, share, user 'nucleus', repo path) is derived automatically.

param([string]$DevName)

# Fixed facts about the deployment.
$Server    = '172.16.205.123'
$Share     = "\\$Server\nucleus-central"
$SambaUser = 'nucleus'

# Repo root = parent of this script's folder (…\scripts\).
$RepoRoot = Split-Path -Parent $PSScriptRoot
$envPath  = Join-Path $RepoRoot '.env'

# Prefer the project venv Python (recorder deps are installed there); fall back
# to the py launcher on machines that installed deps globally. Quoted so a repo
# path with spaces still works when interpolated into the cmd calls below.
$venvPy = Join-Path $RepoRoot '.venv\Scripts\python.exe'
if (Test-Path $venvPy) { $PY = """$venvPy""" } else { $PY = 'py -3' }

Write-Host ""
Write-Host "=== NN central setup ===" -ForegroundColor Cyan
Write-Host "repo : $RepoRoot"
Write-Host "share: $Share (user: $SambaUser)"
Write-Host ""

if (-not (Test-Path $envPath)) {
    Write-Host "ERROR: .env not found at $envPath - is this the right repo?" -ForegroundColor Red
    exit 1
}

# --- inputs ---------------------------------------------------------------
if ([string]::IsNullOrWhiteSpace($DevName)) {
    $DevName = Read-Host "Dev name for the central folder (e.g. Atik)"
}
$DevName = $DevName.Trim()
if ([string]::IsNullOrWhiteSpace($DevName)) { Write-Host "Dev name is required." -ForegroundColor Red; exit 1 }

$sec = Read-Host "Napco share password" -AsSecureString
$pw  = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
           [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
if ([string]::IsNullOrWhiteSpace($pw)) { Write-Host "Password is required." -ForegroundColor Red; exit 1 }

# --- 1. latest code (non-fatal; git noise stays inside cmd) ---------------
Write-Host "`n[1/6] git pull (main)..." -ForegroundColor Yellow
cmd /c "git -C ""$RepoRoot"" checkout main"
cmd /c "git -C ""$RepoRoot"" pull"

# --- 2. write creds to .env (backup, replace any existing lines) ----------
Write-Host "[2/6] writing NUCLEUS_DEV_NAME + Samba creds to .env (backup: .env.bak)..." -ForegroundColor Yellow
Copy-Item $envPath "$envPath.bak" -Force
$lines = Get-Content $envPath |
    Where-Object { $_ -notmatch '^(NUCLEUS_SAMBA_USER|NUCLEUS_SAMBA_PASSWORD|NUCLEUS_DEV_NAME)=' }
$lines += "NUCLEUS_DEV_NAME=$DevName"
$lines += "NUCLEUS_SAMBA_USER=$SambaUser"
$lines += "NUCLEUS_SAMBA_PASSWORD=$pw"
# WriteAllLines = UTF-8 without BOM, so python-dotenv reads the first var cleanly.
[System.IO.File]::WriteAllLines($envPath, $lines)

# --- 3. clear stale mapping/cred, store the credential --------------------
Write-Host "[3/6] storing Windows credential for $Server..." -ForegroundColor Yellow
# Redirect INSIDE cmd so 'not found' messages don't surface as PS errors.
cmd /c "net use $Share /delete /y >nul 2>&1"
cmd /c "cmdkey /delete:$Server >nul 2>&1"
cmdkey /add:$Server /user:$SambaUser /pass:$pw | Out-Null

# --- 4. verify access -----------------------------------------------------
Write-Host "[4/6] verifying share access..." -ForegroundColor Yellow
try {
    Get-ChildItem $Share -ErrorAction Stop | Select-Object -First 3 Name | Out-Null
    Write-Host "  OK - $Share is reachable + no password prompt" -ForegroundColor Green
} catch {
    Write-Host "  FAILED to reach $Share" -ForegroundColor Red
    Write-Host "  $_" -ForegroundColor Red
    Write-Host "  Likely a wrong password, or an existing connection under a different" -ForegroundColor Red
    Write-Host "  user (error 1219). Log that user off the share and re-run this script." -ForegroundColor Red
}

# --- 5. restart the daemon ------------------------------------------------
Write-Host "[5/6] restarting the voice daemon..." -ForegroundColor Yellow
cmd /c """$RepoRoot\scripts\restart-daemon.bat"""

# --- 6. backfill + healthcheck --------------------------------------------
Write-Host "[6/6] pushing stranded calls to central, then healthcheck..." -ForegroundColor Yellow
cmd /c "cd /d ""$RepoRoot"" && $PY -m teams.backfill_central"
cmd /c "cd /d ""$RepoRoot"" && $PY -m tools.healthcheck"

Write-Host "`nDone. Green if the healthcheck's smb-share line shows samba_creds=set and dev='$DevName'." -ForegroundColor Cyan
