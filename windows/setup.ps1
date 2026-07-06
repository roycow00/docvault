<#
.SYNOPSIS
    One-shot Windows setup for docvault.

.DESCRIPTION
    From a fresh checkout, this script:
      1. Verifies Python 3.11+ is on PATH (offers a winget install if not).
      2. Creates the .venv next to pyproject.toml.
      3. Installs docvault into the venv (editable).
      4. Initializes a vault directory (default C:\docvault-data).
      5. Optionally registers Explorer right-click verbs.

    Idempotent — safe to re-run. Does NOT require admin.

.PARAMETER VaultPath
    Where the vault data directory should live. Default: C:\docvault-data

.PARAMETER SkipContextMenu
    Skip the Explorer right-click registration step.

.PARAMETER InstallPython
    If Python isn't found, attempt `winget install Python.Python.3.12` automatically
    (user scope, no admin). Without this flag, the script prints install instructions
    and exits.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\windows\setup.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\windows\setup.ps1 -VaultPath D:\vault -InstallPython
#>
param(
    [string]$VaultPath = "C:\docvault-data",
    [switch]$SkipContextMenu,
    [switch]$InstallPython
)

$ErrorActionPreference = 'Stop'

# Project root = parent of the directory holding this script.
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $projectRoot
Write-Host "[setup] project root: $projectRoot"

# --- 1. Find a usable Python ---------------------------------------------------

function Find-Python {
    # Try the launcher first (handles multiple installs).
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        $ver = & py -3 -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $ver) {
            $major, $minor = $ver -split '\.'
            if ([int]$major -eq 3 -and [int]$minor -ge 11) {
                return @{ Cmd = 'py'; Args = @('-3'); Version = $ver }
            }
        }
    }

    # Fall back to bare `python` on PATH (skipping the Microsoft Store stub).
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python -and $python.Source -notlike '*WindowsApps*') {
        $ver = & python -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and $ver) {
            $major, $minor = $ver -split '\.'
            if ([int]$major -eq 3 -and [int]$minor -ge 11) {
                return @{ Cmd = 'python'; Args = @(); Version = $ver }
            }
        }
    }

    # Probe the standard install locations directly — covers winget user-scope
    # installs that don't update PATH, and machine-wide installs that PATH may
    # not pick up in a non-login shell.
    $candidates = @()
    $candidates += Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'
    $candidates += Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
    $candidates += Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'
    $candidates += 'C:\Python313\python.exe'
    $candidates += 'C:\Python312\python.exe'
    $candidates += 'C:\Python311\python.exe'
    $candidates += 'C:\Program Files\Python313\python.exe'
    $candidates += 'C:\Program Files\Python312\python.exe'
    $candidates += 'C:\Program Files\Python311\python.exe'
    foreach ($p in $candidates) {
        if (Test-Path -LiteralPath $p) {
            $ver = & $p -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -eq 0 -and $ver) {
                $major, $minor = $ver -split '\.'
                if ([int]$major -eq 3 -and [int]$minor -ge 11) {
                    return @{ Cmd = $p; Args = @(); Version = $ver }
                }
            }
        }
    }

    return $null
}

$pyInfo = Find-Python
if (-not $pyInfo) {
    Write-Host "[setup] no Python 3.11+ found on PATH."
    if ($InstallPython) {
        $winget = Get-Command winget -ErrorAction SilentlyContinue
        if (-not $winget) { throw "winget is not available; install Python 3.11+ manually from https://www.python.org/" }
        Write-Host "[setup] installing Python 3.12 via winget (user scope, no admin)..."
        & winget install --id Python.Python.3.12 --source winget --scope user --silent --accept-source-agreements --accept-package-agreements
        # winget user-scope install puts python.exe under %LOCALAPPDATA%\Programs\Python\Python312\
        $candidate = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
        if (-not (Test-Path -LiteralPath $candidate)) {
            throw "Python 3.12 install completed but python.exe not at $candidate. Re-run setup or install manually."
        }
        $pyInfo = @{ Cmd = $candidate; Args = @(); Version = '3.12' }
    } else {
        Write-Host ""
        Write-Host "Install Python 3.11+ from https://www.python.org/ (or run with -InstallPython to use winget)."
        Write-Host "Then re-run this script."
        exit 1
    }
}
Write-Host "[setup] using Python $($pyInfo.Version)  ($($pyInfo.Cmd) $($pyInfo.Args -join ' '))"

# --- 2. Create the venv -------------------------------------------------------

$venv = Join-Path $projectRoot '.venv'
if (Test-Path -LiteralPath (Join-Path $venv 'Scripts\python.exe')) {
    Write-Host "[setup] .venv already exists, reusing"
} else {
    Write-Host "[setup] creating .venv"
    & $pyInfo.Cmd @($pyInfo.Args + @('-m', 'venv', $venv))
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed (exit $LASTEXITCODE)" }
}
$venvPython = Join-Path $venv 'Scripts\python.exe'
$venvDocvault = Join-Path $venv 'Scripts\docvault.exe'

# --- 3. Install docvault into the venv ----------------------------------------

Write-Host "[setup] upgrading pip"
& $venvPython -m pip install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }

Write-Host "[setup] installing docvault (editable)"
& $venvPython -m pip install -e "." --quiet
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# --- 4. Initialize the vault --------------------------------------------------

if (Test-Path -LiteralPath (Join-Path $VaultPath 'config.toml')) {
    Write-Host "[setup] vault already initialized at $VaultPath, skipping init-vault"
} else {
    Write-Host "[setup] initializing vault at $VaultPath"
    & $venvDocvault init-vault $VaultPath
    if ($LASTEXITCODE -ne 0) { throw "init-vault failed" }
}

# --- 4b. Make the config discoverable ------------------------------------------
# `docvault serve` resolves config as: --config flag, then $env:DOCVAULT_VAULT,
# then ~\.config\docvault\config.toml. A fresh install has none of those, so we
# write a small pointer config in the home location naming the vault. The
# vault's own config.toml stays authoritative (docvault follows the pointer).

$homeCfgDir = Join-Path $HOME '.config\docvault'
$homeCfg    = Join-Path $homeCfgDir 'config.toml'
if ($env:DOCVAULT_VAULT) {
    Write-Host "[setup] DOCVAULT_VAULT is set ($env:DOCVAULT_VAULT); leaving config resolution as-is"
} elseif (Test-Path -LiteralPath $homeCfg) {
    Write-Host "[setup] pointer config already exists at $homeCfg; leaving it alone"
} else {
    Write-Host "[setup] writing pointer config -> $homeCfg"
    New-Item -ItemType Directory -Force -Path $homeCfgDir | Out-Null
    $escapedVault = $VaultPath -replace '\\', '\\'
    @(
        '# Pointer config written by windows/setup.ps1.',
        '# docvault reads this only to find the vault; the vault''s own',
        '# config.toml (inside vault_root) is the authoritative config.',
        "vault_root = `"$escapedVault`""
    ) | Out-File -FilePath $homeCfg -Encoding utf8
}

# --- 5. Register Explorer right-click verbs (optional) ------------------------

if ($SkipContextMenu) {
    Write-Host "[setup] skipping context-menu registration (--SkipContextMenu)"
} else {
    Write-Host "[setup] registering Explorer right-click verbs (per-user, no admin)"
    $installScript = Join-Path $projectRoot 'windows\install-context-menu.ps1'
    & powershell -NoProfile -ExecutionPolicy Bypass -File $installScript
    if ($LASTEXITCODE -ne 0) { Write-Host "[setup] WARNING: context-menu registration failed (exit $LASTEXITCODE)" }
}

Write-Host ""
Write-Host "=== docvault setup complete ==="
Write-Host "  vault:        $VaultPath"
Write-Host "  config:       $(Join-Path $VaultPath 'config.toml')"
Write-Host "  venv python:  $venvPython"
Write-Host "  CLI:          $venvDocvault"
Write-Host ""
Write-Host "Next steps:"
Write-Host "  - Edit $(Join-Path $VaultPath 'config.toml') if you want a non-default LLM."
Write-Host "  - For AI ingest with Claude: setx ANTHROPIC_API_KEY `"sk-ant-...`" (then open a new shell)."
if (-not $SkipContextMenu) {
    Write-Host "  - Restart Explorer to refresh the context menu:"
    Write-Host "      Stop-Process -Name explorer -Force; Start-Process explorer"
}
Write-Host "  - Start the web UI: $venvDocvault serve   (then open http://127.0.0.1:7777/)"
Write-Host ""
Write-Host "Later:"
Write-Host "  - Update after pulling new code:  powershell -ExecutionPolicy Bypass -File .\windows\update.ps1"
Write-Host "  - Uninstall (vault data is kept): powershell -ExecutionPolicy Bypass -File .\windows\uninstall.ps1"
Write-Host "  - Server log (headless runs):     $(Join-Path $VaultPath 'logs\server.log')"
