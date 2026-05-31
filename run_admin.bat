@echo off
setlocal
title YukinoChan - Admin Launcher
cd /d "%~dp0"

REM Relaunch this launcher with administrator permission if needed.
net session >nul 2>&1
if not "%errorlevel%"=="0" (
    echo Requesting administrator permission...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs -WorkingDirectory '%~dp0'"
    exit /b
)

echo Start YukinoChan v30 [Administrator]
echo Current directory: %CD%
echo ==========================================
echo.

if not exist "main.py" (
    echo [ERROR] main.py not found in this folder.
    pause
    exit /b 1
)

py -3 --version >nul 2>&1
if "%errorlevel%"=="0" (
    py -3 "main.py"
    goto END
)

python --version >nul 2>&1
if "%errorlevel%"=="0" (
    python "main.py"
    goto END
)

echo [ERROR] Python was not found. Please install Python 3 first.
pause
exit /b 1

:END
set ERR=%ERRORLEVEL%
echo.
echo Program exited. ErrorLevel=%ERR%
pause
