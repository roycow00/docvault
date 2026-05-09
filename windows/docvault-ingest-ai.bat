@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
REM AI-assisted ingest context-menu verb.
REM   %1 = full path to the file selected in Explorer.

if "%~1"=="" (
    echo usage: %~nx0 ^<file^>
    pause
    exit /b 2
)

set "DOCVAULT_HOME=%~dp0.."
if defined DOCVAULT_PORT (set "PORT=%DOCVAULT_PORT%") else (set "PORT=7777")
set "BASE=http://127.0.0.1:%PORT%"

echo [docvault-ai] checking server at %BASE% ...
curl.exe -s -o NUL -m 1 "%BASE%/health"
if errorlevel 1 (
    echo [docvault-ai] server not running â€” starting in background ...
    call "%~dp0docvault-server.bat"

    echo [docvault-ai] waiting for server to bind ^(up to 15s^) ...
    set "READY="
    for /L %%i in (1,1,15) do (
        timeout /t 1 /nobreak >nul
        curl.exe -s -o NUL -m 1 "%BASE%/health" && set "READY=1" && goto :ready
        echo   ... still waiting ^(%%i/15^)
    )
    echo [docvault-ai] failed to start docvault server.
    echo Try running ".venv\Scripts\activate" then "docvault serve" from a console
    echo to see the actual error.
    pause
    exit /b 3
)
:ready
echo [docvault-ai] server ready. opening progress page ...

REM Open the streaming progress page directly. The page POSTs to
REM /api/ingest/ai/stream itself and shows live status (elapsed time,
REM phase, extracted-text preview, final LLM output) before redirecting
REM to the edit form. We URL-encode the source path through DOCVAULT_SRC
REM env var so unicode / spaces / quotes survive cmd's tokenizer.
set "DOCVAULT_SRC=%~1"
for /f "usebackq delims=" %%U in (`powershell -NoProfile -Command "[uri]::EscapeDataString($env:DOCVAULT_SRC)"`) do (
    set "ENC=%%U"
)
set "DOCVAULT_SRC="

start "" "%BASE%/static/ingest-ai.html?src=!ENC!"

endlocal
