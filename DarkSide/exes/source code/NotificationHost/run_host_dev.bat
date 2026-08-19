@echo off
REM Developer-only launcher for NotificationHost -- runs from source, no rebuild.
REM
REM DO NOT move this back under Apps/lib/ExeProducts/. EXE.locate_executable()
REM searches .bat BEFORE .exe, so a copy there shadows NotificationHost.exe on
REM every machine. It also could never work off this box: the publisher copies
REM only Apps/ and Installation/ into EA_Dist, so the DarkSide/ tree this script
REM lives in does not exist on a fleet machine, and the old copy silently
REM launched nothing while still reporting success. See senzhang-todo #3895.
REM
REM Requires a system Python with 'pyw' on PATH. Fleet machines have neither --
REM which is precisely why this stays a developer artifact.
setlocal

set "SCRIPT=%~dp0NotificationHost.py"

if not exist "%SCRIPT%" (
  echo [run_host_dev] NotificationHost.py not found next to this script: "%SCRIPT%" 1>&2
  exit /b 1
)

where pyw >nul 2>&1
if errorlevel 1 (
  echo [run_host_dev] 'pyw' is not on PATH - a system Python is required to run from source. 1>&2
  exit /b 1
)

start "" /B pyw -3 "%SCRIPT%"
exit /b 0
