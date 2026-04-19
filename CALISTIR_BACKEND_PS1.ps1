# PowerShell script for starting Backend
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  BORSA AJANI BACKEND - BASLATILIYOR" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$backendPath = Join-Path $scriptPath "BorsaAjan_Backend\borsaajan_backend"
Set-Location $backendPath

Write-Host "Aktif dizin: $PWD" -ForegroundColor Yellow
Write-Host ""

# Conda environment path
$condaEnvPath = "C:\Users\msi-nb\anaconda3\envs\Python_Pycharm"
$pythonExe = Join-Path $condaEnvPath "python.exe"

# Check if Python exists
if (Test-Path $pythonExe) {
    Write-Host "Python environment bulundu: $pythonExe" -ForegroundColor Green
    Write-Host "Python version:" -ForegroundColor Yellow
    & $pythonExe --version
    Write-Host ""
    
    # Check uvicorn
    Write-Host "Gerekli paketler kontrol ediliyor..." -ForegroundColor Yellow
    $uvicornCheck = & $pythonExe -c "import uvicorn; print('OK')" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "uvicorn bulunamadi, yukleniyor..." -ForegroundColor Yellow
        & $pythonExe -m pip install uvicorn fastapi
    } else {
        Write-Host "uvicorn: OK" -ForegroundColor Green
    }
    Write-Host ""
    
    Write-Host "Backend baslatiliyor..." -ForegroundColor Green
    Write-Host "Port: http://127.0.0.1:8000" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Durdurmak icin: CTRL+C" -ForegroundColor Yellow
    Write-Host ""
    
    # Start uvicorn
    & $pythonExe -m uvicorn main:app --reload --port 8000
} else {
    Write-Host "HATA: Python environment bulunamadi!" -ForegroundColor Red
    Write-Host "Yol: $pythonExe" -ForegroundColor Red
    Write-Host ""
    Write-Host "Lutfen conda environment'in dogru yuklu oldugundan emin olun." -ForegroundColor Yellow
    Write-Host "Environment adi: Python_Pycharm" -ForegroundColor Yellow
    pause
}
