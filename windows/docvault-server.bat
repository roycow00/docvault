@echo off
setlocal EnableExtensions
chcp 65001 >nul
REM Background launcher for the docvault server.
REM
REM Spawns pythonw with stdout/stderr redirected to <vault>\logs\server.log so
REM the server survives its parent (cmd.exe under Task Scheduler, or the cmd
REM /c invoked by the right-click verbs) exiting. Without redirection, pythonw
REM inherits the parent's console for stdio; once the parent exits the console
REM handles go invalid, and uvicorn's first INFO log write raises OSError --
REM the scheduled task reports success while the server is already dead.
REM
REM Trace lines are tee'd into a second log under %TEMP% so we can see what
REM happened even if the primary log path can't be opened (OneDrive vault not
REM mounted, permissions, etc.). The scheduled task otherwise fails silently.

set "DOCVAULT_HOME=%~dp0.."
pushd "%DOCVAULT_HOME%"

REM --- pick a trace log we can always write to ---------------------------------
set "TRACE_FILE=%TEMP%\docvault-launch.log"
>>"%TRACE_FILE%" echo [%date% %time%] launch begin  cwd=%CD%  vault=%DOCVAULT_VAULT%  port=%DOCVAULT_PORT%

REM --- pick the primary log dir (prefer <vault>\logs, fall back to %TEMP%) ----
set "LOG_DIR="
if defined DOCVAULT_VAULT (
    if exist "%DOCVAULT_VAULT%\" (
        set "LOG_DIR=%DOCVAULT_VAULT%\logs"
    ) else (
        >>"%TRACE_FILE%" echo [%date% %time%] vault dir not present: "%DOCVAULT_VAULT%"
    )
)
if not defined LOG_DIR set "LOG_DIR=%TEMP%"
if not exist "%LOG_DIR%\" mkdir "%LOG_DIR%" >nul 2>&1
if not exist "%LOG_DIR%\" (
    >>"%TRACE_FILE%" echo [%date% %time%] cannot create LOG_DIR "%LOG_DIR%", falling back to %%TEMP%%
    set "LOG_DIR=%TEMP%"
)
set "LOG_FILE=%LOG_DIR%\server.log"
>>"%TRACE_FILE%" echo [%date% %time%] LOG_FILE=%LOG_FILE%

REM --- pick a Python executable -----------------------------------------------
REM Prefer pythonw.exe (no console), but fall back to python.exe if the venv
REM was built from a Python install that omits the windowed launcher (Microsoft
REM Store Python, embeddable zip). The scheduled task already runs hidden, so a
REM console-subsystem python.exe inherits that and stays invisible.
set "PY="
if exist ".venv\Scripts\pythonw.exe" set "PY=%CD%\.venv\Scripts\pythonw.exe"
if not defined PY if exist ".venv\Scripts\python.exe" set "PY=%CD%\.venv\Scripts\python.exe"
if not defined PY (
    for %%X in (pythonw.exe) do if not "%%~$PATH:X"=="" set "PY=%%~$PATH:X"
)
if not defined PY (
    for %%X in (python.exe) do if not "%%~$PATH:X"=="" set "PY=%%~$PATH:X"
)
if not defined PY (
    >>"%TRACE_FILE%" echo [%date% %time%] ERROR: no python or pythonw found in .venv or on PATH
    >>"%LOG_FILE%" echo [%date% %time%] ERROR: no python or pythonw found in .venv or on PATH
    popd
    endlocal
    exit /b 2
)
>>"%TRACE_FILE%" echo [%date% %time%] PY=%PY%

REM Prove we can write to LOG_FILE *before* spawning, so silent redirect
REM failures (OneDrive locked, perms) get surfaced in the trace.
>>"%LOG_FILE%" echo [%date% %time%] launching: "%PY%" -m docvault serve
if errorlevel 1 (
    >>"%TRACE_FILE%" echo [%date% %time%] ERROR: cannot append to LOG_FILE "%LOG_FILE%" -- redirecting to %%TEMP%%
    set "LOG_FILE=%TEMP%\server.log"
    >>"%LOG_FILE%" echo [%date% %time%] launching: "%PY%" -m docvault serve  ^(fallback log^)
)

REM Wrap python in `cmd /c "..."` so the >> redirect applies to the python
REM process's handles (not start's). The outer `start "" /B` returns
REM immediately, so callers like the right-click verbs and setup.ps1 don't block.
start "" /B cmd /c ""%PY%" -m docvault serve >> "%LOG_FILE%" 2>&1"
>>"%TRACE_FILE%" echo [%date% %time%] spawned background server

popd
endlocal
