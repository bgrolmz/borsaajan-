@echo off
echo ========================================
echo   BORSA AJANI BACKEND - BASLATILIYOR
echo ========================================
echo.

cd /d "%~dp0BorsaAjan_Backend\borsaajan_backend"

echo Aktif dizin: %CD%
echo.

REM Python environment'i aktif et (conda)
call C:\Users\msi-nb\anaconda3\Scripts\activate.bat Python_Pycharm

echo Python environment kontrol ediliyor...
python --version
echo.

echo Gerekli paketler kontrol ediliyor...
python -c "import uvicorn; print('uvicorn: OK')" 2>nul || echo "uvicorn bulunamadi, yukleniyor..." && pip install uvicorn fastapi
echo.

echo Backend baslatiliyor...
echo Port: http://127.0.0.1:8000
echo.
echo Durdurmak icin: CTRL+C
echo.

python -m uvicorn main:app --reload --port 8000

pause
