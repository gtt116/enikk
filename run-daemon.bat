@echo off
REM Run enikk daemon with administrator privileges
pushd "%~dp0"

REM Check if running as administrator
net session >nul 2>&1
if errorlevel 1 (
    echo Requesting administrator privileges...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

.venv\Scripts\python.exe -m enikk
popd
