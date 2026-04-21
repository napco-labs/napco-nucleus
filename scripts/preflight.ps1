<#
.SYNOPSIS
  Verify Runner B is ready to run the MVP Access build-deploy pipeline.

.DESCRIPTION
  Run this on Runner B before enabling the scheduled workflow. Checks:
    - vswhere.exe installed
    - MSBuild found
    - tf.exe (Team Explorer) found
    - TFS URL reachable + credentials valid
    - IIS UNC path reachable + writable

  Exits non-zero on any failure so you can see what to fix.

.PARAMETER TfsUrl
  Full TFS collection URL (e.g. http://tfs.company.local:8080/tfs/DefaultCollection).

.PARAMETER TfsUsername
  Username (DOMAIN\user or user@company.com).

.PARAMETER TfsPassword
  Password or PAT.

.PARAMETER IisUncPath
  UNC path where the build output will be robocopy'd
  (e.g. \\iis-server\c$\inetpub\wwwroot\MVPAccess).

.EXAMPLE
  .\preflight.ps1 -TfsUrl "http://tfs.company.local:8080/tfs/DefaultCollection" `
                  -TfsUsername "DOMAIN\ci-svc" `
                  -TfsPassword "..." `
                  -IisUncPath "\\iis\c$\inetpub\wwwroot\MVPAccess"
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$TfsUrl,
    [Parameter(Mandatory)][string]$TfsUsername,
    [Parameter(Mandatory)][string]$TfsPassword,
    [Parameter(Mandatory)][string]$IisUncPath
)

$ErrorActionPreference = "Stop"
$failures = @()

function Test-Step {
    param([string]$Name, [scriptblock]$Body)
    Write-Host "• $Name ..." -NoNewline
    try {
        & $Body
        Write-Host " OK" -ForegroundColor Green
    } catch {
        Write-Host " FAIL" -ForegroundColor Red
        Write-Host "    $($_.Exception.Message)" -ForegroundColor DarkYellow
        $script:failures += $Name
    }
}

Write-Host "`nMVP Access CI/CD — Runner B preflight check`n"

# 1. vswhere.exe
Test-Step "vswhere.exe present" {
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path $vswhere)) {
        throw "Not found. Install Visual Studio Build Tools or Visual Studio."
    }
}

# 2. MSBuild
$msbuild = $null
Test-Step "MSBuild found" {
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    $script:msbuild = & $vswhere -latest -requires Microsoft.Component.MSBuild `
                      -find "MSBuild\**\Bin\MSBuild.exe" | Select-Object -First 1
    if (-not $script:msbuild) {
        throw "MSBuild component not installed. Add 'MSBuild' in VS Installer."
    }
    Write-Verbose "  → $script:msbuild"
}

# 3. tf.exe
$tfExe = $null
Test-Step "tf.exe (Team Explorer) found" {
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    $vsRoot = & $vswhere -latest -property installationPath
    $script:tfExe = Get-ChildItem $vsRoot -Recurse -Filter "tf.exe" -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -like "*CommonExtensions\Microsoft\TeamFoundation\Team Explorer\*" } |
        Select-Object -First 1 -ExpandProperty FullName
    if (-not $script:tfExe) {
        throw "Team Explorer component missing. Add it in VS Installer."
    }
    Write-Verbose "  → $script:tfExe"
}

# 4. TFS reachable
Test-Step "TFS URL reachable (HTTP HEAD)" {
    try {
        Invoke-WebRequest -Uri $TfsUrl -Method Head -UseDefaultCredentials -TimeoutSec 10 |
            Out-Null
    } catch [System.Net.WebException] {
        # 401 / 403 is fine — it means the server is reachable, just needs auth
        if ($_.Exception.Response.StatusCode.value__ -in 401,403) { return }
        throw "Cannot reach $TfsUrl : $($_.Exception.Message)"
    }
}

# 5. TFS credentials (tf.exe workspaces list as a cheap auth check)
Test-Step "TFS credentials valid" {
    if (-not $script:tfExe) { throw "Skipped (tf.exe not found above)." }
    $login = "$TfsUsername,$TfsPassword"
    $out = & $script:tfExe workspaces /collection:$TfsUrl /login:$login /format:brief 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "tf workspaces failed. Output: $out"
    }
}

# 6. IIS UNC reachable
Test-Step "IIS UNC path reachable" {
    if (-not (Test-Path $IisUncPath)) {
        throw "$IisUncPath not reachable. Check SMB share permissions + network route."
    }
}

# 7. IIS UNC writable (create + delete a marker file)
Test-Step "IIS UNC path writable" {
    $marker = Join-Path $IisUncPath ".preflight-marker-$(Get-Random)"
    "ok" | Out-File -FilePath $marker -Encoding ascii -Force
    Remove-Item $marker -Force
}

# ─── Report ───────────────────────────────────────────────────────────────
Write-Host ""
if ($failures.Count -eq 0) {
    Write-Host "ALL GREEN — Runner B is ready. You can dispatch the pipeline." -ForegroundColor Green
    exit 0
} else {
    Write-Host "$($failures.Count) check(s) failed:" -ForegroundColor Red
    $failures | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
    exit 1
}
