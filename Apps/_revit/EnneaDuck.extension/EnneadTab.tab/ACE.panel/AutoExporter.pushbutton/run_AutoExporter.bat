@echo off
REM AutoExporter Orchestrator Launcher
REM Discovers and processes all configs in configs/ folder sequentially

REM Lock file to prevent multiple instances
set LOCK_FILE="%~dp0run_orchestrator.lock"
set MAX_LOCK_AGE_HOURS=24

REM Check if lock file exists (another instance is running)
if exist %LOCK_FILE% (
    REM Check if lock file is stale (older than MAX_LOCK_AGE_HOURS)
    set IS_STALE=0
    for /f "tokens=*" %%i in ('powershell -Command "if ((Get-Date) - (Get-Item '%~dp0run_orchestrator.lock').LastWriteTime -gt [TimeSpan]::FromHours(%MAX_LOCK_AGE_HOURS%)) { 'STALE' } else { 'FRESH' }"') do set LOCK_STATUS=%%i
    
    if "%LOCK_STATUS%"=="STALE" (
        echo ================================================
        echo Stale lock file detected - removing
        echo ================================================
        del %LOCK_FILE%
    ) else (
        echo ================================================
        echo AutoExporter - ALREADY RUNNING
        echo ================================================
        echo.
        echo Another orchestrator instance is already running.
        echo Please wait for it to complete before starting a new one.
        echo.
        echo Lock file: %LOCK_FILE%
        echo.
        echo If you're sure no instance is running, delete the lock file:
        echo del %LOCK_FILE%
        echo.
        echo Press any key to close this window...
        pause > nul
        exit /b 1
    )
)

REM Create lock file with timestamp
echo Started: %DATE% %TIME% > %LOCK_FILE%
echo PID: %RANDOM%%RANDOM% >> %LOCK_FILE%

REM Setup cleanup trap for Ctrl+C
REM Note: Batch files don't have perfect signal handling, but this helps
if not defined CLEANUP_REGISTERED (
    set CLEANUP_REGISTERED=1
    REM Register cleanup in case of early termination
)

echo ================================================
echo AutoExporter Orchestrator
echo ================================================
echo.
echo This will process all config files in the configs/ folder.
echo Each config will be processed sequentially:
echo   1. Open Revit with empty doc
echo   2. Open cloud model specified in config
echo   3. Export files per config settings
echo   4. Send email notification
echo   5. Close Revit
echo   6. Repeat for next config
echo.
echo ================================================

REM Determine paths (developer vs distribution)
set DEV_ROOT=C:\Users\%USERNAME%\github\ennead-llp\EnneadTab-OS
set DIST_ROOT=C:\Users\%USERNAME%\Documents\EnneadTab Ecosystem\EA_Dist

REM Detect which environment we're in
if exist "%DEV_ROOT%\Apps\_revit\KingDuck.lib" (
    set ROOT_PATH=%DEV_ROOT%
    set SCRIPT_DIR=%DEV_ROOT%\Apps\_revit\EnneaDuck.extension\EnneadTab.tab\ACE.panel\AutoExporter.pushbutton
) else (
    set ROOT_PATH=%DIST_ROOT%
    set SCRIPT_DIR=%DIST_ROOT%\Apps\_revit\EnneaDuck.extension\EnneadTab.tab\ACE.panel\AutoExporter.pushbutton
)

REM Set paths
set ORCHESTRATOR_SCRIPT=%SCRIPT_DIR%\orchestrator.py
set VENV_PYTHON=%ROOT_PATH%\.venv\Scripts\python.exe

REM Check if .venv Python exists
if not exist "%VENV_PYTHON%" (
    echo [WARNING] .venv Python not found: %VENV_PYTHON%
    echo Falling back to system Python
    set PYTHON_EXE=python
) else (
    set PYTHON_EXE=%VENV_PYTHON%
)

echo Using Python: %PYTHON_EXE%
echo Orchestrator script: %ORCHESTRATOR_SCRIPT%
echo.

REM Run orchestrator
echo Starting orchestrator...
echo Lock file created: %LOCK_FILE%
echo.
"%PYTHON_EXE%" "%ORCHESTRATOR_SCRIPT%" %*

REM Capture exit code
set EXIT_CODE=%ERRORLEVEL%

REM Check if interrupted
if %EXIT_CODE% EQU -1073741510 (
    echo.
    echo [WARNING] Process was interrupted by user
)

echo.
echo ================================================
if %EXIT_CODE% neq 0 (
    echo [ERROR] Orchestrator failed with exit code %EXIT_CODE%
) else (
    echo [SUCCESS] Orchestrator completed successfully
)
echo ================================================
echo.

REM Clean up lock file
if exist %LOCK_FILE% (
    del %LOCK_FILE%
    echo Lock file removed
)

REM Wait for user input before closing
echo Press any key to close this window...
pause > nul

exit /b %EXIT_CODE%

