@echo off
REM One-time setup on the publish PC: registers the 10-minute Windows scheduled task.
REM Pass --dry-run to preview without creating the scheduled task.
call "%~dp0_register_schedule_publisher_task.bat" %*
