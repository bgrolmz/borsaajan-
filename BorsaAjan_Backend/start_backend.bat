@echo off
REM ============================================
REM Borsa Ajanı Backend Başlatma Scripti
REM ============================================
REM Bu script Python_Pycharm conda environment'ını aktif eder
REM ve backend sunucusunu başlatır.
REM ============================================

echo.
echo ============================================
echo   Borsa Ajanı Backend Başlatılıyor...
echo ============================================
echo.

REM Change to this script's directory (the backend root)
cd /d "%~dp0"
echo [1/3] Çalışma dizini: %CD%
echo.

REM Use the conda environment's Python directly (no need to activate)
echo [2/3] Python_Pycharm conda environment kullanılıyor...

REM Direct path to Python in the conda environment
set PYTHON_EXE=C:\Users\msi-nb\anaconda3\envs\Python_Pycharm\python.exe

if not exist "%PYTHON_EXE%" (
    echo [HATA] Python executable bulunamadı: %PYTHON_EXE%
    pause
    exit /b 1
)

echo [OK] Python executable bulundu.
echo Python yolu: %PYTHON_EXE%
echo.

REM Verify Python version and location
echo [3/3] Python versiyonu kontrol ediliyor...
"%PYTHON_EXE%" --version
if errorlevel 1 (
    echo [HATA] Python bulunamadı veya çalıştırılamadı!
    pause
    exit /b 1
)
echo.

REM Verify uvicorn is available
echo Uvicorn kontrol ediliyor...
"%PYTHON_EXE%" -m pip show uvicorn >nul 2>&1
if errorlevel 1 (
    echo [UYARI] Uvicorn bulunamadı. Yükleniyor...
    "%PYTHON_EXE%" -m pip install uvicorn --quiet
)

echo.
echo ============================================
echo   Backend sunucusu başlatılıyor...
echo   URL: http://localhost:8000
echo   Durdurmak için: CTRL+C
echo ============================================
echo.

REM Start the backend server using the conda environment's Python
"%PYTHON_EXE%" -m uvicorn borsaajan_backend.main:app --reload --host 0.0.0.0 --port 8000

REM If we get here, the server stopped
echo.
echo Backend sunucusu durdu.
pause

