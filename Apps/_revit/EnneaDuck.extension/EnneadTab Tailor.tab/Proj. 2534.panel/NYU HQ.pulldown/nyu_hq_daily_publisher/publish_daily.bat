@echo off
setlocal

REM Activate local venv if present; otherwise rely on PATH python
set VENV_PY="%~dp0..\..\..\..\..\..\.venv\Scripts\python.exe"
if exist %VENV_PY% (
    %VENV_PY% "%~dp0run_publish.py" --batch
    exit /b %errorlevel%
)

REM Fallback to python in PATH
python "%~dp0run_publish.py" --batch
exit /b %errorlevel%


