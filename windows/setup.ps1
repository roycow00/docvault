<#
.SYNOPSIS
    Interactive Windows setup for docvault.

.DESCRIPTION
    From a fresh checkout, this script walks the user through:
      1. Verifying Python 3.11+ is on PATH (offers a winget install if not).
      2. Choosing a vault data directory (where files + meta + config live).
      3. Choosing a server port.
      4. Picking an LLM provider (Claude API, local OpenAI-compatible, or none).
      5. Writing the chosen values into <vault>/config.toml so the user does
         NOT need to hand-edit afterward.
      6. Optionally registering Explorer right-click verbs.
      7. Optionally registering an auto-start scheduled task that launches
         the docvault server in the background at user logon.

    Idempotent -- safe to re-run. Does NOT require admin.

    Every flag below also acts as the "default" for the matching prompt, so
    you can pre-seed answers via flags and still confirm interactively, or
    pass -NonInteractive to accept all defaults silently for CI/repeat runs.

.PARAMETER VaultPath
    Where the vault data directory should live. Defaults to the existing
    DOCVAULT_VAULT user env var if set, else C:\docvault-data.

.PARAMETER Port
    HTTP port the local server binds to. Default 7777.

.PARAMETER LlmProvider
    'claude' | 'openai_compat' | 'none'. Default 'claude'.

.PARAMETER ClaudeApiKey
    Sets the ANTHROPIC_API_KEY user env var to this value. Skipped if empty.

.PARAMETER OpenAIBaseUrl
    Base URL for the OpenAI-compatible endpoint (Ollama / LM Studio / vLLM).

.PARAMETER OpenAIModel
    Model name to send to the OpenAI-compatible endpoint.

.PARAMETER OpenAIMultimodal
    'yes' | 'no'. Enable vision pipeline (rasterize PDFs/images).

.PARAMETER ContextMenu
    'yes' | 'no'. Whether to register the Explorer right-click verbs.

.PARAMETER Autostart
    'yes' | 'no'. Whether to register a logon scheduled task that runs
    docvault-server.bat in the background.

.PARAMETER InstallPython
    If Python isn't found, attempt 'winget install Python.Python.3.12'
    automatically (user scope, no admin).

.PARAMETER NonInteractive
    Skip all prompts. Use the defaults / flag values as-is.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\windows\setup.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\windows\setup.ps1 `
        -VaultPath D:\vault -LlmProvider openai_compat `
        -OpenAIBaseUrl http://mac.local:11434/v1 -OpenAIModel qwen3:14b `
        -Autostart yes -NonInteractive
#>
param(
    [string]$VaultPath = "",
    [int]$Port = 7777,
    [ValidateSet('claude','openai_compat','none','')]
    [string]$LlmProvider = "",
    [string]$ClaudeApiKey = "",
    [string]$OpenAIBaseUrl = "http://localhost:11434/v1",
    [string]$OpenAIModel = "qwen3:14b",
    [ValidateSet('yes','no','')]
    [string]$OpenAIMultimodal = "",
    [ValidateSet('yes','no','')]
    [string]$ContextMenu = "",
    [ValidateSet('yes','no','')]
    [string]$Autostart = "",
    [switch]$InstallPython,
    [switch]$NonInteractive
)

$ErrorActionPreference = 'Stop'

# Project root = parent of the directory holding this script.
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $projectRoot
Write-Host ""
Write-Host "=== docvault setup ==="
Write-Host "[setup] project root: $projectRoot"
Write-Host ""

# --- helpers ------------------------------------------------------------------

function Read-WithDefault {
    param(
        [Parameter(Mandatory)][string]$Prompt,
        [string]$Default = ""
    )
    if ($NonInteractive) { return $Default }
    $shown = if ($Default) { "$Prompt [$Default]" } else { "$Prompt" }
    $reply = Read-Host $shown
    if ([string]::IsNullOrWhiteSpace($reply)) { return $Default }
    return $reply.Trim()
}

function Read-Choice {
    param(
        [Parameter(Mandatory)][string]$Prompt,
        [Parameter(Mandatory)][string[]]$Choices,
        [string]$Default
    )
    if (-not $Default) { $Default = $Choices[0] }
    if ($NonInteractive) { return $Default }
    while ($true) {
        $reply = Read-Host "$Prompt ($($Choices -join '/')) [$Default]"
        if ([string]::IsNullOrWhiteSpace($reply)) { return $Default }
        $reply = $reply.Trim().ToLower()
        if ($Choices -contains $reply) { return $reply }
        Write-Host "  please pick one of: $($Choices -join ', ')"
    }
}

function Read-YesNo {
    param(
        [Parameter(Mandatory)][string]$Prompt,
        [string]$Default = "yes"
    )
    $val = Read-Choice -Prompt $Prompt -Choices @('yes','no') -Default $Default
    return ($val -eq 'yes')
}

function Esc-Toml {
    # TOML basic strings need backslashes and double-quotes escaped.
    param([string]$s)
    if ($null -eq $s) { return "" }
    return $s.Replace('\','\\').Replace('"','\"')
}

# --- 1. Find a usable Python --------------------------------------------------

function Find-Python {
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

    # Probe standard install locations directly -- covers winget user-scope
    # installs that don't update PATH in the current shell.
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
    $doInstall = $InstallPython.IsPresent
    if (-not $doInstall) {
        $doInstall = Read-YesNo -Prompt "Install Python 3.12 via winget now (user scope, no admin)?" -Default "yes"
    }
    if ($doInstall) {
        $winget = Get-Command winget -ErrorAction SilentlyContinue
        if (-not $winget) { throw "winget is not available; install Python 3.11+ manually from https://www.python.org/" }
        Write-Host "[setup] installing Python 3.12 via winget..."
        & winget install --id Python.Python.3.12 --source winget --scope user --silent --accept-source-agreements --accept-package-agreements
        $candidate = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
        if (-not (Test-Path -LiteralPath $candidate)) {
            throw "Python 3.12 install completed but python.exe not at $candidate. Re-run setup or install manually."
        }
        $pyInfo = @{ Cmd = $candidate; Args = @(); Version = '3.12' }
    } else {
        Write-Host ""
        Write-Host "Install Python 3.11+ from https://www.python.org/, then re-run this script."
        exit 1
    }
}
Write-Host "[setup] using Python $($pyInfo.Version)  ($($pyInfo.Cmd) $($pyInfo.Args -join ' '))"

# --- 2. Gather settings interactively -----------------------------------------

if (-not $VaultPath) {
    $existingEnv = [Environment]::GetEnvironmentVariable("DOCVAULT_VAULT", "User")
    $defaultVault = if ($existingEnv) { $existingEnv } else { "C:\docvault-data" }
    $VaultPath = Read-WithDefault -Prompt "Vault directory" -Default $defaultVault
}
$VaultPath = [System.IO.Path]::GetFullPath($VaultPath)
Write-Host "[setup] vault: $VaultPath"

if (-not $PSBoundParameters.ContainsKey('Port')) {
    $portReply = Read-WithDefault -Prompt "Server port" -Default "$Port"
    $Port = [int]$portReply
}

if (-not $LlmProvider) {
    Write-Host ""
    Write-Host "LLM provider (powers AI ingest):"
    Write-Host "  claude         - Anthropic API (needs ANTHROPIC_API_KEY)"
    Write-Host "  openai_compat  - local server (Ollama / LM Studio / vLLM)"
    Write-Host "  none           - skip AI; configure later by editing config.toml"
    $LlmProvider = Read-Choice -Prompt "Choice" -Choices @('claude','openai_compat','none') -Default 'claude'
}

$claudeKeyToWrite = ""  # empty == leave env var alone
if ($LlmProvider -eq 'claude') {
    if (-not $ClaudeApiKey) {
        $existingKey = [Environment]::GetEnvironmentVariable("ANTHROPIC_API_KEY", "User")
        if ($existingKey) {
            Write-Host "[setup] ANTHROPIC_API_KEY already set in user env (length=$($existingKey.Length))."
            $overwrite = Read-YesNo -Prompt "Replace it?" -Default "no"
            if ($overwrite) {
                $ClaudeApiKey = Read-WithDefault -Prompt "ANTHROPIC_API_KEY (or empty to skip)" -Default ""
            }
        } else {
            $ClaudeApiKey = Read-WithDefault -Prompt "ANTHROPIC_API_KEY (or empty to set later via setx)" -Default ""
        }
    }
    if ($ClaudeApiKey) { $claudeKeyToWrite = $ClaudeApiKey }
}

if ($LlmProvider -eq 'openai_compat') {
    if (-not $PSBoundParameters.ContainsKey('OpenAIBaseUrl')) {
        $OpenAIBaseUrl = Read-WithDefault -Prompt "OpenAI-compatible base URL" -Default $OpenAIBaseUrl
    }
    if (-not $PSBoundParameters.ContainsKey('OpenAIModel')) {
        $OpenAIModel = Read-WithDefault -Prompt "Model name" -Default $OpenAIModel
    }
    if (-not $OpenAIMultimodal) {
        $OpenAIMultimodal = Read-Choice -Prompt "Enable vision (multimodal) for scanned docs?" -Choices @('yes','no') -Default 'no'
    }
}

if (-not $ContextMenu) {
    $ContextMenu = Read-Choice -Prompt "Register Explorer right-click 'Ingest into docvault' verbs?" -Choices @('yes','no') -Default 'yes'
}

if (-not $Autostart) {
    $Autostart = Read-Choice -Prompt "Auto-start the docvault server at logon (background)?" -Choices @('yes','no') -Default 'yes'
}

# --- 3. Create the venv -------------------------------------------------------

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

# --- 4. Install docvault into the venv ----------------------------------------

Write-Host "[setup] upgrading pip"
& $venvPython -m pip install --upgrade pip --quiet
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed" }

Write-Host "[setup] installing docvault (editable)"
& $venvPython -m pip install -e "." --quiet
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# --- 5. Initialize the vault directory ---------------------------------------

if (-not (Test-Path -LiteralPath $VaultPath)) {
    New-Item -ItemType Directory -Path $VaultPath -Force | Out-Null
}
foreach ($sub in 'files','meta','drafts','trash','.pending-cleanup','index','logs') {
    $d = Join-Path $VaultPath $sub
    if (-not (Test-Path -LiteralPath $d)) {
        New-Item -ItemType Directory -Path $d -Force | Out-Null
    }
}

# --- 6. Write config.toml from chosen settings -------------------------------

$cfgPath = Join-Path $VaultPath 'config.toml'
$existingCfg = Test-Path -LiteralPath $cfgPath
$writeCfg = $true
if ($existingCfg) {
    $writeCfg = Read-YesNo -Prompt "config.toml already exists at $cfgPath. Overwrite with new answers?" -Default "no"
}

if ($writeCfg) {
    $vaultEsc = Esc-Toml $VaultPath
    $multimodalToml = if ($OpenAIMultimodal -eq 'yes') { 'true' } else { 'false' }
    $providerToml = if ($LlmProvider -eq 'none') { 'claude' } else { $LlmProvider }
    $oaiBaseEsc = Esc-Toml $OpenAIBaseUrl
    $oaiModelEsc = Esc-Toml $OpenAIModel

    $cfg = @"
# docvault -- generated by windows\setup.ps1 on $(Get-Date -Format 'yyyy-MM-dd HH:mm')
# To re-run setup with different answers: powershell -File windows\setup.ps1
# To edit by hand, see config.example.toml in the repo for the full schema.

vault_root  = "$vaultEsc"
server_port = $Port

[llm]
provider        = "$providerToml"
max_input_chars = 120000

[llm.claude]
api_key_env      = "ANTHROPIC_API_KEY"
model            = "claude-haiku-4-5-20251001"
use_prompt_cache = true

[llm.openai_compat]
base_url         = "$oaiBaseEsc"
model            = "$oaiModelEsc"
api_key          = "ollama"
local_multimodal = $multimodalToml

[ingest]
on_duplicate   = "open_existing"
suggested_tags = ["Immigration", "House", "Shopping", "School", "Finance", "Tax"]

[cleanup]
retention_days = 30

[trash]
retention_days = 90
"@
    # Set-Content -Encoding utf8 in Windows PowerShell 5.1 emits a UTF-8
    # BOM, which Python's tomllib rejects with "Invalid statement at line 1
    # column 1". Use the .NET API to write UTF-8 *without* BOM.
    [System.IO.File]::WriteAllText($cfgPath, $cfg, [System.Text.UTF8Encoding]::new($false))
    Write-Host "[setup] wrote $cfgPath"
} else {
    Write-Host "[setup] kept existing $cfgPath"
}

# Persist DOCVAULT_VAULT so plain 'docvault serve' (and the right-click .bat
# launchers) find <vault>\config.toml without needing --config every time.
[Environment]::SetEnvironmentVariable("DOCVAULT_VAULT", $VaultPath, "User")
$env:DOCVAULT_VAULT = $VaultPath
Write-Host "[setup] set DOCVAULT_VAULT = $VaultPath (user env, persistent)"

# Persist DOCVAULT_PORT so the right-click .bat launchers probe / open the
# correct port without having to parse config.toml. Defaults to 7777 if unset.
[Environment]::SetEnvironmentVariable("DOCVAULT_PORT", "$Port", "User")
$env:DOCVAULT_PORT = "$Port"
Write-Host "[setup] set DOCVAULT_PORT = $Port (user env, persistent)"

if ($claudeKeyToWrite) {
    [Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY", $claudeKeyToWrite, "User")
    $env:ANTHROPIC_API_KEY = $claudeKeyToWrite
    Write-Host "[setup] set ANTHROPIC_API_KEY (user env, persistent)"
}

# --- 7. Register Explorer right-click verbs (optional) ------------------------

if ($ContextMenu -eq 'yes') {
    Write-Host "[setup] registering Explorer right-click verbs (per-user, no admin)"
    $installScript = Join-Path $projectRoot 'windows\install-context-menu.ps1'
    & powershell -NoProfile -ExecutionPolicy Bypass -File $installScript
    if ($LASTEXITCODE -ne 0) { Write-Host "[setup] WARNING: context-menu registration failed (exit $LASTEXITCODE)" }
} else {
    Write-Host "[setup] skipping context-menu registration"
}

# --- 8. Register autostart (optional) -----------------------------------------

if ($Autostart -eq 'yes') {
    Write-Host "[setup] registering logon scheduled task to auto-start the server"
    $autostartScript = Join-Path $projectRoot 'windows\install-autostart.ps1'
    & powershell -NoProfile -ExecutionPolicy Bypass -File $autostartScript
    if ($LASTEXITCODE -ne 0) { Write-Host "[setup] WARNING: autostart registration failed (exit $LASTEXITCODE)" }
} else {
    Write-Host "[setup] skipping autostart registration"
}

# --- 9. Summary ---------------------------------------------------------------

Write-Host ""
Write-Host "=== docvault setup complete ==="
Write-Host "  vault:        $VaultPath"
Write-Host "  config:       $cfgPath"
Write-Host "  port:         $Port"
Write-Host "  LLM:          $LlmProvider"
Write-Host "  context menu: $ContextMenu"
Write-Host "  autostart:    $Autostart"
Write-Host "  venv python:  $venvPython"
Write-Host "  CLI:          $venvDocvault"
Write-Host ""

if ($LlmProvider -eq 'claude' -and -not $claudeKeyToWrite -and -not $env:ANTHROPIC_API_KEY) {
    Write-Host "Reminder: set ANTHROPIC_API_KEY before using AI ingest:"
    Write-Host "  setx ANTHROPIC_API_KEY `"sk-ant-...`""
    Write-Host ""
}

Write-Host "Next steps:"
if ($Autostart -eq 'yes') {
    $startNow = Read-YesNo -Prompt "Start the server now (will also start at next logon)?" -Default "yes"
    if ($startNow) {
        $serverBat = Join-Path $projectRoot 'windows\docvault-server.bat'
        & cmd /c "`"$serverBat`""
        Write-Host "  server launched in background; open http://127.0.0.1:$Port/"
    } else {
        Write-Host "  server will start at your next Windows logon"
    }
} else {
    Write-Host "  start the web UI: $venvDocvault serve   (then open http://127.0.0.1:$Port/)"
}
if ($ContextMenu -eq 'yes') {
    Write-Host "  restart Explorer to refresh the context menu:"
    Write-Host "    Stop-Process -Name explorer -Force; Start-Process explorer"
}
Write-Host ""
Write-Host "To uninstall later:  powershell -ExecutionPolicy Bypass -File .\windows\uninstall.ps1"
