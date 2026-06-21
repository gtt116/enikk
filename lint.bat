@echo off
REM Run lint + type-check on the enikk project
pushd "%~dp0"

echo --- ruff ---
.venv\Scripts\python.exe -m ruff check .
if errorlevel 1 goto :error

echo --- mypy ---
.venv\Scripts\python.exe -m mypy enikk/ tests/
if errorlevel 1 goto :error

echo --- html check ---
.venv\Scripts\python.exe scripts\check_html.py enikk\static\index.html
if errorlevel 1 goto :error

popd
exit /b 0

:error
popd
exit /b 1
