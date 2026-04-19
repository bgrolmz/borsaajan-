@echo off
echo ========================================
echo   BORSA AJANI - BACKEND + FRONTEND
echo   Her ikisini birden baslat
echo ========================================
echo.

echo BACKEND baslatiliyor (Yeni pencere)...
start "BorsaAjani Backend" cmd /k "cd /d %~dp0BorsaAjan_Backend\borsaajan_backend && call C:\Users\msi-nb\anaconda3\Scripts\activate.bat Python_Pycharm && echo Backend: http://127.0.0.1:8000 && echo. && python -m uvicorn main:app --reload --port 8000"

timeout /t 3 /nobreak >nul

echo.
echo FRONTEND baslatiliyor...
cd /d "%~dp0BorsaAjani_App\BorsaAjani_App"
dotnet run -f net9.0-windows10.0.19041.0

pause
