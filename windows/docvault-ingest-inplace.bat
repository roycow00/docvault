@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
REM In-place ingest context-menu verb.
REM Same as the AI ingest, but locks the storage mode to "reference" so the
REM file stays exactly where it is — only metadata is added to the vault.
REM   %1 = full path to the file selected in Explorer.

if "%~1"=="" (
    echo usage: %~nx0 ^<file^>
    pause
    exit /b 2
)

set "DOCVAULT_HOME=%~dp0.."
if defined DOCVAULT_PORT (set "PORT=%DOCVAULT_PORT%") else (set "PORT=7777")
set "BASE=http://127.0.0.1:%PORT%"

echo [docvault-inplace] checking server at %BASE% ...
curl.exe -s -o NUL -m 1 "%BASE%/health"
if errorlevel 1 (
    echo [docvault-inplace] server not running — starting in background ...
    call "%~dp0docvault-server.bat"

    echo [docvault-inplace] waiting for server to bind ^(up to 15s^) ...
    set "READY="
    for /L %%i in (1,1,15) do (
        timeout /t 1 /nobreak >nul
        curl.exe -s -o NUL -m 1 "%BASE%/health" && set "READY=1" && goto :ready
        echo   ... still waiting ^(%%i/15^)
    )
    echo [docvault-inplace] failed to start docvault server.
    echo Try running ".venv\Scripts\activate" then "docvault serve" from a console
    echo to see the actual error.
    pause
    exit /b 3
)
:ready
echo [docvault-inplace] server ready. asking LLM to draft metadata ...

REM POST to /api/ingest/ai (same as AI flow). The only difference vs the AI
REM verb is we append &lockmode=reference to the URL so the edit form locks
REM the storage radio.
set "DOCVAULT_SRC=%~1"
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "try { $body = ConvertTo-Json -Compress -InputObject @{ src_path = $env:DOCVAULT_SRC }; $r = Invoke-RestMethod -Method Post -Uri '%BASE%/api/ingest/ai' -ContentType 'application/json' -Body $body; Write-Output $r.draft_id } catch { Write-Output '' }"`) do (
    set "DRAFT=%%D"
)
set "DOCVAULT_SRC="

if "%DRAFT%"=="" (
    echo [docvault-inplace] AI ingest failed; falling back to manual form, locked to in-place.
    set "DOCVAULT_SRC=%~1"
    for /f "usebackq delims=" %%U in (`powershell -NoProfile -Command "[uri]::EscapeDataString($env:DOCVAULT_SRC)"`) do (
        set "ENC=%%U"
    )
    set "DOCVAULT_SRC="
    start "" "%BASE%/static/edit.html?src=!ENC!&lockmode=reference"
    exit /b 0
)

echo [docvault-inplace] opening review form for draft %DRAFT%, locked to in-place
start "" "%BASE%/static/edit.html?draft=%DRAFT%&lockmode=reference"

endlocal
