@echo off
REM Register EnneadTab schedule publisher with Windows Task Scheduler (every 10 minutes).
REM Replaces a forever-running Python process; each run does one check and exits.
REM Optional: pass --dry-run to print the planned schtasks command without creating it.
setlocal EnableExtensions

set "DRY_RUN=0"
set "ELEVATED=0"
if /I "%~1"=="--dry-run" set "DRY_RUN=1"
if /I "%~1"=="--elevated" set "ELEVATED=1"
if /I "%~2"=="--elevated" set "ELEVATED=1"

set "SCRIPT_DIR=%~dp0"
set "TICK_BAT=%SCRIPT_DIR%_run_schedule_publish_tick.bat"
set "TASK_NAME=EnneadTab_SchedulePublisher"
set "ENROLL_MARKER=%USERPROFILE%\.enneadtab\publisher-enrollment.json"
set "REPO_ROOT=%SCRIPT_DIR%..\.."

REM Eligibility is machine-local ENROLLMENT, not a hardcoded hostname. The old
REM check pinned EANY-1X8MWP3 here while _schedule_publish.py pinned a different
REM name elsewhere and read it from a different source, so the two could disagree.
if not exist "%ENROLL_MARKER%" (
    echo This machine is not enrolled as the EnneadTab publisher.
    echo Run setup-publisher.ps1 first - it verifies the machine can actually
    echo publish before enrolling it, rather than just registering a task.
    echo Expected marker: %ENROLL_MARKER%
    pause
    exit /b 1
)

if not exist "%TICK_BAT%" (
    echo Missing tick runner: %TICK_BAT%
    pause
    exit /b 1
)

REM Direct bat invocation (nested start/wait caused schtasks Last Result errors)
set "TASK_TR=\"%TICK_BAT%\" --scheduled"

if "%DRY_RUN%"=="1" (
    echo [DRY RUN] Would remove legacy tasks: "%TASK_NAME%", "EnneadTab Publisher"
    echo [DRY RUN] Would register every 10 minutes:
    echo   schtasks /create /tn "%TASK_NAME%" /tr "%TASK_TR%" /sc minute /mo 10 /rl LIMITED /f /ru "%USERNAME%" /it
    echo [DRY RUN] Would then set RunOnlyIfIdle + StartIn via PowerShell
    goto :done
)

echo Removing legacy scheduled tasks (if any)...
call :_delete_task "%TASK_NAME%"
call :_delete_task "EnneadTab Publisher"

echo Registering "%TASK_NAME%" every 10 minutes...
schtasks /create /tn "%TASK_NAME%" /tr "%TASK_TR%" /sc minute /mo 10 /rl LIMITED /f /ru "%USERNAME%" /it
if not errorlevel 1 goto :registered

echo.
if "%ELEVATED%"=="1" (
    echo ERROR: schtasks still failed as Administrator.
    echo Check Task Scheduler policy or run: schtasks /create /tn "%TASK_NAME%" /tr "%TASK_TR%" /sc minute /mo 10 /rl LIMITED /f /ru "%USERNAME%" /it
    pause
    exit /b 1
)
echo schtasks failed ^(often caused by /rl HIGHEST on old scripts^). Retrying as Administrator...
call :_elevate_and_rerun --elevated
exit /b %ERRORLEVEL%

:registered
echo Applying idle-only settings ^(skip when keyboard/mouse in use^)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%_apply_schedule_publisher_idle.ps1" -TaskName "%TASK_NAME%" -WorkingDirectory "%REPO_ROOT%"
if errorlevel 1 (
    echo WARNING: idle settings could not be applied; Python idle gate still protects publish.
)
goto :done

:_delete_task
schtasks /delete /tn "%~1" /f >nul 2>&1
if errorlevel 1 (
    echo   Note: could not delete "%~1" - if it still exists, run this bat as Administrator once.
)
exit /b 0

:_elevate_and_rerun
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Start-Process -FilePath '%~f0' -Verb RunAs -Wait -ArgumentList '%*'"
exit /b %ERRORLEVEL%

:done
echo.
if "%DRY_RUN%"=="1" (
    echo [DRY RUN] No scheduled task was created or changed.
) else (
    echo SUCCESS: Task "%TASK_NAME%" is registered.
)
echo   Trigger: every 10 minutes while you are logged on
echo   Idle:    Windows RunOnlyIfIdle + Python keyboard/mouse gate
echo            Office hours Mon-Fri 9-18: need 15 min idle
echo            Off-hours / weekends: need 5 min idle
echo   Action:  %TICK_BAT%
echo.
echo Stop the old forever-running publisher if it is still open.
echo While a tick runs, a console window shows progress.
echo After each run, open DarkSide\publish\last_tick_run.txt or logs\tick.log
echo To remove this task later, run DarkSide\publish\_unregister_schedule_publisher_task.bat
echo.
pause
exit /b 0
