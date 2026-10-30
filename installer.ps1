param (
    [string]$InstallPath = "."
)
Set-Location $InstallPath

Write-Host "=== Quill-Cowork Installer ===" -ForegroundColor Cyan

# Helper function to refresh environment variables
function Refresh-Path {
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
}

# 1. Check Python
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Installing Python 3.11..." -ForegroundColor Yellow
    winget install -e --id Python.Python.3.11 --silent --accept-package-agreements --accept-source-agreements
    Refresh-Path
}

# 2. Check Rust
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    Write-Host "Installing Rust..." -ForegroundColor Yellow
    winget install -e --id Rustlang.Rustup --silent --accept-package-agreements --accept-source-agreements
    Refresh-Path
}

# 3. Check Ollama
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Write-Host "Downloading and installing Ollama..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" -OutFile "OllamaSetup.exe"
    Start-Process -FilePath ".\OllamaSetup.exe" -ArgumentList "/SILENT" -Wait
    Remove-Item "OllamaSetup.exe"
    Refresh-Path
}

# 4. Start Ollama & Pull Models
Write-Host "Starting Ollama and downloading models (this will take a while depending on your internet)..." -ForegroundColor Yellow
if (-not (Get-Process ollama -ErrorAction SilentlyContinue)) {
    Start-Process "ollama" -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 5
}

ollama pull huihui_ai/qwen3-abliterated:4b
ollama pull huihui_ai/qwen3-abliterated:8b
ollama pull huihui_ai/deepseek-r1-abliterated:8b
ollama pull richardyoung/agents-a1-4b-heretic

# 5. Setup Python environment
Write-Host "Setting up Python virtual environment..." -ForegroundColor Yellow
python -m venv backend\venv
.\backend\venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r backend\requirements.txt

# 6. Build Rust binary
Write-Host "Building Rust core..." -ForegroundColor Yellow
cd backend
python quill_rust.py build --force
cd ..

# 7. Create start script
Write-Host "Creating launch script..." -ForegroundColor Yellow
$startScript = @"
@echo off
cd /d "%~dp0"
call backend\venv\Scripts\activate.bat
cd backend
start http://localhost:8000
python main.py
pause
"@
Set-Content -Path "start_quill.bat" -Value $startScript

# 8. Create Modelfiles
Write-Host "Building custom Ollama models..." -ForegroundColor Yellow
ollama create quill -f backend\Modelfile
ollama create quill-7b -f backend\Modelfile.7b
ollama create quill-7b-reason -f backend\Modelfile.7b-reason
ollama create quill-cpu-fast -f backend\Modelfile.cpu-fast
ollama create quill-cpu-smart -f backend\Modelfile.cpu-smart

Write-Host "=== Installation Complete ===" -ForegroundColor Green
Write-Host "To start Quill, double-click start_quill.bat" -ForegroundColor Green