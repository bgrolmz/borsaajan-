@echo off
echo ========================================
echo   BORSA AJANI FRONTEND - BASLATILIYOR
echo ========================================
echo.

cd /d "%~dp0BorsaAjani_App\BorsaAjani_App"

echo Aktif dizin: %CD%
echo.
echo .NET version kontrol ediliyor...
dotnet --version
echo.

echo Frontend baslatiliyor...
echo.
echo Durdurmak icin: CTRL+C
echo.

dotnet run -f net9.0-windows10.0.19041.0

pause
