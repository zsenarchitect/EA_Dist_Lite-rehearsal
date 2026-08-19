@echo off
setlocal

set "PUBLISH_DIR=%~dp0"
set "STATUS=%PUBLISH_DIR%last_tick_run.txt"
set "LOG=%PUBLISH_DIR%logs\tick.log"

echo === Last tick status ===
if exist "%STATUS%" (
    type "%STATUS%"
) else (
    echo No last_tick_run.txt yet - task has not run or tick failed early.
)

echo.
echo === Recent log (last 40 lines) ===
if exist "%LOG%" (
    powershell -NoProfile -Command "Get-Content -Path '%LOG%' -Tail 40"
) else (
    echo No logs\tick.log yet.
)

echo.
pause
