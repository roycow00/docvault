<#
.SYNOPSIS
    Stop the running docvault server and relaunch it in the background.

.DESCRIPTION
    Use this after editing config.toml so the server re-reads it. The server
    loads config once at startup and holds it in memory for its lifetime, so
    a restart is required for config changes to take effect.

    Resolves the running process from <vault>\.lock (preferred) and falls back
    to matching pythonw/python processes whose command line includes
    "docvault serve" -- the same logic windows\update.ps1 uses.

    Relaunches via wscript.exe + launch-hidden.vbs + docvault-server.bat so
    the new server detaches cleanly from this shell (no orphan console).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\windows\restart-server.ps1
#>

param(
    [int]$HealthTimeoutSec = 10
)

$ErrorActionPreference = 'Stop'

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$RepoRoot  = Split-Path -Parent $ScriptDir

Write-Host "docvault restart"
Write-Host "  repo: $RepoRoot"

# --- 1. Locate launcher artifacts -------------------------------------------

$serverBat   = Join-Path $ScriptDir 'docvault-server.bat'
$vbsLauncher = Join-Path $ScriptDir 'launch-hidden.vbs'
if (-not (Test-Path -LiteralPath $serverBat)) {
    throw "Missing $serverBat -- run windows\setup.ps1 to regenerate."
}
if (-not (Test-Path -LiteralPath $vbsLauncher)) {
    throw "Missing $vbsLauncher -- run windows\setup.ps1 to regenerate."
}

# --- 2. Stop the running server ---------------------------------------------

$stopped = $false
$vault   = $env:DOCVAULT_VAULT

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
    # Fall back: match pythonw/python processes running 'docvault serve'.
    # CommandLine match keeps us from killing unrelated python processes.
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

# --- 3. Start the server (detached) -----------------------------------------

Write-Host "==> starting docvault server (background)"
& wscript.exe $vbsLauncher $serverBat

# --- 4. Health check --------------------------------------------------------

# Prefer the port from <vault>\config.toml; fall back to DOCVAULT_PORT, then
# 7777 (the default everywhere else: config.py, setup.ps1, the .bat verbs).
$port = $null
if ($vault) {
    $cfgPath = Join-Path $vault 'config.toml'
    if (Test-Path -LiteralPath $cfgPath) {
        $portLine = Select-String -Path $cfgPath -Pattern '^\s*server_port\s*=\s*(\d+)' -List
        if ($portLine) {
            $port = [int]$portLine.Matches[0].Groups[1].Value
        }
    }
}
if (-not $port -and $env:DOCVAULT_PORT) { $port = [int]$env:DOCVAULT_PORT }
if (-not $port) { $port = 7777 }

$ok = $false
$deadline = (Get-Date).AddSeconds($HealthTimeoutSec)
while ((Get-Date) -lt $deadline) {
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
    Write-Warning "Server did not respond on port $port within $HealthTimeoutSec s. Check:"
    if ($vault) {
        Write-Warning "  $vault\logs\server.log"
    }
    Write-Warning "  $env:TEMP\docvault-launch.log"
    exit 1
}
