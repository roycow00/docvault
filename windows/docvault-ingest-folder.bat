@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
REM Folder ingest context-menu verb.
REM Opens the file-tree picker in the browser; the user unticks files they
REM don't want and hits "Ingest selected" to batch-ingest with AI.
REM   %1 = full path to the folder selected in Explorer.
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

REM URL-encode the folder path via PowerShell so unicode / spaces survive.
set "DOCVAULT_FOLDER=%~1"
for /f "usebackq delims=" %%U in (`powershell -NoProfile -Command "[uri]::EscapeDataString($env:DOCVAULT_FOLDER)"`) do (
    set "ENC=%%U"
)
set "DOCVAULT_FOLDER="

start "" "%BASE%/static/folder.html?root=!ENC!"
endlocal
