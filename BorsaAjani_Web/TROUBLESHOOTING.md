# Blazor Server Troubleshooting

## Butonlar Çalışmıyor - Çözüm Adımları

### 1. Tarayıcı Konsolunu Açma
- **Chrome/Edge**: `Ctrl + Shift + J` veya `F12`
- **Firefox**: `Ctrl + Shift + K` veya `F12`
- **Sağ tık** → "Inspect" veya "Öğeyi İncele"

### 2. Kontrol Edilecekler

#### A. JavaScript Dosyaları Yüklendi mi?
Tarayıcı konsolunda şu script'in yüklendiğini kontrol edin:
```html
<script src="_framework/blazor.web.js"></script>
```

#### B. SignalR Bağlantısı
Konsolda şu hataları kontrol edin:
- `Failed to connect to SignalR`
- `WebSocket connection failed`
- `blazor.web.js` yüklenemedi

#### C. Render Mode
`Home.razor` dosyasında şu satır olmalı:
```razor
@rendermode @(RenderMode.InteractiveServer)
```

### 3. Test Sayfası
`http://localhost:5000/test` adresine gidin ve "Click Me" butonuna tıklayın.
- Buton çalışıyorsa → Render mode çalışıyor, sorun Home.razor'da
- Buton çalışmıyorsa → Render mode/SignalR sorunu

### 4. Backend Kontrolü
Backend'in çalıştığından emin olun:
```batch
CALISTIR_BACKEND.bat
```
Backend: `http://127.0.0.1:8000`

### 5. Yeniden Başlatma
1. Uygulamayı durdurun (Ctrl+C)
2. `dotnet clean`
3. `dotnet build`
4. `dotnet run --urls "http://localhost:5000"`

### 6. Tarayıcı Cache Temizleme
- `Ctrl + Shift + Delete` → Cache temizle
- Veya `Ctrl + F5` (Hard Refresh)
