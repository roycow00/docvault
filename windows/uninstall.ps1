<#
.SYNOPSIS
    Uninstall docvault from this machine. NEVER deletes vault data.

.DESCRIPTION
    Removes, in order:
      1. The Explorer right-click verbs (HKCU).
      2. Optionally the .venv           (-RemoveVenv).
      3. Optionally the pointer config at ~\.config\docvault\config.toml
         (-RemovePointerConfig).

    The vault itself (documents, metadata, trash, config) is never touched —
    it is a plain folder of files and remains fully usable by a future
    install on this or any other computer. The script prints where it lives.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\windows\uninstall.ps1 -RemoveVenv
#>
param(
    [switch]$RemoveVenv,
    [switch]$RemovePointerConfig
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Write-Host "[uninstall] project root: $projectRoot"

# --- 1. Locate the vault (report only; we never touch it) ---------------------

$homeCfg = Join-Path $HOME '.config\docvault\config.toml'
$vaultHint = $null
if ($env:DOCVAULT_VAULT) {
    $vaultHint = $env:DOCVAULT_VAULT
} elseif (Test-Path -LiteralPath $homeCfg) {
    $line = Select-String -LiteralPath $homeCfg -Pattern '^\s*vault_root\s*=\s*"(.+)"' | Select-Object -First 1
    if ($line) { $vaultHint = $line.Matches[0].Groups[1].Value -replace '\\\\', '\' }
}

# --- 2. Stop a running server (it holds .venv files open) ----------------------

try {
    $null = Invoke-RestMethod -Uri 'http://127.0.0.1:7777/health' -TimeoutSec 2
    Write-Host "[uninstall] a docvault server is running on port 7777."
    Write-Host "            Stop it first (close its console, or stop the pythonw process), then re-run."
    if ($RemoveVenv) { exit 1 }
} catch {
    # not running — good
}

# --- 3. Remove context-menu verbs ----------------------------------------------

Write-Host "[uninstall] removing Explorer right-click verbs"
$uninstallMenu = Join-Path $projectRoot 'windows\uninstall-context-menu.ps1'
& powershell -NoProfile -ExecutionPolicy Bypass -File $uninstallMenu

# --- 4. Optional: remove the venv ------------------------------------------------

$venv = Join-Path $projectRoot '.venv'
if ($RemoveVenv) {
    if (Test-Path -LiteralPath $venv) {
        Write-Host "[uninstall] removing $venv"
        Remove-Item -LiteralPath $venv -Recurse -Force
    } else {
        Write-Host "[uninstall] no .venv to remove"
    }
} else {
    Write-Host "[uninstall] keeping .venv (pass -RemoveVenv to delete it)"
}

# --- 5. Optional: remove the pointer config --------------------------------------

if ($RemovePointerConfig) {
    if (Test-Path -LiteralPath $homeCfg) {
        Write-Host "[uninstall] removing pointer config $homeCfg"
        Remove-Item -LiteralPath $homeCfg -Force
    }
} else {
    if (Test-Path -LiteralPath $homeCfg) {
        Write-Host "[uninstall] keeping pointer config $homeCfg (pass -RemovePointerConfig to delete)"
    }
}

Write-Host ""
Write-Host "=== docvault uninstalled ==="
if ($vaultHint) {
    Write-Host "Your documents are UNTOUCHED in the vault at: $vaultHint"
} else {
    Write-Host "Your documents are UNTOUCHED in the vault directory (default C:\docvault-data)."
}
Write-Host "Deleting that folder is the only way to remove your documents - docvault never does it."
Write-Host "Restart Explorer to drop the old context-menu entries:"
Write-Host "  Stop-Process -Name explorer -Force; Start-Process explorer"
