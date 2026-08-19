@echo off
REM One scheduler cycle. Use --scheduled when launched from Task Scheduler (short dwell at end).
setlocal EnableExtensions EnableDelayedExpansion

set "SCHEDULED=0"
if /I "%~1"=="--scheduled" set "SCHEDULED=1"

chcp 65001 >nul 2>&1
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "GIT_TERMINAL_PROMPT=0"
set "GCM_INTERACTIVE=Never"
set "GIT_CONFIG_COUNT="

set "PUBLISH_DIR=%~dp0"
set "LOG_DIR=%PUBLISH_DIR%logs"
set "LOG_FILE=%LOG_DIR%\tick.log"
set "STDOUT_FILE=%LOG_DIR%\tick_last_output.txt"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo Updated: %date% %time%> "%PUBLISH_DIR%last_tick_run.txt"
echo Status: bat_started>> "%PUBLISH_DIR%last_tick_run.txt"
echo Detail: tick bat invoked>> "%PUBLISH_DIR%last_tick_run.txt"

cd /d "%PUBLISH_DIR%..\.." || (
    echo ERROR: Could not cd to repo root from %PUBLISH_DIR%
    pause
    exit /b 1
)

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
    echo WARNING: .venv not found - using system python. Create .venv at repo root for consistent deps.
)

echo.>>"%LOG_FILE%"
echo ===== %date% %time% =====>>"%LOG_FILE%"
echo EnneadTab publish tick started %date% %time%
echo Repo: %CD%
echo Python: !PYTHON_EXE!
echo Log: %LOG_FILE%
echo Status: %PUBLISH_DIR%last_tick_run.txt
echo.

"!PYTHON_EXE!" "DarkSide\publish\_schedule_publish.py" --tick >"%STDOUT_FILE%" 2>&1
set "RC=!ERRORLEVEL!"

type "%STDOUT_FILE%"
type "%STDOUT_FILE%">>"%LOG_FILE%"
echo.>>"%LOG_FILE%"
echo Exit code: !RC!>>"%LOG_FILE%"

echo.
echo Tick finished with exit code !RC!.
echo See %PUBLISH_DIR%last_tick_run.txt and %LOG_FILE%

if "!SCHEDULED!"=="1" (
    echo Closing in 12 seconds...
    timeout /t 12 /nobreak >nul
) else (
    pause
)
exit /b !RC!
