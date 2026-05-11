<#
.SYNOPSIS
NAPCO Nucleus -- one-shot teammate setup.

.DESCRIPTION
Runs every step a new teammate would otherwise do by hand:

  1. Verify Python 3.11+ (install via winget if missing)
  2. Create a virtualenv at .venv/ in the repo root
  3. Install Python dependencies from requirements.txt
  4. Copy .env.example -> .env on first run, open it in Notepad so the
     teammate fills the per-machine fields (REQ_IMAP_USER, REQ_IMAP_PASSWORD)
  5. Optionally pre-warm faster-whisper models so the first real call
     doesn't hang on a HuggingFace download (~3 GB across both models)

Idempotent -- re-running skips steps that are already done. Safe to use
as the upgrade path too: re-run after `git pull`.

.NOTES
Compatible with Windows PowerShell 5.1 (no PS7-only syntax).
Script must be run from the repo root or anywhere inside the repo --
it walks up to find the project folder automatically.

.EXAMPLE
    .\scripts\setup.ps1
    .\scripts\setup.ps1 -SkipModelPrewarm
#>
param(
    [switch]$SkipModelPrewarm,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

function Write-Step($msg) {
    Write-Host "==> $msg" -ForegroundColor Cyan
}

function Write-Ok($msg) {
    Write-Host "    OK: $msg" -ForegroundColor Green
}

function Write-Warn($msg) {
    Write-Host "    WARN: $msg" -ForegroundColor Yellow
}

function Write-Err($msg) {
    Write-Host "    ERROR: $msg" -ForegroundColor Red
}

# --- Locate the repo root ------------------------------------------
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
if (-not (Test-Path (Join-Path $repoRoot "requirements.txt"))) {
    Write-Err "requirements.txt not found at $repoRoot"
    Write-Err "Are you running this from inside the napco-nucleus repo?"
    exit 1
}
Set-Location $repoRoot
Write-Host ""
Write-Host "NAPCO Nucleus -- teammate setup" -ForegroundColor White
Write-Host "Repo: $repoRoot"
Write-Host ""

# --- 1. Python 3.11+ -----------------------------------------------
Write-Step "Checking Python 3.11+"

function Get-PythonVersion {
    try {
        $out = & python --version 2>&1
        if ($LASTEXITCODE -ne 0) { return $null }
        if ($out -match "Python (\d+)\.(\d+)\.(\d+)") {
            return [version]"$($matches[1]).$($matches[2]).$($matches[3])"
        }
    } catch {
        return $null
    }
    return $null
}

$pyver = Get-PythonVersion
if ($null -eq $pyver -or $pyver -lt [version]"3.11.0") {
    Write-Warn "Python 3.11+ not found (got: $pyver)"
    Write-Step "Installing Python 3.12 via winget (you may see a UAC prompt)"
    & winget install -e --id Python.Python.3.12 --silent --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) {
        Write-Err "winget install failed. Install Python 3.12 manually from python.org and re-run this script."
        exit 1
    }
    # Refresh PATH for this session so the just-installed python is visible
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"
    $pyver = Get-PythonVersion
    if ($null -eq $pyver -or $pyver -lt [version]"3.11.0") {
        Write-Err "Python 3.12 installed but not on PATH. Open a new PowerShell window and re-run this script."
        exit 1
    }
}
Write-Ok "Python $pyver"

# --- 2. Virtualenv -------------------------------------------------
Write-Step "Setting up virtualenv at .venv\"
$venvPath = Join-Path $repoRoot ".venv"
$venvPython = Join-Path $venvPath "Scripts\python.exe"
if ($Force -and (Test-Path $venvPath)) {
    Write-Warn "Removing existing .venv (-Force)"
    Remove-Item -Recurse -Force $venvPath
}
if (-not (Test-Path $venvPython)) {
    & python -m venv $venvPath
    if ($LASTEXITCODE -ne 0) {
        Write-Err "venv creation failed"
        exit 1
    }
    Write-Ok "Created .venv\"
} else {
    Write-Ok ".venv\ already exists (re-using)"
}

# --- 3. Pip install ------------------------------------------------
Write-Step "Installing dependencies (pip install -r requirements.txt)"
& $venvPython -m pip install --quiet --upgrade pip
if ($LASTEXITCODE -ne 0) {
    Write-Err "pip self-upgrade failed"; exit 1
}
& $venvPython -m pip install --quiet -r (Join-Path $repoRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    Write-Err "pip install failed. Check your network / proxy settings."
    exit 1
}
Write-Ok "Dependencies installed"

# --- 4. .env handling ----------------------------------------------
# Default to the dev-only template (no secrets). The agent host owns
# the full .env.example with Gmail / Drive / API credentials and is
# set up once by an admin, not via this script.
Write-Step "Checking .env"
$envFile = Join-Path $repoRoot ".env"
$envDevExample = Join-Path $repoRoot ".env.example.dev"
$envFullExample = Join-Path $repoRoot ".env.example"
if (-not (Test-Path $envFile)) {
    $template = $null
    if (Test-Path $envDevExample) { $template = $envDevExample }
    elseif (Test-Path $envFullExample) { $template = $envFullExample }
    if ($null -eq $template) {
        Write-Err ".env.example.dev (and .env.example) missing -- repo may be incomplete."
        exit 1
    }
    Copy-Item $template $envFile
    Write-Ok "Copied $(Split-Path $template -Leaf) -> .env"
    Write-Host ""
    Write-Host "    >>> Opening .env in Notepad." -ForegroundColor Yellow
    Write-Host "    >>> No secrets needed -- just confirm NUCLEUS_CENTRAL_PATH points to" -ForegroundColor Yellow
    Write-Host "    >>> your team's central share (e.g. \\MVPACCESS\nucleus)." -ForegroundColor Yellow
    Write-Host "    >>> Save and close Notepad to continue." -ForegroundColor Yellow
    Write-Host ""
    Start-Process notepad.exe -ArgumentList $envFile -Wait
} else {
    Write-Ok ".env exists (re-using). Run with -Force to reset."
}

# --- 5. Pre-warm models (optional) ---------------------------------
if (-not $SkipModelPrewarm) {
    Write-Step "Pre-warming faster-whisper models (~3 GB total, one-time)"
    Write-Host "    base   (~150 MB) -- used by voice daemon" -ForegroundColor Gray
    Write-Host "    large-v3 (~3 GB) -- used by call transcription" -ForegroundColor Gray
    $reply = Read-Host "    Download both now? (Y/n)"
    if ($reply -eq "" -or $reply -match "^[Yy]") {
        Write-Host "    Downloading 'base' model..." -ForegroundColor Gray
        & $venvPython -c 'from faster_whisper import WhisperModel; WhisperModel("base", device="cpu", compute_type="int8")'
        if ($LASTEXITCODE -eq 0) { Write-Ok "base model ready" } else { Write-Warn "base model warmup failed (will download on first use)" }

        Write-Host "    Downloading 'large-v3' model..." -ForegroundColor Gray
        & $venvPython -c 'from faster_whisper import WhisperModel; WhisperModel("large-v3", device="cpu", compute_type="int8")'
        if ($LASTEXITCODE -eq 0) { Write-Ok "large-v3 model ready" } else { Write-Warn "large-v3 model warmup failed (will download on first use)" }
    } else {
        Write-Warn "Skipped model warmup. Models will download on first call (one-time, ~3 GB)."
    }
} else {
    Write-Warn "Skipped model warmup (-SkipModelPrewarm)."
}

# --- 6. Smoke-test imports -----------------------------------------
# Pipe the test code via stdin to avoid PowerShell's argument-quoting
# mangling embedded double quotes when -c "..." is passed to native python.
Write-Step "Smoke-testing imports"
$smokeSrc = @"
from faster_whisper import WhisperModel
from teams import reader
from mail import requirements_inbox
from drive import drive_ingester
from pycaw.pycaw import AudioUtilities
print('imports OK')
"@
$smokeSrc | & $venvPython -
if ($LASTEXITCODE -ne 0) {
    Write-Err "Some imports failed. See pip output above."
    exit 1
}
Write-Ok "Imports clean"

# --- Done ----------------------------------------------------------
Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host ""
Write-Host "Day-to-day:" -ForegroundColor White
Write-Host "  Double-click  scripts\start-daemon.bat   to start the voice daemon"
Write-Host "  Double-click  scripts\pull-now.bat       to pull recent activity into a session"
Write-Host "  Double-click  scripts\update.bat         to git pull + reinstall after code changes"
Write-Host ""
Write-Host "Voice daemon listens for:" -ForegroundColor White
Write-Host "  Start:  Assalamualaikum / Salaam alaikum / Nucleus start"
Write-Host "  Stop :  Allah Hafez / Khoda Hafiz / Nucleus stop"
Write-Host "  (gated to MS Teams calls only -- open data\teams\voice_phrases.json to add more)"
Write-Host ""
