<#
.SYNOPSIS
    Update an existing docvault installation in place.

.DESCRIPTION
    Run after pulling/copying new code into this checkout. It:
      1. Reinstalls docvault into the existing .venv (editable, with any new deps).
      2. Re-registers the Explorer right-click verbs (in case this checkout moved).
      3. Detects a running server and reminds you to restart it.

    Never touches the vault (documents, metadata, config, trash) — the vault
    directory is plain files and is fully forward-compatible.

.PARAMETER SkipContextMenu
    Don't re-register the Explorer verbs.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\windows\update.ps1
#>
param(
    [switch]$SkipContextMenu
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $projectRoot
Write-Host "[update] project root: $projectRoot"

$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "[update] no .venv found - this looks like a fresh checkout."
    Write-Host "         Run setup instead:  powershell -ExecutionPolicy Bypass -File .\windows\setup.ps1"
    exit 1
}

Write-Host "[update] reinstalling docvault into the existing venv"
& $venvPython -m pip install -e "." --upgrade --quiet
if ($LASTEXITCODE -ne 0) { throw "pip install failed (exit $LASTEXITCODE)" }

$version = & $venvPython -c "import docvault; print(docvault.__version__)"
Write-Host "[update] installed docvault $version"

if ($SkipContextMenu) {
    Write-Host "[update] skipping context-menu refresh (-SkipContextMenu)"
} else {
    Write-Host "[update] refreshing Explorer right-click verbs"
    $installScript = Join-Path $projectRoot 'windows\install-context-menu.ps1'
    & powershell -NoProfile -ExecutionPolicy Bypass -File $installScript
    if ($LASTEXITCODE -ne 0) { Write-Host "[update] WARNING: context-menu refresh failed (exit $LASTEXITCODE)" }
}

# If a server is running it still executes the old code; ask for a restart.
try {
    $health = Invoke-RestMethod -Uri 'http://127.0.0.1:7777/health' -TimeoutSec 2
    Write-Host ""
    Write-Host "[update] a docvault server is running (vault: $($health.vault))."
    Write-Host "         It is still running the OLD code. Restart it to pick up the update:"
    Write-Host "         close its console, or: Get-Process pythonw -ErrorAction SilentlyContinue | Where-Object { `$_.Path -like '*docvault*' } | Stop-Process"
    Write-Host "         then start it again (right-click ingest restarts it automatically)."
} catch {
    Write-Host "[update] no running server detected on port 7777."
}

Write-Host ""
Write-Host "=== docvault update complete ($version) ==="
Write-Host "Vault data, config, and trash were not touched."
