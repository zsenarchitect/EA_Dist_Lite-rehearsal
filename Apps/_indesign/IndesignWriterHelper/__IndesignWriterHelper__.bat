@echo off
setlocal enabledelayedexpansion

REM EnneadTab InDesign Writer Helper Launcher
REM This batch file checks Python installation and starts the application

echo ============================================================
echo 🔍 EnneadTab InDesign Writer Helper - Python Installation Checker
echo ============================================================

REM Check if PowerShell is available
powershell -Command "exit" >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ PowerShell is not available. Please install PowerShell and try again.
    pause
    exit /b 1
)

REM Run PowerShell script to check Python installation
echo Checking Python installation...
powershell -ExecutionPolicy Bypass -File "%~dp0src\check_python.ps1" -Silent
if %errorlevel% neq 0 (
    echo.
    echo ❌ Python installation check failed.
    echo.
    echo 🔧 TROUBLESHOOTING:
    echo    1. Make sure Python is installed from python.org or Microsoft Store
    echo    2. Install pywin32: pip install pywin32
    echo    3. Make sure InDesign is installed on your system
    echo    4. Run this script as administrator if you have permission issues
    echo    5. Check your firewall settings if network access fails
    echo.
    echo Press any key to open the launcher page for detailed instructions...
    pause >nul
    
    REM Open launcher page in default browser
    start "" "%~dp0src\launcher.html"
    exit /b 1
)

echo ✅ Python installation check passed!
echo.
echo 🚀 Starting InDesign Writer Helper...
echo.

REM Always use system Python for better compatibility
echo [INFO] Using system Python installation for better compatibility
set PYTHON_PATH=python

echo [INFO] Python found at %PYTHON_PATH%, checking modules...
cd /d "%~dp0src"

REM Check and install required modules
"%PYTHON_PATH%" check_modules.py
if %errorlevel% neq 0 (
    echo ❌ Failed to check/install required modules
    echo.
    echo This might be due to:
    echo    - Missing Python dependencies
    echo    - Permission issues
    echo.
    echo Press any key to open the launcher page for troubleshooting...
    pause >nul
    start "" "%~dp0launcher.html"
    exit /b 1
)

echo.
echo 🚀 Starting InDesign Writer Helper server...
echo.

REM Try to start the Python server
"%PYTHON_PATH%" simple_server.py
if %errorlevel% neq 0 (
    echo ❌ Failed to start the Python server.
    echo.
    echo This might be due to:
    echo    - Missing Python dependencies
    echo    - Port 8081 already in use
    echo    - Permission issues
    echo.
    echo Press any key to open the launcher page for troubleshooting...
    pause >nul
    start "" "%~dp0src\launcher.html"
    exit /b 1
)

echo ✅ Application started successfully!
echo 🌐 Opening in your default browser...
echo.

REM Wait a moment for the server to start
timeout /t 2 /nobreak >nul

REM Open the main application in default browser
start "" "http://localhost:8081/"

echo.
echo 💡 The application is now running at http://localhost:8081
echo 💡 Keep this window open while using the application
echo 💡 Press Ctrl+C to stop the server when you're done
echo.
echo Application Features:
echo • Auto-detect InDesign and open documents
echo • View all text frames in your document
echo • Navigate between text frames and pages
echo • Preview text content in a large text box
echo • Future: AI-powered text suggestions and modifications
echo.

REM Keep the batch file running to maintain the server
pause
