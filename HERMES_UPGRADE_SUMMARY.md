# 🚀 Hermes Upgrade: Context-Aware Mentor with Watchlist & Telegram Alerts

## ✅ Implementation Summary

All requested features have been successfully implemented and integrated into the existing codebase.

---

## 📋 Features Implemented

### 1. ✅ **Watchlist Logic** (Already Existed + Verified)
- **Database Table**: `watched_symbols` table with columns: `id`, `symbol`, `mode`, `created_at`, `updated_at`
- **Functions** (in `database.py`):
  - `get_watched_symbols()` - Get all watched symbols
  - `add_watched_symbol(symbol, mode)` - Add symbol to watchlist
  - `remove_watched_symbol(symbol)` - Remove symbol from watchlist
  - `get_watched_symbols_only()` - Get symbol set for Hermes processing

### 2. ✅ **Hermes News Impact Engine** (Enhanced with Gemini)
**File**: `news_pipeline.py`

**Enhancements**:
- LLM now analyzes news and returns:
  - `market_impact`: POSITIVE | NEGATIVE | NEUTRAL
  - `impact_reason`: Short explanation (max 80 chars)
  - `importance_score`: 0-100 (Gemini's assessment)
  - `what_happened`, `why_it_matters`, `mentor_action`, `risk`

**Key Changes**:
```python
# Line 220-285: Enhanced enrich_news_with_llm()
- Added importance_score to LLM prompt
- Validates and extracts importance_score from LLM response
- Falls back to local score if LLM score is invalid

# Line 306-330: Validation logic
- Ensures importance_score is integer 0-100
- Logs final importance score for debugging
```

### 3. ✅ **Telegram Critical Alerts** (Impact > 80)
**File**: `news_pipeline.py`

**Implementation**:
```python
# Line 666-688: _process_notifications()
- Checks if confidence >= 80
- Sets notification_type = "CRITICAL" for high-impact news
- Adds 🚨 CRITICAL prefix to title
- Sends Telegram notification via send_and_save_notification()
```

**Notification Flow**:
1. News item analyzed by Gemini → `importance_score` extracted
2. If `importance_score >= 80` → `notification_type = "CRITICAL"`
3. Telegram message sent with urgency indicator
4. Saved to database with CRITICAL type

### 4. ✅ **Context-Aware Chat** (Last Decision Integration)
**File**: `logic.py`

**Enhancements**:
```python
# Line 9264-9295: Stock context building
- Fetches last mentor decision using get_last_decision_for_symbol()
- Extracts: decision, verdict, price_at_analysis, confidence, created_at, key_reasoning
- Calculates price change since last decision
- Injects context into chat prompt

# Line 9381-9418: System prompt update
- Added CONTEXT-AWARE rule
- Instructs LLM to compare current situation with last decision
- Example: "Geçen sefer AL dedik $150'den. Şimdi $165'te (+10%). RSI 75'e yükseldi, kar kilitleme zamanı."
```

**Context Injection Example**:
```
MEVCUT HİSSE BİLGİLERİ:
- Sembol: NVDA
- Mevcut Fiyat: $165.00
- RSI: 75.0
- Adil Değer: $150.00
- Son Haberler: Earnings beat expectations...
- Son Mentor Kararı: AL (BUY) - Güven: 85%
- Karar Zamanı: 2026-01-05 14:30:00
- Karar Fiyatı: $150.00 → Şimdi: $165.00 (+10.0%)
- Gerekçe: Strong technical breakout, RSI oversold, positive earnings catalyst
```

### 5. ✅ **Watchlist Management Endpoints** (Already Existed + Verified)
**File**: `main.py`

**Endpoints**:
- `GET /hermes/watchlist` - Get all watched symbols
- `POST /hermes/watchlist/add?symbol=NVDA&mode=STOCK` - Add symbol
- `DELETE /hermes/watchlist/remove/{symbol}` - Remove symbol
- `POST /hermes/news/process` - Manually trigger Hermes processing

### 6. ✅ **Scheduled Hermes Processing** (Already Configured)
**File**: `main.py`

**Scheduler Configuration**:
```python
# Line 419-447: run_hermes_news_processing()
- Runs every 30 minutes (configurable)
- Calls process_news_pipeline(mode="DEEP", use_watchlist=True)
- Only processes watched symbols (resource-efficient)
```

---

## 🔄 Data Flow

### Hermes Smart Watchlist Flow:
```
1. User adds symbol to watchlist
   ↓
2. Scheduler triggers every 30 minutes
   ↓
3. Fetch news for watched symbols only
   ↓
4. Local scoring (fast)
   ↓
5. LLM enrichment (if score >= 60)
   - Gemini analyzes: market_impact, importance_score, impact_reason
   ↓
6. If importance_score >= 80:
   - Send CRITICAL Telegram notification
   - Save to DB with CRITICAL type
   ↓
7. Store analysis in news_analysis_history table
```

### Context-Aware Chat Flow:
```
1. User asks about a stock (e.g., "NVDA nasıl?")
   ↓
2. Fetch last mentor decision from DB
   - get_last_decision_for_symbol(symbol, mode)
   ↓
3. Build context with:
   - Current price, RSI, news
   - Last decision, price at decision, reasoning
   - Price change since last decision
   ↓
4. Inject context into LLM prompt
   ↓
5. LLM compares current vs. last decision
   - "Geçen sefer AL dedik $150'den. Şimdi $165'te (+10%)..."
   ↓
6. Return context-aware response
```

---

## 🧪 Testing Guide

### Test 1: Add Symbol to Watchlist
```bash
curl -X POST "http://localhost:8000/hermes/watchlist/add?symbol=NVDA&mode=STOCK"
```
**Expected Response**:
```json
{
  "success": true,
  "message": "Added NVDA to watchlist",
  "symbol": "NVDA",
  "mode": "STOCK"
}
```

### Test 2: Get Watchlist
```bash
curl "http://localhost:8000/hermes/watchlist"
```
**Expected Response**:
```json
{
  "success": true,
  "watchlist": [
    {
      "id": 1,
      "symbol": "NVDA",
      "mode": "STOCK",
      "created_at": "2026-01-10 12:00:00",
      "updated_at": "2026-01-10 12:00:00"
    }
  ],
  "count": 1
}
```

### Test 3: Manually Trigger Hermes News Processing
```bash
curl -X POST "http://localhost:8000/hermes/news/process"
```
**Expected Response**:
```json
{
  "success": true,
  "processed_count": 5,
  "news_items": [...],
  "message": "Processed 5 news items for watched symbols"
}
```

### Test 4: Context-Aware Chat
**Prerequisites**: 
1. Add NVDA to watchlist
2. Run analysis on NVDA first to create a decision in DB

```bash
curl -X POST "http://localhost:8000/chat" \
  -H "Content-Type: application/json" \
  -d '{
    "user_message": "NVDA nasıl?",
    "context_data": {
      "type": "stock",
      "symbol": "NVDA",
      "mode": "STOCK",
      "price": 165.0,
      "rsi": 75.0
    }
  }'
```

**Expected Response** (should include reference to last decision):
```json
{
  "success": true,
  "response": "Decision: REDUCE\n\nGeçen sefer AL dedik $150'den. Şimdi $165'te (+10%). RSI 75'e yükseldi, kar kilitleme zamanı.\n\nGerekçeler:\n- Fiyat %10 yükseldi, hedef tutturuldu\n- RSI 75 (aşırı alım bölgesi)\n- Kademeli kar kilitleme mantıklı\n\nAksiyonlar:\n- %30-50 pozisyon sat\n- Stop-loss'u $155'e çek\n- Geri kalan pozisyonu tut\n\nRisk: RSI yüksekse düzeltme riski var, kademeli kâr kilitleme düşün.",
  "context_used": true
}
```

### Test 5: Check Telegram Notifications
**Prerequisites**: Set environment variables:
```bash
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

**Trigger Critical News**:
1. Add a high-volatility stock to watchlist (e.g., TSLA)
2. Wait for scheduler or manually trigger: `POST /hermes/news/process`
3. Check Telegram for critical alerts (importance_score >= 80)

**Expected Telegram Message**:
```
🚨 CRITICAL: Tesla announces surprise earnings beat

📢 **TSLA**
Impact: 🟢 Positive
Reason: Earnings beat expectations, strong guidance for Q2

_Mentor: Şirket kazanç beklentilerini aştı, servis segmentinde güçlü büyüme. Olumlu sürpriz fiyatı destekleyebilir._

_Borsa Ajanı Mentor_
```

---

## 📊 Database Schema Changes

### Existing Tables Used:
1. **`watched_symbols`** (Hermes watchlist)
   - `id`, `symbol`, `mode`, `created_at`, `updated_at`

2. **`news_analysis_history`** (News storage with LLM enrichment)
   - Stores: `market_impact`, `impact_reason`, `importance_score`, `what_happened`, `why_it_matters`, `mentor_action`, `risk_note`

3. **`analysis_history`** (Mentor decisions)
   - Used by `get_last_decision_for_symbol()` for context-aware chat

4. **`notifications`** (Telegram notification log)
   - Stores all sent notifications with type (ALERT, CRITICAL, SUMMARY)

---

## 🔧 Configuration

### Environment Variables:
```bash
# Telegram (Required for notifications)
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Gemini API (Required for LLM enrichment)
GOOGLE_API_KEY=your_gemini_api_key

# Scheduler Configuration (Optional)
NEWS_INTERVAL_MINUTES=15          # Critical news check interval
NOTIF_COOLDOWN_MINUTES=30         # Notification cooldown
NOTIF_MAX_PER_DAY_PER_SYMBOL=5    # Max notifications per symbol per day
```

### Scheduler Jobs:
- **Hermes News Processing**: Every 30 minutes
- **Critical News Check**: Every 15 minutes (configurable)
- **Market Summary**: 17:45, 20:30, 23:45 daily
- **Portfolio Analysis**: 09:00, 21:00 daily (configurable)

---

## 🎯 Key Benefits

1. **Resource Efficiency**: Only processes news for watched symbols (saves API limits)
2. **Critical Alerts**: Automatic Telegram notifications for high-impact news (score >= 80)
3. **Context Awareness**: Chat responses reference past decisions for consistency
4. **Smart Filtering**: Local scoring first, LLM enrichment only for important news
5. **Deduplication**: Prevents duplicate notifications with cooldown system
6. **Learning**: All decisions and news stored for future improvement

---

## 📝 Next Steps (Optional Enhancements)

1. **Watchlist Auto-Population**: Automatically add portfolio symbols to watchlist
2. **Impact Scoring Tuning**: Adjust importance_score threshold based on user feedback
3. **Multi-Language Support**: Translate Telegram notifications to English/Turkish
4. **Watchlist Groups**: Create watchlist categories (e.g., "Tech", "Energy")
5. **Historical Performance**: Track how often Gemini's impact predictions were correct

---

## 🐛 Troubleshooting

### Issue: Telegram notifications not sending
**Solution**: Check environment variables:
```python
import os
print(os.getenv("TELEGRAM_BOT_TOKEN"))  # Should not be None
print(os.getenv("TELEGRAM_CHAT_ID"))    # Should not be None
```

### Issue: Context-aware chat not showing last decision
**Solution**: Ensure symbol has at least one analysis in `analysis_history` table:
```sql
SELECT * FROM analysis_history WHERE symbol = 'NVDA' ORDER BY created_at DESC LIMIT 1;
```

### Issue: Hermes not processing news
**Solution**: Check scheduler status:
```bash
curl "http://localhost:8000/notifications/scheduler/status"
```

### Issue: LLM enrichment failing
**Solution**: Check Gemini API key and daily limit:
```python
import os
print(os.getenv("GOOGLE_API_KEY"))  # Should not be None
# Check logs for "API quota exceeded" messages
```

---

## 📚 Code References

### Key Functions Modified:
1. `news_pipeline.py::enrich_news_with_llm()` - Lines 220-337
2. `news_pipeline.py::_process_notifications()` - Lines 620-690
3. `logic.py::chat_with_mentor()` - Lines 9240-9479
4. `database.py::get_last_decision_for_symbol()` - Lines 895-999

### Key Endpoints:
- `GET /hermes/watchlist` - Line 827
- `POST /hermes/watchlist/add` - Line 840
- `DELETE /hermes/watchlist/remove/{symbol}` - Line 862
- `POST /hermes/news/process` - Line 883
- `POST /chat` - Line 1067

---

## ✅ Completion Checklist

- [x] Watchlist table and functions (already existed)
- [x] Hermes Impact Engine with Gemini (enhanced)
- [x] Telegram critical alerts (importance_score >= 80)
- [x] Context-aware chat with last decision
- [x] Watchlist management endpoints (already existed)
- [x] Scheduled Hermes processing (already configured)
- [x] Documentation and testing guide

---

**Status**: ✅ **ALL FEATURES IMPLEMENTED AND READY FOR TESTING**

**Estimated Time to Test**: 15-20 minutes
**Estimated Time to Production**: Ready now (pending environment variable setup)
