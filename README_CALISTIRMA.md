# 🚀 Borsa Ajani - Çalıştırma Kılavuzu

## Hızlı Başlatma

### Yöntem 1: Otomatik (Önerilen)
1. **CALISTIR_HER_IKISI.bat** dosyasına çift tıklayın
   - Backend ve Frontend otomatik başlar
   - Backend yeni bir pencere açılır
   - Frontend ana pencerede çalışır

### Yöntem 2: Manuel (Ayrı Pencereler)

#### Backend'i Başlat:
1. **CALISTIR_BACKEND.bat** dosyasına çift tıklayın (CMD için)
   - Veya PowerShell'de:
   ```powershell
   cd BorsaAjan_Backend\borsaajan_backend
   C:\Users\msi-nb\anaconda3\envs\Python_Pycharm\python.exe -m uvicorn main:app --reload --port 8000
   ```
   - Veya PowerShell script'i kullanın: `.\CALISTIR_BACKEND_PS1.ps1`
   - Backend: http://127.0.0.1:8000

#### Frontend'i Başlat:
1. **CALISTIR_FRONTEND.bat** dosyasına çift tıklayın
   - Veya PowerShell'de:
   ```powershell
   cd BorsaAjani_App\BorsaAjani_App
   dotnet run -f net9.0-windows10.0.19041.0
   ```

## ⚠️ Önemli Notlar

1. **Backend ÖNCE başlatılmalı!**
   - Frontend backend'e bağlanır
   - Backend çalışmazsa frontend hata verir

2. **Python Environment:**
   - `Python_Pycharm` environment aktif olmalı
   - Gerekli paketler yüklü olmalı:
     ```powershell
     pip install fastapi uvicorn yfinance feedparser google-generativeai python-dotenv pandas numpy matplotlib mplfinance
     ```

3. **.NET SDK:**
   - .NET 9.0 SDK yüklü olmalı
   - `dotnet --version` ile kontrol edin

## 🔧 Sorun Giderme

### Backend çalışmıyor:
- Python environment'ı kontrol edin
- Port 8000 kullanımda mı? (başka bir uygulama kullanıyor olabilir)
- Gerekli paketler yüklü mü?

### Frontend çalışmıyor:
- Backend çalışıyor mu? (http://127.0.0.1:8000)
- .NET SDK yüklü mü?
- Proje restore edildi mi? (`dotnet restore`)

## 📝 Test Endpoints

Backend çalıştıktan sonra tarayıcıda test edin:
- Ana sayfa: http://127.0.0.1:8000
- Test chart: http://127.0.0.1:8000/test/chart/NVDA
- Analiz: http://127.0.0.1:8000/analiz/NVDA?mode=STOCK&maliyet=176
