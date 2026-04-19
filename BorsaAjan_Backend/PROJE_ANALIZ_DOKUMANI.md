# BORSA AJANI BACKEND - TEKNİK ANALİZ DOKÜMANI

**Hazırlanma Tarihi:** 2025  
**Hedef Kitle:** Senior Backend Engineer  
**Amaç:** Projenin mimari yapısını, akışlarını ve mevcut durumunu anlatmak

---

## 1. GENEL MİMARİ ÖZET

### 1.1 Projenin Amacı
**Borsa Ajani**, hisse senedi ve kripto para analizi yapan bir AI destekli yatırım danışmanlık platformudur. Sistem:
- Gerçek zamanlı piyasa verilerini toplar (yfinance)
- Teknik ve temel analiz yapar
- AI (Google Gemini) ile stratejik öneriler üretir
- Portföy yönetimi ve analizi sağlar
- Chat tabanlı yatırım mentorluğu sunar
- Otomatik bildirimler gönderir (Telegram)

### 1.2 Ana Akış (Request → Logic → DB → Response)

```
Client Request (FastAPI)
    ↓
main.py (Endpoint Handler)
    ↓
logic.py (Business Logic)
    ├─→ Market Data Fetch (yfinance) → Fast Response
    ├─→ Technical Analysis (Local calculations)
    ├─→ News Analysis (Local heuristics + Optional LLM)
    ├─→ AI Analysis (Gemini API - Optional)
    └─→ Template Fallback (If LLM fails/disabled)
    ↓
database.py (SQLite Persistence)
    ├─→ Save analysis history
    ├─→ Portfolio CRUD
    ├─→ User profile
    └─→ Cache market bars
    ↓
Response (JSON)
```

**Önemli Not:** Sistem **hibrit** çalışır:
- **Hızlı endpoint'ler** (`/market-data`): LLM yok, sadece teknik veriler
- **Yavaş endpoint'ler** (`/ai-insight`): LLM opsiyonel (`use_llm` flag'i ile kontrol edilir)

### 1.3 AI / LLM Devreye Giriş Noktaları

LLM (Google Gemini) şu durumlarda devreye girer:

1. **`/ai-insight/{sembol}`** endpoint'i, `use_llm=1` parametresi ile çağrıldığında
2. **`/portfolio/analyze`** endpoint'i (her zaman LLM kullanır, fallback var)
3. **`/chat`** endpoint'i (her zaman LLM kullanır, fallback var)
4. **`/market/overview`** endpoint'i (her zaman LLM kullanır, fallback var)
5. **Haber analizi** (`get_news` fonksiyonu, `use_llm=1` ile batch LLM analizi)

**LLM Kullanılmayan Durumlar:**
- `use_llm=0` (default) → Template-based analiz
- LLM API hatası → Otomatik template fallback
- Günlük limit aşımı → Template fallback
- API key yok → Template fallback

---

## 2. DOSYA BAZLI AÇIKLAMA

### 2.1 `main.py` (726 satır)

**Sorumluluk:** FastAPI uygulaması, endpoint tanımları, CORS, scheduler başlatma

**Ana Fonksiyonlar:**
- `lifespan()`: Startup/shutdown event handler (DB init)
- `analiz_yap()`: Legacy endpoint (`/analiz/{sembol}`) - backward compatibility
- `market_data()`: Fast endpoint (`/market-data/{sembol}`) - LLM yok
- `ai_insight()`: Slow endpoint (`/ai-insight/{sembol}`) - LLM opsiyonel
- `portfolio_*()`: Portföy CRUD ve analiz endpoint'leri
- `chat_with_user()`: Chat mentor endpoint'i
- `market_overview()`: Günlük piyasa özeti

**Bağlantılı Dosyalar:**
- `logic.py` → Tüm business logic
- `database.py` → Veritabanı işlemleri
- `services/alert_system.py` → Bildirim sistemi

**Kritiklik:** ⭐⭐⭐⭐⭐ (Kritik - Tüm API trafiği buradan geçer)

**Özel Notlar:**
- Scheduler (APScheduler) başlatılıyor: Market summary (17:45, 20:30, 23:45) ve critical news check (15 dakikada bir)
- CORS açık (`allow_origins=["*"]`) - geliştirme için
- DB path `database.py`'den alınıyor (single source of truth)

---

### 2.2 `logic.py` (5879 satır)

**Sorumluluk:** Tüm business logic, AI entegrasyonu, teknik analiz, haber analizi, portföy analizi

**Ana Fonksiyonlar:**

#### LLM İşlemleri:
- `gemini_text()`: **Yerel heuristic** (LLM çağrısı YOK, keyword-based sentiment)
- `safe_gemini_call()`: Unified LLM çağrı wrapper (retry, error handling, budget tracking)
- `run_master_analysis()`: Ana LLM analiz fonksiyonu (structured output, schema validation)
- `build_template_analysis()`: LLM olmadan template-based analiz (deterministik)

#### Market Data:
- `get_market_data_fast()`: Hızlı piyasa verisi (fiyat, RSI, BB, MACD, chart)
- `get_technical_metrics()`: Teknik göstergeler hesaplama
- `calculate_deep_technicals()`: Golden cross, MACD signal, ATR
- `get_chart_data()`: Chart verisi (self-healing cache ile)

#### News Analysis:
- `get_news()`: Yahoo Finance RSS'den haber çekme, local heuristic analiz, opsiyonel batch LLM
- `analyze_news_batch_with_llm()`: Haberleri batch olarak LLM ile analiz etme
- `filter_critical_news_local()`: Yerel kritik haber filtreleme

#### Portfolio:
- `analyze_portfolio()`: Portföy analizi (LLM kullanır, fallback var)
- `backtest_lite()`: Portföy backtest (S&P500 ile karşılaştırma)
- `whale_watch()`: Kurumsal yatırımcı takibi

#### Chat:
- `chat_with_mentor()`: AI mentor chat (transaction extraction, context-aware)

#### Yardımcı Fonksiyonlar:
- `local_decision_engine()`: LLM olmadan karar verme (RSI, trend, volatility bazlı)
- `apply_policy_guardrails()`: Risk yönetimi kuralları (bearish haber varsa BUY engelleme)
- `build_level0_fallback_analysis()`: LLM başarısız olduğunda minimum fallback

**Bağlantılı Dosyalar:**
- `database.py` → Analiz kaydetme, portföy CRUD, memory context
- `schemas.py` → Gemini JSON schema tanımları
- `news_analyzer.py` → Yerel haber analizi (heuristic)

**Kritiklik:** ⭐⭐⭐⭐⭐ (Kritik - Tüm iş mantığı burada)

**Özel Notlar:**
- **Rate limiting:** Günlük 10 gerçek LLM çağrısı limiti (`DAILY_REAL_CALL_LIMIT`)
- **Budget tracking:** `log_llm_usage()` ile her LLM çağrısı kaydediliyor
- **Fallback stratejisi:** LLM başarısız olursa otomatik template'e geçiş
- **Self-healing cache:** Chart verisi eksikse otomatik tamamlama

---

### 2.3 `database.py` (1519 satır)

**Sorumluluk:** SQLite veritabanı katmanı, tüm CRUD işlemleri, cache yönetimi

**Ana Fonksiyonlar:**

#### DB Path Management:
- `get_db_path()`: Single source of truth - DB path belirleme (env var veya default)
- `get_connection()`: Connection helper (WAL mode, PRAGMA settings)

#### Analysis History:
- `save_analysis()`: Analiz kaydetme
- `get_last_analysis()`: Son analizi getirme
- `get_memory_context()`: AI için geçmiş analiz özetleri (memory context)
- `get_all_history()`: Tüm analiz geçmişi

#### Portfolio:
- `add_to_portfolio()`: Portföye ekleme/güncelleme (weighted average cost)
- `remove_from_portfolio()`: Portföyden çıkarma (partial/full)
- `get_portfolio()`: Portföy listesi
- `add_portfolio_transaction()`: İşlem kaydı (BUY/SELL)

#### Portfolio Analysis:
- `save_portfolio_analysis()`: Portföy analizi kaydetme
- `get_portfolio_analysis_history()`: Portföy analiz geçmişi

#### User Profile:
- `get_user_profile()`: Kullanıcı profil (risk profile, system instruction)
- `update_user_profile()`: Profil güncelleme

#### Notifications:
- `get_notifications()`: Bildirim listesi
- `should_send_notification()`: Cooldown ve deduplication kontrolü
- `log_notification()`: Bildirim loglama

#### Market Bars Cache:
- `get_cached_market_bars()`: Cache'den chart verisi
- `upsert_market_bars()`: Chart verisi cache'leme
- `get_missing_dates()`: Eksik tarihleri bulma (self-healing için)

#### LLM Usage Tracking:
- `log_llm_usage()`: LLM kullanım kaydı (budget tracking)
- `get_monthly_llm_usage()`: Aylık kullanım istatistikleri

**Veritabanı Tabloları:**

1. **`analysis_history`**: Analiz geçmişi (symbol, mode, raw_prompt, raw_response, summary, risk_level, full_analysis_json, price_at_analysis)
2. **`portfolio`**: Portföy (symbol, avg_cost, quantity)
3. **`portfolio_transactions`**: İşlem geçmişi (symbol, quantity, price, transaction_type)
4. **`portfolio_analysis_history`**: Portföy analiz geçmişi
5. **`user_profile`**: Kullanıcı profili (settings_json)
6. **`notifications`**: Bildirimler (timestamp, title, message, type)
7. **`notification_log`**: Bildirim cooldown takibi (symbol, event_key, importance_score)
8. **`market_bars`**: Chart verisi cache (symbol, mode, timeframe, bar_date, OHLCV)
9. **`llm_usage_log`**: LLM kullanım logları (model, purpose, tokens, cost)

**Bağlantılı Dosyalar:**
- `main.py` → Startup'ta `init_db()` çağrılıyor
- `logic.py` → Tüm fonksiyonlar buradan çağrılıyor

**Kritiklik:** ⭐⭐⭐⭐⭐ (Kritik - Tüm veri burada)

**Özel Notlar:**
- **DB Path Strategy:** `BORSA_DB_PATH` env var veya `<repo_root>/data/borsa.db` (default)
- **WAL Mode:** Write-Ahead Logging (concurrency için)
- **Self-healing:** Chart cache eksikse otomatik tamamlama
- **Cooldown System:** Aynı haber için 30 dakika cooldown, deduplication

---

### 2.4 `news_analyzer.py` (244 satır)

**Sorumluluk:** Yerel haber analizi (LLM YOK, sadece heuristic rules)

**Ana Fonksiyon:**
- `analyze_news_item()`: Keyword-based sentiment analizi
  - Importance score (0-100)
  - Impact (bullish/bearish/neutral)
  - Time horizon (intraday/short/long)
  - Reasons (max 3)

**Analiz Kriterleri:**
- Critical negative keywords (bankrupt, lawsuit, ban, fraud) → Yüksek skor, bearish
- Earnings keywords → Orta-yüksek skor
- Rating keywords (upgrade/downgrade) → Orta skor
- Regulatory keywords (SEC, investigation) → Yüksek skor, bearish
- Insider activity → Yüksek skor
- Sentiment keywords (bullish/bearish) → Skor artışı
- Numeric data bonus → +10 skor
- Source credibility bonus → +15 skor (Reuters, Bloomberg, WSJ)

**Bağlantılı Dosyalar:**
- `logic.py` → `get_news()` fonksiyonu bu modülü kullanıyor

**Kritiklik:** ⭐⭐⭐⭐ (Yüksek - LLM olmadan haber analizi için kritik)

**Özel Notlar:**
- **LLM yok:** Tamamen deterministik, hızlı
- **Batch LLM opsiyonel:** `get_news(use_llm=1)` ile batch LLM analizi yapılabilir

---

### 2.5 `schemas.py` (334 satır)

**Sorumluluk:** Gemini structured output için JSON schema tanımları

**Ana Schema'lar:**
- `MASTER_ANALYSIS_SCHEMA`: Tam analiz schema (summary, technical, fundamental, sentiment, scenarios, strategy, risk_score, confidence_score)
- `NEW_ANALYSIS_SCHEMA`: Kompakt schema (headline_tr, verdict, confidence, thesis_bullets, risk_bullets, levels, scenarios, news_summary, what_to_watch)

**Özellikler:**
- Gemini-compatible (sadece type, properties, required, items)
- Validation rules yok (maxLength, enum, min/max) - backend'de kontrol ediliyor
- UI contract compliance için tasarlanmış

**Bağlantılı Dosyalar:**
- `logic.py` → `run_master_analysis()` bu schema'ları kullanıyor

**Kritiklik:** ⭐⭐⭐ (Orta - Schema değişirse UI bozulabilir)

---

### 2.6 `test_api.py` (108 satır)

**Sorumluluk:** Policy guardrails test fonksiyonu

**Ana Fonksiyon:**
- `test_policy_guardrails_bearish()`: Bearish haber durumunda BUY önerisinin engellenmesini test eder

**Kritiklik:** ⭐⭐ (Düşük - Test dosyası)

---

## 3. AI / LLM AKIŞI

### 3.1 LLM Çağrıları Nereden Başlıyor?

**Entry Points:**
1. **`/ai-insight/{sembol}?use_llm=1`** → `get_ai_insight()` → `run_master_analysis()`
2. **`/portfolio/analyze`** → `analyze_portfolio()` → `safe_gemini_call()`
3. **`/chat`** → `chat_with_mentor()` → `gemini_text()` (ama bu yerel heuristic, gerçek LLM değil!)
4. **`/market/overview`** → `gemini_text()` (yerel heuristic)
5. **`get_news(symbol, use_llm=1)`** → `analyze_news_batch_with_llm()`

**Önemli:** `gemini_text()` fonksiyonu **gerçek LLM çağrısı yapmıyor!** Sadece keyword-based sentiment analizi yapıyor. Bu bir bug veya eksiklik olabilir.

### 3.2 `use_llm` Flag Kontrolü

**Kontrol Noktaları:**

1. **`/ai-insight` endpoint:**
   ```python
   if use_llm == 0:
       # Template-based (NO LLM)
       master_analysis = build_template_analysis(...)
   else:
       # LLM-based (use_llm=1)
       master_analysis = run_master_analysis(...)
   ```

2. **`get_news()` fonksiyonu:**
   ```python
   if use_llm == 1 and filtered_news:
       # Batch LLM analysis
       analyzed_news = analyze_news_batch_with_llm(...)
   ```

**Default Değer:** `use_llm=0` (LLM kapalı)

### 3.3 Fallback / Template / Local Heuristic Akışı

**Akış Şeması:**

```
LLM Çağrısı Gerekiyor mu?
    ↓
use_llm == 0? → EVET → build_template_analysis() → Deterministik template
    ↓
HAYIR (use_llm == 1)
    ↓
safe_gemini_call() → Başarılı? → EVET → LLM sonucu
    ↓
HAYIR (Hata)
    ↓
build_template_analysis() → Fallback template
```

**Template Analysis Özellikleri:**
- `local_decision_engine()` kullanır (RSI, trend, volatility bazlı)
- `build_template_analysis()` ile zengin template oluşturur
- `apply_policy_guardrails()` ile risk kuralları uygulanır
- UI contract'ı tam olarak doldurur (tüm alanlar mevcut)

**Local Heuristic (Haber Analizi):**
- `news_analyzer.py` → Keyword-based analiz
- LLM yok, hızlı, deterministik

### 3.4 Neden Bazı Endpoint'lerde LLM Devreye Girmiyor?

**LLM Devreye Girmeyen Endpoint'ler:**

1. **`/market-data/{sembol}`**: Hızlı endpoint, LLM yok (sadece teknik veriler)
2. **`/ai-insight/{sembol}`** (default): `use_llm=0` → Template-based
3. **`/chat`**: `gemini_text()` çağrılıyor ama bu **gerçek LLM değil**, yerel heuristic

**LLM Her Zaman Devreye Giren Endpoint'ler:**
- `/portfolio/analyze` → `safe_gemini_call()` (fallback var)
- `/market/overview` → `gemini_text()` (ama bu yerel heuristic, gerçek LLM değil!)

**Sorun:** `/chat` ve `/market/overview` endpoint'leri `gemini_text()` kullanıyor ama bu fonksiyon gerçek LLM çağrısı yapmıyor. Bu bir bug veya eksiklik olabilir.

---

## 4. VERİTABANI AKIŞI

### 4.1 Tablolar ve Veri Tipleri

**Analiz Verileri:**
- **`analysis_history`**: Her analiz kaydediliyor (raw_prompt, raw_response, summary, full_analysis_json)
- **`portfolio_analysis_history`**: Portföy analizleri ayrı tabloda

**Portföy Verileri:**
- **`portfolio`**: Aktif portföy (symbol, avg_cost, quantity)
- **`portfolio_transactions`**: İşlem geçmişi (BUY/SELL)

**Kullanıcı Verileri:**
- **`user_profile`**: Risk profili, system instruction (JSON formatında)

**Cache Verileri:**
- **`market_bars`**: Chart verisi cache (self-healing için)
- **`notification_log`**: Bildirim cooldown takibi

**Log Verileri:**
- **`notifications`**: Bildirim geçmişi
- **`llm_usage_log`**: LLM kullanım ve maliyet takibi

### 4.2 Cache Mantığı

**Chart Data Cache:**
- `market_bars` tablosunda OHLCV verileri saklanıyor
- `get_cached_market_bars()` ile cache'den okunuyor
- `get_missing_dates()` ile eksik tarihler bulunuyor
- Eksik tarihler otomatik tamamlanıyor (self-healing)

**Notification Cooldown:**
- `notification_log` tablosunda cooldown takibi
- Aynı `event_key` için 30 dakika cooldown
- Günlük deduplication (aynı haber iki kez gönderilmez)

### 4.3 Restart Sonrası Veri Kaybı Neden Yaşanmış Olabilir?

**Olası Nedenler:**

1. **DB Path Değişikliği:**
   - `BORSA_DB_PATH` env var değiştiyse farklı DB dosyası kullanılıyor olabilir
   - Default path: `<repo_root>/data/borsa.db`
   - Eğer çalışma dizini değiştiyse farklı DB'ye yazıyor olabilir

2. **DB Dosyası Silindi:**
   - `init_db()` sadece tabloları oluşturur, veri silmez
   - Ama DB dosyası silinirse tüm veri kaybolur

3. **Transaction Commit Sorunu:**
   - WAL mode kullanılıyor, commit edilmemiş transaction'lar kaybolabilir
   - Ama kodda `conn.commit()` her yerde mevcut

4. **Multiple DB Files:**
   - Kodda "stray DB" kontrolü var (CWD'deki `borsa.db` dosyası)
   - Eğer birden fazla DB dosyası varsa, yanlış dosyaya yazıyor olabilir

**Öneri:** DB path'i log'layarak kontrol et (`get_db_path()` fonksiyonu log atıyor)

---

## 5. PORTFÖY SİSTEMİ

### 5.1 Portföy Verisi Nerede Tutuluyor?

**SQLite Tablosu:** `portfolio`
- `symbol`: Hisse sembolü (UNIQUE)
- `avg_cost`: Ortalama maliyet (weighted average)
- `quantity`: Miktar
- `created_at`, `updated_at`: Timestamp'ler

**İşlem Geçmişi:** `portfolio_transactions`
- Her BUY/SELL işlemi kaydediliyor
- `add_portfolio_transaction()` ile otomatik portföy güncelleniyor

### 5.2 `/portfolio/analyze` Çağrısı Akışı

```
/portfolio/analyze endpoint
    ↓
get_portfolio() → DB'den portföy listesi
    ↓
Her hisse için:
    - get_technical_metrics() → Fiyat, RSI
    - calculate_fair_value() → Adil değer
    - get_news() → Haberler (5 saniye delay)
    ↓
Portföy özeti oluşturuluyor (allocation, P/L, risk)
    ↓
LLM prompt hazırlanıyor (sert, gerçekçi hedge fund yöneticisi)
    ↓
safe_gemini_call() → LLM analizi (JSON response)
    ↓
Fallback? → HAYIR → LLM sonucu
    ↓
EVET → Basit template analizi
    ↓
save_portfolio_analysis() → DB'ye kaydet
    ↓
Response
```

**Önemli Notlar:**
- Her hisse için 5 saniye delay (rate limit koruması)
- LLM her zaman çağrılıyor (fallback var)
- Sektör konsantrasyonu analizi yapılıyor (Tech %80+ → Yüksek risk uyarısı)
- Market opportunity bulma (portföyde olmayan tech hisse önerisi)

### 5.3 Neden AI Portföy Analizi Zayıf veya Fallback'te Kalıyor Olabilir?

**Olası Nedenler:**

1. **LLM API Hatası:**
   - Budget limit aşıldı
   - API key geçersiz
   - Rate limit aşıldı
   - Network hatası

2. **Prompt Çok Uzun:**
   - Portföy büyükse prompt çok uzun olabilir
   - Token limit aşımı

3. **JSON Parse Hatası:**
   - LLM JSON döndürmüyor
   - Schema validation başarısız

4. **Fallback Template Zayıf:**
   - `analyze_portfolio()` fallback'i çok basit (sadece allocation ve P/L)
   - LLM olmadan derin analiz yapılamıyor

**Kod İncelemesi:**
```python
# analyze_portfolio() - Line 5446-5454
try:
    analysis_json = safe_gemini_call(prompt, response_mode="json", max_retries=1, purpose="portfolio_analysis")
except GeminiCallError:
    analysis_json = None

if analysis_json is None:
    print("⚠️ Using fallback data")
    # Fallback: Return basic portfolio analysis without AI
    return {
        "success": True,
        "message": FALLBACK_AI_MESSAGE,  # Generic mesaj
        ...
    }
```

**Sorun:** Fallback çok basit, sadece generic mesaj döndürüyor. LLM başarısız olursa kullanıcıya anlamlı bir analiz sunulmuyor.

---

## 6. CHAT / MENTOR AKIŞI

### 6.1 `/chat` Endpoint'i Hangi Bilgileri Context Olarak Alıyor?

**Context Data Yapısı:**

1. **Stock Context** (`context_data["type"] == "stock"`):
   - `symbol`: Hisse sembolü
   - `price`: Mevcut fiyat
   - `rsi`: RSI değeri
   - `fair_value`: Adil değer
   - `news_summary`: Son haberler özeti

2. **Portfolio Context** (`context_data["type"] == "portfolio"`):
   - `total_value`: Toplam değer
   - `total_pnl`: Toplam P/L
   - `holdings_count`: Hisse sayısı

**Context String Oluşturma:**
```python
if context_data["type"] == "stock":
    context_str = f"""
MEVCUT HİSSE BİLGİLERİ:
- Sembol: {symbol}
- Mevcut Fiyat: ${price:.2f}
- RSI: {rsi:.1f}
- Adil Değer: {fair_value_str}
- Son Haberler: {news_summary[:200]}
"""
```

### 6.2 LLM Neden Çoğu Zaman Çalışmıyor Gibi Görünüyor?

**Sorun:** `chat_with_mentor()` fonksiyonu `gemini_text()` çağrıyor ama bu fonksiyon **gerçek LLM çağrısı yapmıyor!**

**Kod İncelemesi:**
```python
# logic.py - Line 247-290
def gemini_text(prompt: str) -> dict:
    """
    Local, deterministic function for generating Turkish news comments.
    NO Gemini API calls - uses keyword-based sentiment detection.
    """
    print("[gemini_text] Local heuristic (no API call).")
    # ... keyword-based sentiment analysis ...
    return {"fallback": False, "text": comment}
```

**Sonuç:** `/chat` endpoint'i gerçek LLM kullanmıyor, sadece keyword-based sentiment analizi yapıyor. Bu bir bug veya eksiklik.

**Çözüm Önerisi:** `gemini_text()` fonksiyonu gerçek LLM çağrısı yapmalı veya `safe_gemini_call()` kullanılmalı.

### 6.3 Chat'in Şu Anki Rolü Ne?

**Mevcut Durum:**
- **Transaction Extraction:** Kullanıcı mesajından BUY/SELL işlemi çıkarılıyor (LLM ile)
- **Portfolio Update:** İşlem otomatik portföye ekleniyor
- **Response Generation:** `gemini_text()` ile keyword-based yanıt (gerçek LLM değil)

**İdeal Durum:**
- Context-aware AI mentor
- Gerçek LLM ile derin analiz
- Eğitici ve spesifik tavsiyeler

**Gap:** Chat şu anda template-based, gerçek mentor değil.

---

## 7. MEVCUT DURUM DEĞERLENDİRMESİ

### 7.1 Sistem Şu An Teknik Olarak Sağlam mı?

**Güçlü Yönler:**
- ✅ Fallback mekanizması iyi (LLM başarısız olursa template'e geçiş)
- ✅ Rate limiting var (günlük 10 LLM çağrısı)
- ✅ Budget tracking var (LLM kullanım loglanıyor)
- ✅ Self-healing cache (chart verisi otomatik tamamlanıyor)
- ✅ Policy guardrails (risk yönetimi kuralları)
- ✅ Database path management (single source of truth)
- ✅ WAL mode (concurrency için)

**Zayıf Yönler:**
- ❌ `/chat` endpoint'i gerçek LLM kullanmıyor (`gemini_text()` yerel heuristic)
- ❌ `/market/overview` endpoint'i gerçek LLM kullanmıyor
- ❌ Portföy analizi fallback'i çok basit (generic mesaj)
- ❌ Multiple DB files riski (stray DB kontrolü var ama yeterli değil)
- ❌ `use_llm` flag default 0 (LLM kapalı, kullanıcı bilmiyor olabilir)

### 7.2 En Büyük Mimari Darboğazlar

1. **LLM Entegrasyonu Tutarsızlığı:**
   - Bazı endpoint'ler gerçek LLM kullanıyor (`/ai-insight`, `/portfolio/analyze`)
   - Bazı endpoint'ler yerel heuristic kullanıyor (`/chat`, `/market/overview`)
   - Bu tutarsızlık kullanıcı deneyimini bozuyor

2. **Fallback Mekanizması Eksik:**
   - Portföy analizi fallback'i çok basit
   - Chat fallback'i yok (sadece error mesajı)

3. **Rate Limiting Kısıtlayıcı:**
   - Günlük 10 LLM çağrısı çok düşük
   - Production için yetersiz

4. **DB Path Yönetimi:**
   - Multiple DB files riski
   - Restart sonrası veri kaybı olasılığı

### 7.3 En Riskli Dosya/Akış

**En Riskli Dosya: `logic.py`**
- 5879 satır (çok büyük)
- Tüm business logic tek dosyada
- Refactor edilmesi zor
- Test edilmesi zor

**En Riskli Akış: LLM Çağrıları**
- `safe_gemini_call()` → `run_master_analysis()` → Schema validation
- Çok fazla hata noktası (API, JSON parse, schema validation)
- Fallback mekanizması her durumu kapsamıyor

**En Riskli Endpoint: `/chat`**
- Gerçek LLM kullanmıyor (bug)
- Kullanıcı beklentisi yüksek (AI mentor)
- Transaction extraction LLM ile yapılıyor ama response generation yerel heuristic

---

## 8. ÖZET VE ÖNERİLER

### 8.1 Kritik Bulgular

1. **`gemini_text()` fonksiyonu gerçek LLM çağrısı yapmıyor** → `/chat` ve `/market/overview` endpoint'leri etkileniyor
2. **Portföy analizi fallback'i çok basit** → LLM başarısız olursa kullanıcıya anlamlı analiz sunulmuyor
3. **`use_llm` flag default 0** → LLM kapalı, kullanıcı bilmiyor olabilir
4. **Multiple DB files riski** → Restart sonrası veri kaybı olasılığı

### 8.2 Acil Düzeltilmesi Gerekenler

1. **`gemini_text()` fonksiyonu gerçek LLM çağrısı yapmalı** veya `safe_gemini_call()` kullanılmalı
2. **Portföy analizi fallback'i geliştirilmeli** (en azından allocation ve P/L analizi)
3. **DB path logging artırılmalı** (her DB işleminde path log'lanmalı)
4. **`use_llm` flag default değeri dokümante edilmeli** veya 1 yapılmalı

### 8.3 Uzun Vadeli İyileştirmeler

1. **`logic.py` refactor edilmeli** (modüler yapı, service layer)
2. **Rate limiting artırılmalı** veya dinamik yapılmalı
3. **Fallback mekanizması geliştirilmeli** (her endpoint için anlamlı fallback)
4. **Test coverage artırılmalı** (özellikle LLM akışları)

---

**Doküman Sonu**

