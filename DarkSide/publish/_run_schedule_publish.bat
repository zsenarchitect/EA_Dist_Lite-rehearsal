@echo off
REM Optional monitoring GUI (manual start/stop). Production uses Task Scheduler instead.

set "PUBLISH_DIR=%~dp0"
cd /d "%PUBLISH_DIR%..\.."

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

"%PYTHON_EXE%" "DarkSide\publish\_schedule_publish.py"
pause
