# One command setup without Docker, for Windows PowerShell.
#
#     .\scripts\run.ps1
#
# Creates a virtual environment, installs the project, and starts the service
# on http://127.0.0.1:8000. Safe to run again: it reuses what is already there.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

if (-not (Test-Path ".venv")) {
    Write-Host "Creating .venv"
    python -m venv .venv
}

$VenvPython = ".venv\Scripts\python.exe"

Write-Host "Installing dependencies"
& $VenvPython -m pip install --quiet --upgrade pip
& $VenvPython -m pip install --quiet -e ".[dev]"

$OllamaHost = if ($env:INSIGHTS_OLLAMA_HOST) { $env:INSIGHTS_OLLAMA_HOST } else { "http://localhost:11434" }
$Model = if ($env:INSIGHTS_OLLAMA_MODEL) { $env:INSIGHTS_OLLAMA_MODEL } else { "qwen2.5-coder:7b" }

try {
    Invoke-WebRequest -Uri "$OllamaHost/api/tags" -TimeoutSec 2 -UseBasicParsing | Out-Null
} catch {
    Write-Host ""
    Write-Host "WARNING: no model server answered at $OllamaHost" -ForegroundColor Yellow
    Write-Host "         Start one with:  ollama serve"
    Write-Host "         And pull the model with:  ollama pull $Model"
    Write-Host "         The service will still start. Ingestion works; questions will return 503."
    Write-Host ""
}

$BindHost = if ($env:INSIGHTS_HOST) { $env:INSIGHTS_HOST } else { "127.0.0.1" }
$Port = if ($env:INSIGHTS_PORT) { $env:INSIGHTS_PORT } else { "8000" }
Write-Host "Starting on http://${BindHost}:${Port}"
& $VenvPython -m insights
