<#
.SYNOPSIS
    Register docvault context-menu verbs in HKCU (no admin required).

.DESCRIPTION
    Adds three right-click verbs to all files:
      "Ingest into docvault"             -> docvault-ingest.bat "%1"
      "Ingest into docvault (AI)"        -> docvault-ingest-ai.bat "%1"
      "Ingest document in-place (AI)"    -> docvault-ingest-inplace.bat "%1"
    Plus one right-click verb on folders:
      "Ingest folder into docvault"      -> docvault-ingest-folder.bat "%1"

    Run uninstall-context-menu.ps1 to remove.

    Per-user install -- writes only under HKCU\Software\Classes\.
    No admin elevation required, but you may need to restart Explorer
    before it picks up the new verbs:
        Stop-Process -Name explorer -Force
#>

$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$ingestBat        = Join-Path $here 'docvault-ingest.bat'
$ingestAiBat      = Join-Path $here 'docvault-ingest-ai.bat'
$ingestInplaceBat = Join-Path $here 'docvault-ingest-inplace.bat'
$ingestFolderBat  = Join-Path $here 'docvault-ingest-folder.bat'

if (-not (Test-Path -LiteralPath $ingestBat))        { throw "missing $ingestBat" }
if (-not (Test-Path -LiteralPath $ingestAiBat))      { throw "missing $ingestAiBat" }
if (-not (Test-Path -LiteralPath $ingestInplaceBat)) { throw "missing $ingestInplaceBat" }
if (-not (Test-Path -LiteralPath $ingestFolderBat))  { throw "missing $ingestFolderBat" }

# We use reg.exe rather than the PowerShell registry provider because the
# path "HKCU\Software\Classes\*\shell\..." contains a literal '*' that
# PowerShell's path engine interprets as a wildcard -- New-Item and
# Set-ItemProperty then try to enumerate every key under Classes\ and hang
# (or fail silently) on a populated registry. reg.exe takes paths as raw
# strings and is bundled with Windows.
function Install-Verb {
    param(
        [string]$VerbKey,
        [string]$DisplayName,
        [string]$BatPath,
        [string]$ClassRoot = 'HKCU\Software\Classes\*\shell'   # files by default
    )
    $base = "$ClassRoot\$VerbKey"
    $cmd  = "$base\command"

    # We want this stored as REG_SZ in the registry:
    #   "C:\full\path\to\bat" "%1"
    # so that filenames containing spaces, '&', '(' etc. survive cmd's
    # tokenizer when Explorer invokes the verb. Getting reg.exe to receive
    # the embedded double-quotes intact is fiddly because PowerShell's
    # native-command argument passer strips them. Workaround: write a
    # temporary .reg file and import it -- the file format takes the value
    # verbatim with \" escapes for inner quotes, and bypasses PowerShell's
    # tokenizer entirely.
    $regBat = $BatPath -replace '\\', '\\'                  # escape backslashes for .reg syntax
    $verbDisplay = $DisplayName -replace '"', '\"'
    $cmdValue = '\"' + $regBat + '\" \"%1\"'                # produces: "C:\path\to.bat" "%1"
    $iconValue = $regBat                                    # Icon is a single path, no inner quotes needed

    $regBaseKey = $base -replace '^HKCU', 'HKEY_CURRENT_USER'
    $regCmdKey  = $cmd  -replace '^HKCU', 'HKEY_CURRENT_USER'

    $regBody = @"
Windows Registry Editor Version 5.00

[$regBaseKey]
@="$verbDisplay"
"Icon"="$iconValue"

[$regCmdKey]
@="$cmdValue"
"@

    $tmp = [System.IO.Path]::ChangeExtension([System.IO.Path]::GetTempFileName(), '.reg')
    # .reg files MUST be UTF-16 LE with BOM for the "Windows Registry Editor
    # Version 5.00" header to be recognized; otherwise reg.exe import errors.
    [System.IO.File]::WriteAllText($tmp, $regBody, [System.Text.UnicodeEncoding]::new($false, $true))
    try {
        # reg.exe writes "The operation completed successfully." to stderr
        # even on success. Don't redirect stderr (2>&1 would trip
        # NativeCommandError under $ErrorActionPreference='Stop'); rely on
        # $LASTEXITCODE alone, and just suppress stdout.
        & reg.exe import $tmp | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "reg.exe import failed for $VerbKey (exit $LASTEXITCODE)" }
    } finally {
        Remove-Item -LiteralPath $tmp -ErrorAction SilentlyContinue
    }
    Write-Host "installed: $DisplayName -> $BatPath"
}

# File verbs (HKCU\Software\Classes\*\shell -- applies to all file types)
Install-Verb -VerbKey 'Docvault'        -DisplayName 'Ingest into docvault'           -BatPath $ingestBat
Install-Verb -VerbKey 'DocvaultAI'      -DisplayName 'Ingest into docvault (AI)'      -BatPath $ingestAiBat
Install-Verb -VerbKey 'DocvaultInPlace' -DisplayName 'Ingest document in-place (AI)'  -BatPath $ingestInplaceBat

# Folder verb (HKCU\Software\Classes\Directory\shell -- right-click on folder
# in Explorer's tree or list view).
Install-Verb -VerbKey 'DocvaultFolder' -DisplayName 'Ingest folder into docvault' `
    -BatPath $ingestFolderBat -ClassRoot 'HKCU\Software\Classes\Directory\shell'

Write-Host ""
Write-Host "Restart Explorer to refresh the context menu:"
Write-Host "  Stop-Process -Name explorer -Force; Start-Process explorer"
