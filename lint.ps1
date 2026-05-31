# Run lint + type-check on the enikk project
$ErrorActionPreference = "Stop"
Push-Location $PSScriptRoot

Write-Host "--- ruff ---"
.\.venv\Scripts\python.exe -m ruff check .

Write-Host "--- mypy ---"
.\.venv\Scripts\python.exe -m mypy enikk/ tests/

Pop-Location