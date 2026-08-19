@echo off
REM RevitSlave4 Launcher - 2412_SPARC Project Only (with Pre-Validation)
REM Activates .venv and runs RevitSlave4.py with project filter

echo ================================================================================
echo RevitSlave4 - 2412_SPARC Project Only (WITH PRE-VALIDATION)
echo ================================================================================
echo.
echo V4 NEW FEATURE: Pre-validates models before launching Revit!
echo   Expected for SPARC: Skip ~32 deleted models in ^<1 min
echo   vs V3: Try all 33 models, waste 2.5+ hours
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

REM Run RevitSlave4 with 2412_SPARC filter
echo.
echo Starting RevitSlave4 with 2412_SPARC project filter...
echo Pre-validation will check which models still exist in ACC...
echo.

python RevitSlave4.py --project 2412_SPARC %*

REM Keep window open on error
if errorlevel 1 (
    echo.
    echo ================================================================================
    echo ERROR: RevitSlave4 exited with error code %errorlevel%
    echo ================================================================================
    pause
)

