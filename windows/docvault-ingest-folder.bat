@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
REM Folder ingest context-menu verb.
REM Opens the file-tree picker in the browser; the user unticks files they
REM don't want and hits "Ingest selected" to batch-ingest with AI.
REM   %1 = full path to the folder selected in Explorer.

if "%~1"=="" (
    echo usage: %~nx0 ^<folder^>
    pause
    exit /b 2
)

set "DOCVAULT_HOME=%~dp0.."
if defined DOCVAULT_PORT (set "PORT=%DOCVAULT_PORT%") else (set "PORT=7777")
set "BASE=http://127.0.0.1:%PORT%"

echo [docvault-folder] checking server at %BASE% ...
curl.exe -s -o NUL -m 1 "%BASE%/health"
if errorlevel 1 (
    echo [docvault-folder] server not running — starting in background ...
    call "%~dp0docvault-server.bat"

    echo [docvault-folder] waiting for server to bind ^(up to 15s^) ...
    set "READY="
    for /L %%i in (1,1,15) do (
        timeout /t 1 /nobreak >nul
        curl.exe -s -o NUL -m 1 "%BASE%/health" && set "READY=1" && goto :ready
        echo   ... still waiting ^(%%i/15^)
    )
    echo [docvault-folder] failed to start docvault server.
    echo Try running ".venv\Scripts\activate" then "docvault serve" from a console
    echo to see the actual error.
    pause
    exit /b 3
)
:ready
echo [docvault-folder] server ready. opening folder picker for: %~1

REM URL-encode the folder path via PowerShell so unicode / spaces survive.
set "DOCVAULT_FOLDER=%~1"
for /f "usebackq delims=" %%U in (`powershell -NoProfile -Command "[uri]::EscapeDataString($env:DOCVAULT_FOLDER)"`) do (
    set "ENC=%%U"
)
set "DOCVAULT_FOLDER="

start "" "%BASE%/static/folder.html?root=!ENC!"
endlocal
