@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\pyinstaller.exe" (
    echo [ERROR] PyInstaller not found. Run: .venv\Scripts\pip install pyinstaller
    exit /b 1
)

:: Parse arguments
set BUILD_MODE=debug
for %%a in (%*) do (
    if "%%a"=="--release" set BUILD_MODE=release
    if "%%a"=="-r" set BUILD_MODE=release
)

echo === Cleaning previous build ===
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

:: Build with appropriate mode
if "%BUILD_MODE%"=="release" (
    echo === Building release build - no console window ===
    set "ENIKK_RELEASE=1"
    set "OUTPUT_DIR=enikk"
) else (
    echo === Building debug build - with console window ===
    set "ENIKK_RELEASE=0"
    set "OUTPUT_DIR=enikk-debug"
)

echo [INFO] ENIKK_RELEASE=%ENIKK_RELEASE%

.venv\Scripts\pyinstaller.exe enikk.spec --noconfirm

if %errorlevel% neq 0 (
    echo [ERROR] Build failed.
    exit /b 1
)

:: Copy install guide into dist
copy /Y docs\INSTALL.txt dist\%OUTPUT_DIR%\INSTALL.txt >nul

:: Zip the output directory
echo.
echo === Creating zip archive ===
cd dist
powershell -Command "Compress-Archive -Path '%OUTPUT_DIR%' -DestinationPath '%OUTPUT_DIR%.zip' -Force"
cd ..

if %errorlevel% neq 0 (
    echo [ERROR] Zip creation failed.
    exit /b 1
)

echo.
echo === Build complete ===
for %%F in (dist\%OUTPUT_DIR%\%OUTPUT_DIR%.exe) do echo   EXE: %%F (%%~zF bytes)
for %%F in (dist\%OUTPUT_DIR%.zip) do echo   ZIP: %%F (%%~zF bytes)
echo.
echo Usage:
echo   build.bat          - Build debug version (with console)
echo   build.bat --release - Build release version (no console)
echo.
