<#
.SYNOPSIS
Headless Claude Code task runner for MASTAN2 (the "brain" layer).

Runs a task prompt (agent\tasks\<Task>.md) through `claude --print` and logs
the result to logs\agent\. Call it on demand, or point a Scheduled Task at it
for recurring agent work (e.g. a daily reminder / status pass).

.EXAMPLE
  .\agent-run.ps1 -Task pipeline-status
  .\agent-run.ps1 -Task remind-add-nucleus

.NOTES
Requires a one-time headless login on this box:  claude setup-token
By default this runs with NORMAL permissions (safe). A task that must take
real actions unattended (write files, send) needs -Autonomous, which passes
--dangerously-skip-permissions -- only use it for tasks you've reviewed.
#>
param(
    [Parameter(Mandatory)][string]$Task,
    [switch]$Autonomous
)
$ErrorActionPreference = "Stop"
$repo = "E:\napco-nucleus"
$taskFile = Join-Path $repo "agent\tasks\$Task.md"
if (-not (Test-Path $taskFile)) {
    Write-Error "No task file: $taskFile  (available: $(Get-ChildItem (Join-Path $repo 'agent\tasks') -Filter *.md -ErrorAction SilentlyContinue | ForEach-Object BaseName))"
    exit 1
}
$logDir = Join-Path $repo "logs\agent"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$log = Join-Path $logDir "$Task-$stamp.log"

$prompt = Get-Content $taskFile -Raw
Set-Location $repo
"[agent-run] task=$Task start=$(Get-Date -Format s) autonomous=$Autonomous" | Tee-Object -FilePath $log

$args = @("--print")
if ($Autonomous) { $args += "--dangerously-skip-permissions" }
$prompt | & claude @args 2>&1 | Tee-Object -FilePath $log -Append

"[agent-run] task=$Task end=$(Get-Date -Format s)" | Tee-Object -FilePath $log -Append
Write-Host "log: $log"
