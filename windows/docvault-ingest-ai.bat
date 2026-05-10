@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
REM AI-assisted ingest context-menu verb.
REM   %1 = full path to the file selected in Explorer.
REM
REM Invoked through windows\launch-hidden.vbs so the cmd window stays hidden.

if "%~1"=="" exit /b 2

set "DOCVAULT_HOME=%~dp0.."
if defined DOCVAULT_PORT (set "PORT=%DOCVAULT_PORT%") else (set "PORT=7777")
set "BASE=http://127.0.0.1:%PORT%"

curl.exe -s -o NUL -m 1 "%BASE%/health"
if errorlevel 1 (
    call "%~dp0docvault-server.bat"
    for /L %%i in (1,1,15) do (
        timeout /t 1 /nobreak >nul
        curl.exe -s -o NUL -m 1 "%BASE%/health" && goto :ready
    )
)
:ready

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
