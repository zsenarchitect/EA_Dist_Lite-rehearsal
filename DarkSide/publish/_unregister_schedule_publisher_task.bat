@echo off
setlocal

set "TASK_NAME=EnneadTab_SchedulePublisher"

schtasks /delete /tn "%TASK_NAME%" /f >nul 2>&1
schtasks /delete /tn "EnneadTab Publisher" /f >nul 2>&1

echo Removed scheduled tasks (if they existed).
pause
