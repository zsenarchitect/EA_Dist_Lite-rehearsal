@echo off
REM Cancel RevitSlave4 Gracefully
REM Creates a cancel signal file that the orchestrator checks

echo ================================================================================
echo Cancel RevitSlave4
echo ================================================================================
echo.

REM Navigate to script directory
cd /d "%~dp0"

REM Create cancel signal file
echo %DATE% %TIME% > revitslave3.cancel

echo [OK] Cancellation signal sent!
echo.
echo The orchestrator will:
echo  1. Detect the cancel file
echo  2. Stop processing new jobs
echo  3. Kill current Revit process
echo  4. Exit gracefully
echo.
echo NOTE: Current job will be terminated immediately.
echo.

pause

