@echo off
chcp 65001 >nul
REM Background launcher for the docvault server.
REM
REM Spawns pythonw with stdout/stderr redirected to <vault>\logs\server.log so
REM the server survives its parent (cmd.exe under Task Scheduler, or the cmd
REM /c invoked by the right-click verbs) exiting. Without redirection, pythonw
REM inherits the parent's console for stdio; once the parent exits the console
REM handles go invalid, and uvicorn's first INFO log write raises OSError --
REM the scheduled task reports success while the server is already dead.

set "DOCVAULT_HOME=%~dp0.."
pushd "%DOCVAULT_HOME%"

if defined DOCVAULT_VAULT (
    set "LOG_DIR=%DOCVAULT_VAULT%\logs"
) else (
    set "LOG_DIR=%TEMP%"
)
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1
set "LOG_FILE=%LOG_DIR%\server.log"

if exist ".venv\Scripts\pythonw.exe" (
    set "PY=%CD%\.venv\Scripts\pythonw.exe"
) else (
    set "PY=pythonw.exe"
)

REM Wrap pythonw in `cmd /c "..."` so the >> redirect applies to pythonw's
REM handles (not start's). The outer `start "" /B` returns immediately, so
REM callers like the right-click verbs and setup.ps1 don't block.
start "" /B cmd /c ""%PY%" -m docvault serve >> "%LOG_FILE%" 2>&1"

popd
