@echo off
setlocal

set "PUBLISH_DIR=%~dp0"
cd /d "%PUBLISH_DIR%..\.."

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

if /I "%~1"=="24h" (
    "%PYTHON_EXE%" "DarkSide\publish\_phone_notify.py" "EnneadTab: 24h publish check" "Check last_tick_run.txt, tick.log, Task Scheduler, EA_Dist/Lite, wiki."
    exit /b %ERRORLEVEL%
)

if /I "%~1"=="scheduled" (
    "%PYTHON_EXE%" "DarkSide\publish\_phone_notify.py" "EnneadTab: reminder scheduled" "Phone alert in 24h. See DarkSide/publish/REMINDER_check_back_24h.md"
    exit /b %ERRORLEVEL%
)

if "%~1"=="" (
    "%PYTHON_EXE%" "DarkSide\publish\_phone_notify.py" "EnneadTab: publish reminder" "Publisher reminder from EnneadTab-OS"
) else (
    "%PYTHON_EXE%" "DarkSide\publish\_phone_notify.py" "EnneadTab: publish reminder" "%~1"
)
exit /b %ERRORLEVEL%
