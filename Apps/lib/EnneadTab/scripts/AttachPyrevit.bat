@echo off
REM Simplified script: attach pyRevit master clone to all installed Revit versions.
pyrevit attach master default --installed

REM Wait 10 seconds, then close automatically.
echo Script will close in 10 seconds...
timeout /t 10 /nobreak >nul

