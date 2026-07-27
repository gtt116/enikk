@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\pyinstaller.exe" (
    echo [ERROR] PyInstaller not found. Run: uv pip install pyinstaller
    exit /b 1
)

echo === Cleaning previous build ===
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo === Building enikk ===
set "OUTPUT_DIR=enikk"

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
for %%F in (dist\%OUTPUT_DIR%\enikk.exe) do echo   EXE: %%F (%%~zF bytes)
for %%F in (dist\%OUTPUT_DIR%.zip) do echo   ZIP: %%F (%%~zF bytes)
echo.
