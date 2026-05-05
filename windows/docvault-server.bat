@echo off
chcp 65001 >nul
REM Background launcher for the docvault server.
REM Uses pythonw so no console window appears.

set "DOCVAULT_HOME=%~dp0.."
pushd "%DOCVAULT_HOME%"

if exist ".venv\Scripts\pythonw.exe" (
    start "" /B ".venv\Scripts\pythonw.exe" -m docvault serve
) else (
    start "" /B pythonw -m docvault serve
)

popd
