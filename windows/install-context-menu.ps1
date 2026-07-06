<#
.SYNOPSIS
    Register docvault context-menu verbs in HKCU (no admin required).

.DESCRIPTION
    Adds two right-click verbs to all files:
      "Ingest into docvault"          -> docvault-ingest.bat "%1"
      "Ingest into docvault (AI)"     -> docvault-ingest-ai.bat "%1"

    Run uninstall-context-menu.ps1 to remove.

    Per-user install — writes only under HKCU\Software\Classes\.
    No admin elevation required, but you may need to restart Explorer
    before it picks up the new verbs:
        Stop-Process -Name explorer -Force
#>

$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$ingestBat   = Join-Path $here 'docvault-ingest.bat'
$ingestAiBat = Join-Path $here 'docvault-ingest-ai.bat'

if (-not (Test-Path -LiteralPath $ingestBat))   { throw "missing $ingestBat" }
if (-not (Test-Path -LiteralPath $ingestAiBat)) { throw "missing $ingestAiBat" }

# We use reg.exe rather than the PowerShell registry provider because the
# path "HKCU\Software\Classes\*\shell\..." contains a literal '*' that
# PowerShell's path engine interprets as a wildcard — `New-Item` and
# `Set-ItemProperty` then try to enumerate every key under Classes\ and hang
# (or fail silently) on a populated registry. reg.exe takes paths as raw
# strings and is bundled with Windows.
function Install-Verb {
    param(
        [string]$VerbKey,
        [string]$DisplayName,
        [string]$BatPath
    )
    $base = "HKCU\Software\Classes\*\shell\$VerbKey"
    $cmd  = "$base\command"

    # Build the command value: "C:\full\path\to\bat" "%1"
    # reg.exe's /d wants the value as a single argument; we pass it via a
    # PowerShell string with embedded quotes, and reg.exe stores it as a
    # plain REG_SZ.
    $command = '"' + $BatPath + '" "%1"'

    & reg.exe add $base /ve /d $DisplayName /f | Out-Null
    & reg.exe add $base /v Icon /d $BatPath /f | Out-Null
    & reg.exe add $cmd /ve /d $command /f | Out-Null

    if ($LASTEXITCODE -ne 0) { throw "reg.exe failed for $VerbKey (exit $LASTEXITCODE)" }
    Write-Host "installed: $DisplayName -> $BatPath"
}

Install-Verb -VerbKey 'Docvault'   -DisplayName 'Ingest into docvault'      -BatPath $ingestBat
Install-Verb -VerbKey 'DocvaultAI' -DisplayName 'Ingest into docvault (AI)' -BatPath $ingestAiBat

Write-Host ""
Write-Host "Restart Explorer to refresh the context menu:"
Write-Host "  Stop-Process -Name explorer -Force; Start-Process explorer"
