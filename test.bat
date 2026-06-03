@echo off
REM Run pytest on the enikk project
pushd "%~dp0"

echo --- pytest ---
.venv\Scripts\python.exe -m pytest tests/ -v %*
if errorlevel 1 goto :error

popd
exit /b 0

:error
popd
exit /b 1
