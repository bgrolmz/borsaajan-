---
description: Test workflow to verify Claude is active
---

# Borsa Ajanı v2.0 — Master Context & Rules

## 1. Proje Kimliği
- **Amaç:** Amerikan borsası haberleri + teknik analiz (RSI, SMA, Bollinger) → Gemini AI analiz → SQLite + Telegram + Blazor terminal
- **Backend:** Python FastAPI → Railway (prod: https://borsaajan-production.up.railway.app)
- **Frontend:** Blazor Server (BorsaAjani_Web) → ngrok üzerinden lokal / Railway deploy bekliyor
- **GitHub:** https://github.com/bgrolmz/borsaajan-
- **Deploy:** git push → Railway otomatik deploy (sadece BorsaAjan_Backend)
- **Pipeline:** n8n Schedule → Yahoo RSS → Filter → HTTP POST → FastAPI → yfinance → Gemini → SQLite + Telegram

## 2. Kritik Konfigürasyon
- **Webhook:** POST /webhook/news-signal | Header: X-Webhook-Secret | Body: {hisse_adi, haber_metni, kaynak}
- **Model:** gemini-1.5-flash (dynamic discovery ile)
- **DB:** Railway'de /app/data/borsa.db
- **n8n:** localhost:5678 (lokal)
- **Railway Vars:** GOOGLE_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, MAX_NEWS_PER_BATCH=3, NEWS_INTERVAL_MINUTES=30

## 3. Kesinlikle Uyulacak Kurallar
- Yorum satırı ekleme
- Fallback/sahte veri mantığı ekleme
- yfinance backfill döngüsü ekleme
- .env dosyasına dokunma
- Gereksiz dosya tarama — sadece sorunun kaynağına odaklan
- Token israfı yapma — /compact'tan önce bu dosyayı güncelle

## 4. Ajan Rolleri
İsteğe göre rol seç:
- **Interaction Engineer:** Blazor, Tailwind, UI binding, razor hataları
- **Systems Architect:** FastAPI, JSON şema, veri akışı, API entegrasyonu

## 5. İletişim Kuralları
- Türkçe, kısa, net konuş
- "Anladım, yapıyorum" yazma — direkt yap
- Hata varsa önce kök sebebi söyle, sonra fix uygula
- Her oturum başında bu dosyayı oku, bağlamı kur

## 6. Çözülmüş Sorunlar (Referans)
- ✅ gemini-2.0-flash → gemini-1.5-flash (rate limit)
- ✅ VIX f-string syntax hatası
- ✅ Webhook 503 → 200 skipped (exception handling)
- ✅ JSON truncation → max_output_tokens=2048, İngilizce prompt
- ✅ Dynamic model discovery (client.models.list())
- ✅ n8n expression {{ $json.title }} resolve sorunu
- ✅ Telegram bildirimleri Türkçe formatına alındı
- ✅ Keyword-based sembol tespiti (NVDA, AAPL, TSLA vb.)
- ✅ Frontend HttpClient → Railway backend bağlantısı (Program.cs)

## 7. Bekleyen Sorunlar
- ❌ BorsaAjani_Web Dockerfile build hatası (Railway frontend deploy)
  - Hata: "/BorsaAjani_Web/BorsaAjani_Web.csproj not found"
  - Sebep: Root Directory /BorsaAjani_Web iken Dockerfile path çiftleniyor
  - Fix: COPY ["BorsaAjani_Web.csproj", "./"] olmalı (zaten denendi, tekrar dene)
- ❌ Fiyat/RSI N/A geliyor — haber başlığı sembol olarak geçiyor, yfinance bulamıyor
- ❌ Frontend Railway'de değil, ngrok üzerinden çalışıyor

## 8. Sonraki Adımlar (Öncelik Sırası)
1. BorsaAjani_Web Dockerfile düzelt → Railway frontend deploy
2. Fiyat/RSI verisini düzelt (sembol tespiti iyileştir)
3. n8n'i de Railway'e taşı (tam otonom sistem)

## 9. /compact Protokolü
Bu dosyayı /compact'tan ÖNCE güncelle:
- Yeni çözülen sorunları bölüm 6'ya taşı
- Yeni hataları bölüm 7'ye ekle
- Sonraki adımları bölüm 8'de güncelle
- Commit: git add . && git commit -m "chore: update claude.md context" && git push