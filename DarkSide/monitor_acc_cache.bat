@echo off
REM Batch file to run ACC cache monitor using .venv Python

REM Get the directory where this batch file is located
set "SCRIPT_DIR=%~dp0"

REM Navigate to project root (one level up from DarkSide)
cd /d "%SCRIPT_DIR%.."

REM Run the monitor script using .venv Python
.venv\Scripts\python.exe "DarkSide\monitor_acc_cache.py" %*

REM Pause to see any output
pause
