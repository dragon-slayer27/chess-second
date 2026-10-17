# Sets up Second on Windows: Stockfish in .\bin, a Python virtual environment, and the Gemma model in Ollama.
# Run from the project folder:  powershell -ExecutionPolicy Bypass -File scripts\setup-windows.ps1
param(
    [string]$Model = "gemma4:e4b-it-qat"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "1/3 Stockfish" -ForegroundColor Cyan
$engine = Get-ChildItem "$root\bin" -Filter "stockfish*.exe" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $engine) {
    New-Item -ItemType Directory -Force -Path "$root\bin" | Out-Null
    $zip = Join-Path $env:TEMP "stockfish.zip"
    Invoke-WebRequest "https://github.com/official-stockfish/Stockfish/releases/latest/download/stockfish-windows-x86-64-universal.zip" -OutFile $zip
    Expand-Archive $zip "$root\bin" -Force
    $engine = Get-ChildItem "$root\bin" -Filter "stockfish*.exe" -Recurse | Select-Object -First 1
}
Write-Host "    $($engine.FullName)"

Write-Host "2/3 Python packages" -ForegroundColor Cyan
if (-not (Test-Path "$root\.venv")) { python -m venv .venv }
& "$root\.venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
& "$root\.venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt

Write-Host "3/3 Gemma in Ollama" -ForegroundColor Cyan
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "    Ollama is not installed. Get it from https://ollama.com/download, then run this script again." -ForegroundColor Yellow
    exit 1
}
ollama pull $Model

Write-Host ""
Write-Host "Done. Start Second with:" -ForegroundColor Green
Write-Host "    .\.venv\Scripts\python.exe -m second serve"
Write-Host "and open http://127.0.0.1:8000"
