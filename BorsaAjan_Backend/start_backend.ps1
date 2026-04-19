# ============================================================================
# Borsa Ajan Backend - Startup Script for PowerShell
# ============================================================================
# Usage: .\start_backend.ps1
# Or with custom port: .\start_backend.ps1 -Port 8080
# ============================================================================

param(
    [int]$Port = 8000,
    [string]$Host = "127.0.0.1"
)

# Get script directory (where this .ps1 file is located)
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Change to the repository root (BorsaAjan_Backend)
Set-Location $ScriptDir

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Borsa Ajan Backend - Starting Server" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Check if GOOGLE_API_KEY is set
if (-not $env:GOOGLE_API_KEY) {
    # Try to load from .env file if it exists
    $envFile = Join-Path $ScriptDir ".env"
    if (Test-Path $envFile) {
        Write-Host "[INFO] Loading environment from .env file..." -ForegroundColor Yellow
        Get-Content $envFile | ForEach-Object {
            if ($_ -match "^\s*([^#][^=]+)=(.+)$") {
                $name = $matches[1].Trim()
                $value = $matches[2].Trim()
                # Remove quotes if present
                $value = $value -replace '^["'']|["'']$', ''
                [Environment]::SetEnvironmentVariable($name, $value, "Process")
                Write-Host "  Set: $name" -ForegroundColor DarkGray
            }
        }
    }
    
    # Check again after loading .env
    if (-not $env:GOOGLE_API_KEY) {
        Write-Host ""
        Write-Host "[ERROR] GOOGLE_API_KEY is not set!" -ForegroundColor Red
        Write-Host ""
        Write-Host "Please set it using one of these methods:" -ForegroundColor Yellow
        Write-Host "  1. Set environment variable:" -ForegroundColor White
        Write-Host '     $env:GOOGLE_API_KEY = "your-api-key-here"' -ForegroundColor Gray
        Write-Host ""
        Write-Host "  2. Create a .env file in this directory with:" -ForegroundColor White
        Write-Host '     GOOGLE_API_KEY=your-api-key-here' -ForegroundColor Gray
        Write-Host ""
        Write-Host "Get your API key from: https://aistudio.google.com/apikey" -ForegroundColor Cyan
        Write-Host ""
        exit 1
    }
}

Write-Host "[OK] GOOGLE_API_KEY is set" -ForegroundColor Green
Write-Host "[OK] Working directory: $ScriptDir" -ForegroundColor Green
Write-Host ""

# Check if Python is available
try {
    $pythonVersion = python --version 2>&1
    Write-Host "[OK] Python: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Python is not installed or not in PATH" -ForegroundColor Red
    exit 1
}

# Check if uvicorn is available
try {
    $uvicornCheck = python -c "import uvicorn; print(uvicorn.__version__)" 2>&1
    Write-Host "[OK] Uvicorn: $uvicornCheck" -ForegroundColor Green
} catch {
    Write-Host "[WARN] Uvicorn not found, installing..." -ForegroundColor Yellow
    pip install uvicorn[standard]
}

Write-Host ""
Write-Host "Starting server on http://${Host}:${Port}" -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop" -ForegroundColor DarkGray
Write-Host ""

# Start uvicorn with the correct module path
python -m uvicorn borsaajan_backend.main:app --reload --host $Host --port $Port
