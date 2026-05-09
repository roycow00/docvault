<#
.SYNOPSIS
    Remove the docvault installation from this user account.

.DESCRIPTION
    Reverses what windows\setup.ps1 does:
      1. Stops a running docvault server (reads PID from <vault>\.lock).
      2. Removes the logon scheduled task (windows\uninstall-autostart.ps1).
      3. Removes the Explorer right-click verbs (windows\uninstall-context-menu.ps1).
      4. Clears the DOCVAULT_VAULT user env var.
      5. Optionally clears ANTHROPIC_API_KEY (prompted -- other tools may use it).
      6. Optionally deletes the project's .venv (prompted).

    Does NOT touch the vault data directory itself -- your documents and metadata
    stay where they are. Pass -PurgeVault to override (you'll be prompted again
    before files are deleted).

.PARAMETER PurgeVault
    Also delete the vault data directory ($env:DOCVAULT_VAULT) after confirmation.
    Default: vault is preserved.

.PARAMETER NonInteractive
    Skip all prompts. With no other flags, this means: keep ANTHROPIC_API_KEY,
    keep .venv, keep the vault. Combine with -PurgeVault / -RemoveVenv /
    -RemoveAnthropicKey to opt into destructive steps.

.PARAMETER RemoveVenv
    Delete the project .venv directory.

.PARAMETER RemoveAnthropicKey
    Clear the ANTHROPIC_API_KEY user env var.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\windows\uninstall.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\windows\uninstall.ps1 -RemoveVenv -NonInteractive
#>
param(
    [switch]$PurgeVault,
    [switch]$RemoveVenv,
    [switch]$RemoveAnthropicKey,
    [switch]$NonInteractive
)

$ErrorActionPreference = 'Continue'

$here        = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $here

Write-Host ""
Write-Host "=== docvault uninstall ==="
Write-Host "[uninstall] project root: $projectRoot"
Write-Host ""

function Read-YesNo {
    param([Parameter(Mandatory)][string]$Prompt, [string]$Default = "no")
    if ($NonInteractive) { return ($Default -eq 'yes') }
    $reply = Read-Host "$Prompt (yes/no) [$Default]"
    if ([string]::IsNullOrWhiteSpace($reply)) { return ($Default -eq 'yes') }
    return ($reply.Trim().ToLower() -eq 'yes')
}

# --- 1. Stop running server ---------------------------------------------------

$vaultEnv = [Environment]::GetEnvironmentVariable("DOCVAULT_VAULT", "User")
if ($vaultEnv) {
    $lock = Join-Path $vaultEnv '.lock'
    if (Test-Path -LiteralPath $lock) {
        try {
            $info = Get-Content -LiteralPath $lock -Raw | ConvertFrom-Json
            $serverPid = [int]$info.pid
            $port = if ($info.port) { [int]$info.port } else { 7777 }
            $proc = Get-Process -Id $serverPid -ErrorAction SilentlyContinue
            if ($proc) {
                Write-Host "[uninstall] stopping running server (pid=$serverPid, port=$port)"
                Stop-Process -Id $serverPid -Force -ErrorAction SilentlyContinue
                Start-Sleep -Milliseconds 500
            } else {
                Write-Host "[uninstall] stale .lock at $lock (pid $serverPid not running) -- leaving the file in place"
            }
        } catch {
            Write-Host "[uninstall] could not parse $lock -- skipping server stop"
        }
    } else {
        Write-Host "[uninstall] no .lock under $vaultEnv -- assuming server not running"
    }
} else {
    Write-Host "[uninstall] no DOCVAULT_VAULT env var; skipping server stop"
}

# Belt-and-suspenders: kill any python.exe with 'docvault' in its command line.
try {
    $stragglers = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine -match 'docvault' }
    foreach ($p in $stragglers) {
        Write-Host "[uninstall] killing straggler $($p.Name) pid=$($p.ProcessId)"
        Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    }
} catch {
    # Non-fatal if WMI is unavailable.
}

# --- 2. Remove autostart scheduled task --------------------------------------

$autoUninstall = Join-Path $here 'uninstall-autostart.ps1'
if (Test-Path -LiteralPath $autoUninstall) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $autoUninstall
} else {
    Write-Host "[uninstall] (missing) $autoUninstall"
}

# --- 3. Remove Explorer right-click verbs ------------------------------------

$ctxUninstall = Join-Path $here 'uninstall-context-menu.ps1'
if (Test-Path -LiteralPath $ctxUninstall) {
    & powershell -NoProfile -ExecutionPolicy Bypass -File $ctxUninstall
} else {
    Write-Host "[uninstall] (missing) $ctxUninstall"
}

# --- 4. Clear DOCVAULT_VAULT env var -----------------------------------------

if ($vaultEnv) {
    [Environment]::SetEnvironmentVariable("DOCVAULT_VAULT", $null, "User")
    Remove-Item Env:\DOCVAULT_VAULT -ErrorAction SilentlyContinue
    Write-Host "[uninstall] cleared DOCVAULT_VAULT user env var (was: $vaultEnv)"
} else {
    Write-Host "[uninstall] DOCVAULT_VAULT not set, nothing to clear"
}

$portEnv = [Environment]::GetEnvironmentVariable("DOCVAULT_PORT", "User")
if ($portEnv) {
    [Environment]::SetEnvironmentVariable("DOCVAULT_PORT", $null, "User")
    Remove-Item Env:\DOCVAULT_PORT -ErrorAction SilentlyContinue
    Write-Host "[uninstall] cleared DOCVAULT_PORT user env var (was: $portEnv)"
}

# --- 5. Optional: clear ANTHROPIC_API_KEY ------------------------------------

$anth = [Environment]::GetEnvironmentVariable("ANTHROPIC_API_KEY", "User")
if ($anth) {
    $clearAnth = $RemoveAnthropicKey.IsPresent
    if (-not $clearAnth) {
        $clearAnth = Read-YesNo -Prompt "Clear ANTHROPIC_API_KEY user env var? (other tools may use it)" -Default "no"
    }
    if ($clearAnth) {
        [Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY", $null, "User")
        Remove-Item Env:\ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
        Write-Host "[uninstall] cleared ANTHROPIC_API_KEY user env var"
    } else {
        Write-Host "[uninstall] kept ANTHROPIC_API_KEY"
    }
}

# --- 6. Optional: delete .venv -----------------------------------------------

$venv = Join-Path $projectRoot '.venv'
if (Test-Path -LiteralPath $venv) {
    $delVenv = $RemoveVenv.IsPresent
    if (-not $delVenv) {
        $delVenv = Read-YesNo -Prompt "Delete project .venv ($venv)?" -Default "no"
    }
    if ($delVenv) {
        Write-Host "[uninstall] removing $venv (this can take a moment)"
        Remove-Item -LiteralPath $venv -Recurse -Force -ErrorAction SilentlyContinue
        if (Test-Path -LiteralPath $venv) {
            Write-Host "[uninstall] WARNING: some files under .venv could not be deleted (likely held open)"
        }
    } else {
        Write-Host "[uninstall] kept $venv"
    }
}

# --- 7. Optional: purge vault data dir ---------------------------------------

if ($vaultEnv -and (Test-Path -LiteralPath $vaultEnv)) {
    $purge = $PurgeVault.IsPresent
    if ($purge -and -not $NonInteractive) {
        $purge = Read-YesNo -Prompt "REALLY delete vault data at $vaultEnv (your documents and metadata)?" -Default "no"
    }
    if ($purge) {
        Write-Host "[uninstall] deleting vault data at $vaultEnv"
        Remove-Item -LiteralPath $vaultEnv -Recurse -Force -ErrorAction SilentlyContinue
    } else {
        Write-Host "[uninstall] kept vault data at $vaultEnv"
    }
}

Write-Host ""
Write-Host "=== docvault uninstall complete ==="
Write-Host ""
Write-Host "If the right-click verbs still appear in Explorer, restart it:"
Write-Host "  Stop-Process -Name explorer -Force; Start-Process explorer"
