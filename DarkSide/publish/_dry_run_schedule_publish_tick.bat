@echo off
setlocal

set "PUBLISH_DIR=%~dp0"
cd /d "%PUBLISH_DIR%..\.."

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

"%PYTHON_EXE%" "DarkSide\publish\_schedule_publish.py" --tick --dry-run
pause
exit /b %ERRORLEVEL%
