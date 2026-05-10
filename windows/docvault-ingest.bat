@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
REM Manual-ingest context-menu verb.
REM   %1 = full path to the file selected in Explorer.
REM
REM Invoked through windows\launch-hidden.vbs so the cmd window stays hidden;
REM no `pause` here on purpose -- a silent hang would be worse than a flash.
REM Failure modes (server didn't bind, etc.) end up surfacing as a browser
REM "can't reach 127.0.0.1" page, which is itself an honest signal.

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

REM URL-encode the source path via PowerShell. Pass the path through an env
REM var so apostrophes / quotes / unicode in the filename don't get mangled
REM by cmd's argument tokenizer.
set "DOCVAULT_SRC=%~1"
for /f "usebackq delims=" %%U in (`powershell -NoProfile -Command "[uri]::EscapeDataString($env:DOCVAULT_SRC)"`) do (
    set "ENC=%%U"
)
set "DOCVAULT_SRC="

start "" "%BASE%/static/edit.html?src=!ENC!"

endlocal
