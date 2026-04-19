@echo off
echo ========================================
echo   BORSA AJANI WEB - BASLATILIYOR
echo ========================================
echo.

cd /d "%~dp0BorsaAjani_Web"

echo Aktif dizin: %CD%
echo.
echo .NET version kontrol ediliyor...
dotnet --version
echo.

echo Web uygulamasi baslatiliyor...
echo Port: http://localhost:5000 (veya https://localhost:5001)
echo.
echo Durdurmak icin: CTRL+C
echo.

dotnet run --urls "http://localhost:5000"

pause
