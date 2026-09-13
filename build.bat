@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\pyinstaller.exe" (
    echo [ERROR] PyInstaller not found. Run: uv pip install -e ".[dev]"
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

:: Build the Inno Setup installer (reads exe from dist, version from enikk/version.py)
echo.
echo === Building installer ===
for /f "tokens=3 delims= " %%v in ('findstr "__version__" enikk\version.py') do set "BASE_VERSION=%%v"
set BASE_VERSION=%BASE_VERSION:"=%

:: Version: --release = formal (BASE); default = dev (BASE-dev.<git commit count>)
set "APP_VERSION=%BASE_VERSION%"
if "%~1"=="--release" goto :version_done
set "COMMIT_COUNT="
for /f %%c in ('git rev-list --count HEAD 2^>nul') do set "COMMIT_COUNT=%%c"
if not defined COMMIT_COUNT (
    echo [WARN] git commit count unavailable — using "-dev" without a number.
    set "APP_VERSION=%BASE_VERSION%-dev"
) else (
    set "APP_VERSION=%BASE_VERSION%-dev.%COMMIT_COUNT%"
)
:version_done

set "ISCC="
for /f "delims=" %%i in ('where iscc 2^>nul') do if not defined ISCC set "ISCC=%%i"
if not defined ISCC if exist "%USERPROFILE%\scoop\shims\iscc.exe" set "ISCC=%USERPROFILE%\scoop\shims\iscc.exe"
if not defined ISCC if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set "ISCC=C:\Program Files\Inno Setup 6\ISCC.exe"
if not defined ISCC (
    echo [WARN] Inno Setup (ISCC.exe) not found — skipping installer build.
    goto :skip_installer
)

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
