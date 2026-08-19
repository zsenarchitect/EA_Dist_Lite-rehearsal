@echo off
REM RevitSlave4 Launcher - All Projects (with Model Pre-Validation)
REM Activates .venv and runs RevitSlave4.py

echo ================================================================================
echo RevitSlave4 - With Model Pre-Validation
echo ================================================================================
echo.
echo NEW in V4: Pre-validates models exist before launching Revit!
echo   - Skips deleted/archived models immediately
echo   - Reduces run time by 50-80%% for projects with deleted models
echo   - Higher success rate (no wasted Revit launches)
echo.

REM Navigate to script directory
cd /d "%~dp0"

REM Activate .venv from workspace root
set VENV_PATH=..\..\..\..\.venv\Scripts\activate.bat

if exist "%VENV_PATH%" (
    echo Activating .venv Python environment...
    call "%VENV_PATH%"
) else (
    echo Warning: .venv not found at %VENV_PATH%
    echo Using system Python...
)

REM Run RevitSlave4
echo.
echo Starting RevitSlave4...
echo.

python RevitSlave4.py %*

REM Keep window open on error
if errorlevel 1 (
    echo.
    echo ================================================================================
    echo ERROR: RevitSlave4 exited with error code %errorlevel%
    echo ================================================================================
    pause
)

