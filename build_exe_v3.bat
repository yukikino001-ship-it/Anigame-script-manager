@echo off
chcp 65001 >nul
title Build YukinoChan v1.0 - v3

cd /d "%~dp0"

echo ========================================
echo Build YukinoChan v1.0 - v3
echo ========================================
echo.

echo [1/6] Searching Python...

set "PYTHON_CMD="

py -3 --version >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=py -3"

if "%PYTHON_CMD%"=="" (
    python --version >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=python"
)

if "%PYTHON_CMD%"=="" (
    if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
)

if "%PYTHON_CMD%"=="" (
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)

if "%PYTHON_CMD%"=="" (
    if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PYTHON_CMD=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
)

if "%PYTHON_CMD%"=="" (
    echo Python was not found.
    echo.
    echo Please run this in PowerShell to check:
    echo py -3 --version
    echo.
    echo If not found, install Python and check "Add python.exe to PATH".
    pause
    exit /b 1
)

echo Using Python:
%PYTHON_CMD% --version
echo.

echo [2/6] Installing dependencies...

%PYTHON_CMD% -m pip install --upgrade pip
if errorlevel 1 goto BUILD_FAIL

if exist requirements.txt (
    %PYTHON_CMD% -m pip install -r requirements.txt
    if errorlevel 1 goto BUILD_FAIL
)

%PYTHON_CMD% -m pip install pyinstaller
if errorlevel 1 goto BUILD_FAIL

echo.
echo [3/6] Cleaning old build files...

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist YukinoChan.spec del /q YukinoChan.spec

echo.
echo [4/6] Preparing icon...

set "ICON_ARG="

if exist "assets\icon.ico" (
    set "ICON_ARG=--icon=assets\icon.ico"
    echo Found icon: assets\icon.ico
) else (
    if exist "yukinochan.ico" (
        set "ICON_ARG=--icon=yukinochan.ico"
        echo Found icon: yukinochan.ico
    ) else (
        echo No icon found. Building with default icon.
    )
)

echo.
echo [5/6] Building YukinoChan.exe...

%PYTHON_CMD% -m PyInstaller --noconfirm --onedir --windowed --uac-admin --name=YukinoChan %ICON_ARG% --add-data "assets;assets" --add-data "config;config" main.py
if errorlevel 1 goto BUILD_FAIL

echo.
echo [6/6] Copying release files...

if exist "config.json" copy /Y "config.json" "dist\YukinoChan\config.json" >nul
if exist "README.md" copy /Y "README.md" "dist\YukinoChan\README.md" >nul
if exist "USER_GUIDE.md" copy /Y "USER_GUIDE.md" "dist\YukinoChan\USER_GUIDE.md" >nul
if exist "FAQ.md" copy /Y "FAQ.md" "dist\YukinoChan\FAQ.md" >nul
if exist "CHANGELOG.md" copy /Y "CHANGELOG.md" "dist\YukinoChan\CHANGELOG.md" >nul
if exist "RELEASE_NOTES_v1.0.md" copy /Y "RELEASE_NOTES_v1.0.md" "dist\YukinoChan\RELEASE_NOTES_v1.0.md" >nul
if exist "RELEASE_NOTES_v1.0_RC1.md" copy /Y "RELEASE_NOTES_v1.0_RC1.md" "dist\YukinoChan\RELEASE_NOTES_v1.0_RC1.md" >nul
if exist "LICENSE" copy /Y "LICENSE" "dist\YukinoChan\LICENSE" >nul

if exist "docs" xcopy /E /I /Y "docs" "dist\YukinoChan\docs" >nul

echo.
echo ========================================
echo Build finished successfully.
echo Output:
echo dist\YukinoChan\YukinoChan.exe
echo ========================================
echo.
echo Next:
echo 1. Run dist\YukinoChan\YukinoChan.exe
echo 2. Test UI/assets/logs/tasks
echo 3. Remove logs/runtime_stats before final release
echo 4. Check config.json does not contain private paths
echo 5. Zip dist\YukinoChan as YukinoChan_v1.0.zip
echo.
pause
exit /b 0

:BUILD_FAIL
echo.
echo ========================================
echo Build failed.
echo Please copy the error log above and send it to ChatGPT.
echo ========================================
pause
exit /b 1
