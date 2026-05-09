@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
REM Manual-ingest context-menu verb.
REM   %1 = full path to the file selected in Explorer.

if "%~1"=="" (
    echo usage: %~nx0 ^<file^>
    pause
    exit /b 2
)

set "DOCVAULT_HOME=%~dp0.."
if defined DOCVAULT_PORT (set "PORT=%DOCVAULT_PORT%") else (set "PORT=7777")
set "BASE=http://127.0.0.1:%PORT%"

echo [docvault] checking server at %BASE% ...
curl.exe -s -o NUL -m 1 "%BASE%/health"
if errorlevel 1 (
    echo [docvault] server not running â€” starting in background ...
    call "%~dp0docvault-server.bat"

    echo [docvault] waiting for server to bind ^(up to 15s^) ...
    set "READY="
    for /L %%i in (1,1,15) do (
        timeout /t 1 /nobreak >nul
        curl.exe -s -o NUL -m 1 "%BASE%/health" && set "READY=1" && goto :ready
        echo   ... still waiting ^(%%i/15^)
    )
    echo [docvault] failed to start docvault server.
    echo Try running ".venv\Scripts\activate" then "docvault serve" from a console
    echo to see the actual error.
    pause
    exit /b 3
)
:ready
echo [docvault] server ready.

REM URL-encode the source path via PowerShell. Pass the path through an env
REM var so apostrophes / quotes / unicode in the filename don't get mangled
REM by cmd's argument tokenizer.
set "DOCVAULT_SRC=%~1"
for /f "usebackq delims=" %%U in (`powershell -NoProfile -Command "[uri]::EscapeDataString($env:DOCVAULT_SRC)"`) do (
    set "ENC=%%U"
)
set "DOCVAULT_SRC="

echo [docvault] opening edit form for: %~1
start "" "%BASE%/static/edit.html?src=!ENC!"

endlocal
