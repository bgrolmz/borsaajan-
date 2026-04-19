# Borsa Ajanı Backend

Türkiye borsası ve kripto analizi için AI destekli backend servisi. Google Gemini API kullanır.

## 🚀 Hızlı Başlatma

### PowerShell ile (Önerilen)

```powershell
cd BorsaAjan_Backend
.\start_backend.ps1
```

### Manuel Başlatma

```powershell
cd BorsaAjan_Backend
$env:GOOGLE_API_KEY = "your-api-key-here"
python -m uvicorn borsaajan_backend.main:app --reload --host 127.0.0.1 --port 8000
```

Backend http://localhost:8000 adresinde çalışacak.  
API dokümantasyonu: http://localhost:8000/docs

---

## 📋 Kurulum

### 1. Python Environment

```bash
cd BorsaAjan_Backend
python -m venv venv

# Windows PowerShell:
.\venv\Scripts\Activate.ps1

# Windows CMD:
venv\Scripts\activate.bat
```

### 2. Paketleri Yükle

```bash
pip install -r requirements.txt
```

### 3. API Key Ayarla

**Yöntem A: .env dosyası (Önerilen)**

`BorsaAjan_Backend` klasöründe `.env` dosyası oluştur:

```env
GOOGLE_API_KEY=your_actual_api_key_here
```

**Yöntem B: Environment Variable**

```powershell
$env:GOOGLE_API_KEY = "your-api-key-here"
```

> ⚠️ **GÜVENLİK:** API key'i asla koda yazmayın veya Git'e commit etmeyin!

### 4. Backend'i Başlat

```bash
python -m uvicorn borsaajan_backend.main:app --reload --host 127.0.0.1 --port 8000
```

---

## 📁 Proje Yapısı

```
BorsaAjan_Backend/
├── borsaajan_backend/          # Ana Python paketi
│   ├── __init__.py             # Paket tanımı
│   ├── main.py                 # FastAPI endpoints
│   ├── logic.py                # İş mantığı ve Gemini entegrasyonu
│   ├── database.py             # SQLite veritabanı katmanı
│   ├── data/                   # Veritabanı dosyaları (otomatik oluşur)
│   │   └── borsa.db            # SQLite veritabanı
│   └── services/               # Yardımcı servisler
│       ├── alert_system.py
│       └── ...
├── .env                        # API keys (Git'e eklenmez)
├── requirements.txt            # Python bağımlılıkları
├── start_backend.ps1           # PowerShell başlatma scripti
└── README.md
```

---

## 🔧 Veritabanı

Veritabanı dosyası (`borsa.db`) şu konumda saklanır:

```
borsaajan_backend/data/borsa.db
```

Bu konum `__file__` bazlı olduğu için:
- ✅ Working directory değişse bile aynı DB kullanılır
- ✅ Restart sonrası veri kaybı olmaz
- ✅ Farklı terminallerden çalıştırılsa bile aynı DB'ye erişilir

### Özel DB Konumu (Opsiyonel)

```powershell
$env:BORSA_DB_PATH = "C:\MyData\borsa.db"
```

---

## 🔌 API Endpoints

| Endpoint | Method | Açıklama |
|----------|--------|----------|
| `/ai-insight/{symbol}` | GET | AI analizi (Gemini) |
| `/market-data/{symbol}` | GET | Piyasa verileri (offline) |
| `/portfolio/list` | GET | Portföy listesi |
| `/portfolio/add` | POST | Portföye ekle |
| `/mentor-chat` | POST | AI mentor sohbeti |
| `/docs` | GET | API dokümantasyonu |

---

## 🐛 Sorun Giderme

### "No module named borsaajan_backend"

```powershell
# Doğru dizinden çalıştırın:
cd BorsaAjan_Backend
python -m uvicorn borsaajan_backend.main:app --reload
```

### "GOOGLE_API_KEY not set"

```powershell
# .env dosyası oluşturun veya:
$env:GOOGLE_API_KEY = "your-key"
```

### ImportError (database fonksiyonları)

Tüm database fonksiyonları `borsaajan_backend/database.py` içinde tanımlıdır:
- `init_db`, `get_conn`
- `add_to_portfolio`, `remove_from_portfolio`, `get_portfolio`
- `add_portfolio_transaction` (mentor chat için)
- `save_analysis`, `get_last_analysis`, `get_all_history`
- `get_user_profile`, `update_user_profile`
- `get_notifications`

### JSON Parse Hatası

Gemini JSON hatalarında:
1. İlk parse denemesi
2. `{...}` arasını çıkarıp tekrar deneme
3. Tek bir düşük-token "JSON düzelt" çağrısı
4. Fallback (12 saat kapatma YOK - sadece quota 429'da)

---

## 📊 Gemini Entegrasyonu

- **Model:** gemini-flash-latest
- **JSON Mode:** `response_mime_type="application/json"` (strict)
- **Temperature:** 0.2 (deterministik çıktı)
- **Max Tokens:** 3500 (detaylı analiz için)
- **Quota Koruma:** Günlük limit + 429 durumunda 12 saat bekleme

---

---

## 🐳 Docker Deployment (24/7 Cloud-Ready)

### Local Development with Docker Compose

1. **Create `.env` file** in `BorsaAjan_Backend/`:
```env
GOOGLE_API_KEY=your_actual_api_key_here
DB_PATH=/app/data/borsa.db
TZ=Europe/Istanbul
QUICK_SCHEDULE_TIMES=09:00,21:00
NEWS_INTERVAL_MINUTES=15
BACKUP_KEEP_DAYS=14
TELEGRAM_BOT_TOKEN=your_telegram_token
TELEGRAM_CHAT_ID=your_chat_id
```

2. **Start services**:
```bash
cd BorsaAjan_Backend
docker compose up -d
```

3. **View logs**:
```bash
docker compose logs -f backend
```

4. **Stop services**:
```bash
docker compose down
```

### Deploy on VPS (Docker)

1. **Clone repository** and navigate to backend:
```bash
git clone <repo-url>
cd Borsa_Projem/BorsaAjan_Backend
```

2. **Create `.env` file** with all required variables (see above)

3. **Start with Docker Compose**:
```bash
docker compose up -d
```

4. **Verify persistence**:
```bash
# Check that data directory exists and has DB file
ls -la data/
ls -la data/backups/
```

5. **Check health**:
```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

### Deploy on Render/Railway/Fly.io

#### Render.com

1. **Create new Web Service**
2. **Build Command**: `pip install -r requirements.txt`
3. **Start Command**: `uvicorn borsaajan_backend.main:app --host 0.0.0.0 --port $PORT`
4. **Environment Variables**: Add all from `.env` file
5. **Persistent Disk**: Mount `/app/data` for SQLite persistence

#### Railway.app

1. **New Project** → Deploy from GitHub
2. **Add Environment Variables** (from `.env`)
3. **Add Volume**: Mount `/app/data` for persistence
4. **Start Command**: `uvicorn borsaajan_backend.main:app --host 0.0.0.0 --port $PORT`

#### Fly.io

1. **Create `fly.toml`**:
```toml
app = "borsa-ajan"
primary_region = "iad"

[build]
  dockerfile = "Dockerfile"

[[services]]
  internal_port = 8000
  protocol = "tcp"

[[mounts]]
  source = "borsa_data"
  destination = "/app/data"
```

2. **Deploy**:
```bash
fly launch
fly volumes create borsa_data --size 1
fly deploy
```

### Volume Persistence

**Important**: The SQLite database and backups are stored in `/app/data/` (or `./data/` in docker-compose).

- **Docker Compose**: Volume mounted at `./data:/app/data`
- **Cloud Platforms**: Use persistent volumes/disks mounted at `/app/data`
- **Verify**: Check that `data/borsa.db` and `data/backups/` exist after restart

### Health Endpoints

- **`GET /health`**: Simple health check
  ```bash
  curl http://localhost:8000/health
  # Returns: {"ok": true, "timestamp": "..."}
  ```

- **`GET /ready`**: Readiness check (verifies DB connectivity)
  ```bash
  curl http://localhost:8000/ready
  # Returns: {"ok": true, "db": "ok", "timestamp": "..."}
  # Or 503 if DB is not ready
  ```

### Scheduled Jobs

The system runs the following scheduled jobs:

1. **QUICK Portfolio Analysis**: 2x daily (configurable via `QUICK_SCHEDULE_TIMES`)
2. **News Check**: Every 15 minutes (configurable via `NEWS_INTERVAL_MINUTES`)
3. **Daily Backup**: 02:00 daily (keeps last N days via `BACKUP_KEEP_DAYS`)
4. **Outcome Backfill**: 03:00 daily (computes 1/3/7-day forward returns)

**Check scheduler status**:
```bash
curl http://localhost:8000/notifications/scheduler/status
```

### Backup System

- **Location**: `/app/data/backups/borsa_YYYYMMDD.db`
- **Retention**: Last N days (default: 14, configurable via `BACKUP_KEEP_DAYS`)
- **Schedule**: Daily at 02:00 (configurable in code)
- **Manual backup**: Copy `data/borsa.db` to `data/backups/`

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_PATH` | `/app/data/borsa.db` | SQLite database path (absolute) |
| `TZ` | `Europe/Istanbul` | Timezone for scheduler |
| `QUICK_SCHEDULE_TIMES` | `09:00,21:00` | QUICK analysis schedule (comma-separated) |
| `NEWS_INTERVAL_MINUTES` | `15` | News check interval |
| `BACKUP_KEEP_DAYS` | `14` | Number of backup files to keep |
| `GOOGLE_API_KEY` | - | Required: Gemini API key |
| `TELEGRAM_BOT_TOKEN` | - | Optional: Telegram bot token |
| `TELEGRAM_CHAT_ID` | - | Optional: Telegram chat ID |

### Production Checklist

- [ ] `.env` file configured with all required variables
- [ ] Volume mounted at `/app/data` (or `./data` for docker-compose)
- [ ] Health endpoints responding (`/health`, `/ready`)
- [ ] Scheduler running (check `/notifications/scheduler/status`)
- [ ] Database integrity check passing (see startup logs)
- [ ] Backups directory exists and is writable
- [ ] Timezone set correctly (`TZ` env var)
- [ ] Port 8000 exposed (or configured port)

### Troubleshooting

**Scheduler not running**:
- Check logs: `docker compose logs backend`
- Verify `apscheduler` is installed
- Check timezone configuration

**Database not persisting**:
- Verify volume mount: `docker compose exec backend ls -la /app/data`
- Check `DB_PATH` environment variable
- Ensure `/app/data` directory is writable

**Health check failing**:
- Check database file exists: `ls -la data/borsa.db`
- Verify database integrity: Check startup logs for integrity check result
- Check file permissions

**Backups not created**:
- Verify `/app/data/backups` directory exists and is writable
- Check scheduler is running
- Review backup job logs in scheduler status

---

## 📝 Lisans

MIT License
