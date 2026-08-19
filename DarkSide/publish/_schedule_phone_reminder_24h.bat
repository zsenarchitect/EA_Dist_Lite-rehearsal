@echo off
REM Schedule a one-time phone push in 24 hours via ntfy (requires NTFY_TOPIC in DarkSide/.env).
setlocal EnableExtensions

set "PUBLISH_DIR=%~dp0"
set "TASK_NAME=EnneadTab_PublishPhoneReminder24h"
set "NOTIFY_BAT=%PUBLISH_DIR%_send_phone_reminder_now.bat"

if not exist "%NOTIFY_BAT%" (
    echo Missing %NOTIFY_BAT%
    pause
    exit /b 1
)

for /f "tokens=1,2 delims= " %%a in ('powershell -NoProfile -Command "$t=(Get-Date).AddHours(24); Write-Output ($t.ToString(''HH:mm'') + '' '' + $t.ToString(''MM/dd/yyyy''))"') do (
    set "REM_ST=%%a"
    set "REM_SD=%%b"
)

echo Scheduling phone reminder at %REM_SD% %REM_ST% ...
schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1
schtasks /create /f /tn "%TASK_NAME%" /sc once /st %REM_ST% /sd %REM_SD% ^
  /tr "cmd /c \"\"%NOTIFY_BAT%\" 24h\"" /rl LIMITED /ru "%USERNAME%" /it

if errorlevel 1 (
    echo Failed to schedule task.
    pause
    exit /b 1
)

echo Scheduled. Sending confirmation to phone now...
call "%NOTIFY_BAT%" scheduled
pause
