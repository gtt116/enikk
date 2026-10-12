@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\pyinstaller.exe" (
    echo [ERROR] PyInstaller not found. Run: uv pip install -e ".[dev]"
    exit /b 1
)

:: Version: derived from the nearest git tag, plus commit count since that tag
:: and the short commit hash (e.g. 0.11.1+35.g8807ed1). The stamp file is
:: written BEFORE PyInstaller runs so frozen builds embed the version;
:: enikk/version.py reads it when sys.frozen is set. --release requires HEAD
:: to be exactly on a tag.
echo.
echo === Computing version ===
set "VERSION_ARGS="
if "%~1"=="--release" set "VERSION_ARGS=-RequireTag"
set "APP_VERSION="
for /f "usebackq delims=" %%v in (`powershell -NoProfile -ExecutionPolicy Bypass -File scripts\build_version.ps1 %VERSION_ARGS%`) do set "APP_VERSION=%%v"
if not defined APP_VERSION (
    echo [ERROR] Failed to compute version from git.
    exit /b 1
)
echo   Version: %APP_VERSION%

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

:: Build the Inno Setup installer (reads exe from dist, version computed above)
echo.
echo === Building installer ===

set "ISCC="
for /f "delims=" %%i in ('where iscc 2^>nul') do if not defined ISCC set "ISCC=%%i"
if defined ISCC goto run_iscc
if exist "%USERPROFILE%\scoop\shims\iscc.exe" set "ISCC=%USERPROFILE%\scoop\shims\iscc.exe"
if defined ISCC goto run_iscc
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if defined ISCC goto run_iscc
if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
if defined ISCC goto run_iscc
echo [WARN] Inno Setup (ISCC.exe) not found - skipping installer build.
goto skip_installer
:run_iscc

"%ISCC%" installer\enikk_installer.iss /DMyAppVersion=%APP_VERSION%
if %errorlevel% neq 0 (
    echo [ERROR] Installer build failed.
    exit /b 1
)
echo   Installer: installer_output\Enikk-%APP_VERSION%-Setup.exe

:skip_installer

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
