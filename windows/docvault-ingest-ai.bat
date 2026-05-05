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
set "PORT=7777"
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
echo [docvault-ai] server ready. asking LLM to draft metadata ...

REM Build JSON body and POST to /api/ingest/ai. Capture draft_id.
for /f "usebackq delims=" %%J in (`powershell -NoProfile -Command "$body = @{ src_path = '%~1' } ^| ConvertTo-Json -Compress; Write-Output $body"`) do (
    set "BODY=%%J"
)

for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "try { $r = Invoke-RestMethod -Method Post -Uri '%BASE%/api/ingest/ai' -ContentType 'application/json' -Body '!BODY!'; Write-Output $r.draft_id } catch { Write-Output '' }"`) do (
    set "DRAFT=%%D"
)

if "%DRAFT%"=="" (
    echo [docvault-ai] AI ingest failed; falling back to manual form.
    for /f "usebackq delims=" %%U in (`powershell -NoProfile -Command "[uri]::EscapeDataString('%~1')"`) do (
        set "ENC=%%U"
    )
    start "" "%BASE%/static/edit.html?src=!ENC!"
    exit /b 0
)

echo [docvault-ai] opening review form for draft %DRAFT%
start "" "%BASE%/static/edit.html?draft=%DRAFT%"

endlocal
