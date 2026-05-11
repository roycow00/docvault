<#
.SYNOPSIS
    Pull the latest docvault code, reinstall deps if needed, and restart the server.

.DESCRIPTION
    One-shot updater for a docvault checkout that was originally set up via
    windows\setup.ps1. Designed to be safe to run repeatedly: it fast-forwards
    main, only reinstalls when pyproject.toml actually changed, and uses the
    existing docvault-server.bat launcher to restart in the background so the
    server stays detached from this shell.

    Run from the repo's windows\ folder OR from anywhere -- paths are resolved
    relative to the script itself, not the current working directory.

.PARAMETER NoRestart
    Pull and (if needed) reinstall, but skip the server restart. Useful when
    the server is already stopped and you don't want this script to start it.

.PARAMETER ForceReinstall
    Always run "pip install -e ." even if pyproject.toml didn't change.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\windows\update.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\windows\update.ps1 -NoRestart
#>

param(
    [switch]$NoRestart,
    [switch]$ForceReinstall
)

$ErrorActionPreference = 'Stop'

# Resolve repo root from this script's path, not $PWD, so it works from any cwd.
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RepoRoot  = Split-Path -Parent $ScriptDir
Set-Location -LiteralPath $RepoRoot

Write-Host "docvault update"
Write-Host "  repo: $RepoRoot"

# --- 1. Sanity checks --------------------------------------------------------

if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot '.git'))) {
    throw "Not a git repo: $RepoRoot"
}
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot '.venv\Scripts\python.exe'))) {
    throw "No .venv found at $RepoRoot\.venv -- run windows\setup.ps1 first."
}

# --- 2. Capture pre-pull state so we can decide on reinstall ----------------

$preCommit = (git rev-parse HEAD).Trim()
$prePyHash = (Get-FileHash 'pyproject.toml' -Algorithm SHA256).Hash

# --- 3. Fast-forward pull ----------------------------------------------------

Write-Host "==> git pull --ff-only"
git pull --ff-only
if ($LASTEXITCODE -ne 0) {
    throw "git pull failed -- resolve uncommitted changes or merge conflicts, then re-run."
}

$postCommit = (git rev-parse HEAD).Trim()
$postPyHash = (Get-FileHash 'pyproject.toml' -Algorithm SHA256).Hash

if ($preCommit -eq $postCommit) {
    Write-Host "Already up to date at $postCommit."
} else {
    Write-Host "Updated $preCommit -> $postCommit"
}

# --- 4. Reinstall if pyproject changed (or forced) ---------------------------

$needsInstall = $ForceReinstall -or ($prePyHash -ne $postPyHash)
if ($needsInstall) {
    if ($ForceReinstall) {
        Write-Host "==> pip install -e . (forced)"
    } else {
        Write-Host "==> pip install -e . (pyproject.toml changed)"
    }
    & "$RepoRoot\.venv\Scripts\pip.exe" install -e .
    if ($LASTEXITCODE -ne 0) {
        throw "pip install failed."
    }
} else {
    Write-Host "==> pyproject.toml unchanged; skipping pip install."
}

# --- 5. Stop the running server ---------------------------------------------

if ($NoRestart) {
    Write-Host "Done. (-NoRestart: not touching the server.)"
    return
}

$stopped = $false
$vault = $env:DOCVAULT_VAULT
if ($vault -and (Test-Path -LiteralPath (Join-Path $vault '.lock'))) {
    try {
        $lock = Get-Content -LiteralPath (Join-Path $vault '.lock') -Raw | ConvertFrom-Json
        if ($lock.pid) {
            $proc = Get-Process -Id $lock.pid -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Host "==> stopping server pid=$($lock.pid) (from $vault\.lock)"
                Stop-Process -Id $lock.pid -Force
                $stopped = $true
            }
        }
    } catch {
        Write-Warning "Could not read $vault\.lock: $_"
    }
}
if (-not $stopped) {
    # Fall back to killing any pythonw running 'docvault serve'. We match on
    # CommandLine so we don't nuke unrelated pythonw processes (e.g. another
    # tool the user is running).
    $procs = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'docvault\s+serve' }
    foreach ($p in $procs) {
        Write-Host "==> stopping $($p.Name) pid=$($p.ProcessId)"
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
        $stopped = $true
    }
}
if (-not $stopped) {
    Write-Host "==> no running server detected; starting fresh"
}

# Give Windows a tick to release the port before re-binding.
Start-Sleep -Milliseconds 500

# --- 6. Start the server via the existing launcher --------------------------

$serverBat = Join-Path $ScriptDir 'docvault-server.bat'
if (-not (Test-Path -LiteralPath $serverBat)) {
    throw "Missing $serverBat -- run windows\setup.ps1 to regenerate."
}

Write-Host "==> starting docvault server (background)"
# /B keeps cmd from spawning a visible window; the .bat itself uses
# 'start "" /B pythonw' so the server detaches from this shell.
& cmd.exe /c "`"$serverBat`""

# --- 7. Health check --------------------------------------------------------

$port = $env:DOCVAULT_PORT
if (-not $port) { $port = 7856 }

$ok = $false
for ($i = 0; $i -lt 10; $i++) {
    Start-Sleep -Milliseconds 500
    try {
        $r = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$port/health" -TimeoutSec 2
        if ($r.StatusCode -eq 200) { $ok = $true; break }
    } catch {
        # not up yet; retry
    }
}

if ($ok) {
    Write-Host "[OK] server healthy on http://127.0.0.1:$port"
} else {
    Write-Warning "Server did not respond on port $port within 5s. Check the log:"
    if ($vault) {
        Write-Warning "  $vault\logs\server.log"
    }
    Write-Warning "  $env:TEMP\docvault-launch.log"
}

Write-Host "Update complete."
