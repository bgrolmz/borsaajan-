# 🚀 Hermes Quick Start Guide

## What's New?

Hermes is now a **Context-Aware Mentor** with:
- 📋 **Smart Watchlist**: Only analyze symbols you care about
- 🤖 **Gemini Impact Engine**: AI-powered news analysis with impact scoring
- 📱 **Telegram Alerts**: Instant notifications for critical news (score ≥ 80)
- 🧠 **Context Memory**: Chat remembers past decisions and compares them

---

## 🏃 Quick Start (5 Minutes)

### Step 1: Set Environment Variables
```bash
# Required for Telegram notifications
export TELEGRAM_BOT_TOKEN="your_bot_token"
export TELEGRAM_CHAT_ID="your_chat_id"

# Required for AI analysis
export GOOGLE_API_KEY="your_gemini_api_key"
```

### Step 2: Start Backend
```bash
cd BorsaAjan_Backend
uvicorn borsaajan_backend.main:app --reload
```

### Step 3: Add Symbols to Watchlist
```bash
# Add NVDA to watchlist
curl -X POST "http://localhost:8000/hermes/watchlist/add?symbol=NVDA&mode=STOCK"

# Add more symbols
curl -X POST "http://localhost:8000/hermes/watchlist/add?symbol=TSLA&mode=STOCK"
curl -X POST "http://localhost:8000/hermes/watchlist/add?symbol=AAPL&mode=STOCK"
```

### Step 4: Trigger News Processing (or wait for scheduler)
```bash
curl -X POST "http://localhost:8000/hermes/news/process"
```

### Step 5: Check Telegram for Alerts 📱
- Critical news (score ≥ 80) will be sent automatically
- Format: 🚨 CRITICAL: [Title] + Impact + Reason

---

## 📚 API Reference

### Watchlist Management

#### Get Watchlist
```bash
GET /hermes/watchlist
```
**Response**:
```json
{
  "success": true,
  "watchlist": [
    {
      "id": 1,
      "symbol": "NVDA",
      "mode": "STOCK",
      "created_at": "2026-01-10 12:00:00"
    }
  ],
  "count": 1
}
```

#### Add Symbol
```bash
POST /hermes/watchlist/add?symbol=NVDA&mode=STOCK
```
**Response**:
```json
{
  "success": true,
  "message": "Added NVDA to watchlist",
  "symbol": "NVDA",
  "mode": "STOCK"
}
```

#### Remove Symbol
```bash
DELETE /hermes/watchlist/remove/NVDA
```
**Response**:
```json
{
  "success": true,
  "message": "Removed NVDA from watchlist"
}
```

### News Processing

#### Manual Trigger
```bash
POST /hermes/news/process
```
**Response**:
```json
{
  "success": true,
  "processed_count": 5,
  "news_items": [
    {
      "symbol": "NVDA",
      "confidence": 85,
      "market_impact": "POSITIVE",
      "impact_reason": "Earnings beat expectations",
      "mentor_summary": "Strong quarterly results...",
      "what_happened": "NVDA reported Q4 earnings...",
      "why_it_matters": "Revenue growth signals...",
      "mentor_action": "Hold current position",
      "risk": "Watch for profit-taking"
    }
  ]
}
```

### Context-Aware Chat

#### Ask About a Stock
```bash
POST /chat
Content-Type: application/json

{
  "user_message": "NVDA nasıl?",
  "context_data": {
    "type": "stock",
    "symbol": "NVDA",
    "mode": "STOCK",
    "price": 165.0,
    "rsi": 75.0
  }
}
```

**Response** (with context):
```json
{
  "success": true,
  "response": "Decision: REDUCE\n\nGeçen sefer AL dedik $150'den. Şimdi $165'te (+10%). RSI 75'e yükseldi, kar kilitleme zamanı.\n\nGerekçeler:\n- Fiyat %10 yükseldi, hedef tutturuldu\n- RSI 75 (aşırı alım bölgesi)\n- Kademeli kar kilitleme mantıklı\n\nAksiyonlar:\n- %30-50 pozisyon sat\n- Stop-loss'u $155'e çek\n\nRisk: RSI yüksekse düzeltme riski var.",
  "context_used": true
}
```

---

## 🔔 Telegram Notification Examples

### Critical Alert (Score ≥ 80)
```
🚨 CRITICAL: Tesla announces surprise earnings beat

📢 **TSLA**
Impact: 🟢 Positive
Reason: Earnings beat expectations, strong guidance for Q2

_Mentor: Şirket kazanç beklentilerini aştı, servis segmentinde güçlü büyüme._

_Borsa Ajanı Mentor_
```

### Regular Alert (Score < 80)
```
📢 **NVDA**
Impact: 🟡 Neutral
Reason: Routine product announcement, minimal market impact

_Mentor: Yeni ürün lansmanı, fiyat üzerinde kısa vadeli etki beklenmez._

_Borsa Ajanı Mentor_
```

---

## ⚙️ Configuration

### Scheduler Settings (Optional)
Edit `main.py` or set environment variables:

```bash
# News processing interval (default: 30 minutes)
HERMES_INTERVAL_MINUTES=30

# Notification cooldown (default: 30 minutes)
NOTIF_COOLDOWN_MINUTES=30

# Max notifications per symbol per day (default: 5)
NOTIF_MAX_PER_DAY_PER_SYMBOL=5
```

### Critical Alert Threshold
Default: `importance_score >= 80`

To change, edit `news_pipeline.py`:
```python
# Line 669
notification_type = "CRITICAL" if confidence >= 80 else "ALERT"
```

---

## 🧪 Testing

### Run Automated Test Suite
```bash
python test_hermes_flow.py
```

**What it tests**:
1. ✅ Add symbol to watchlist
2. ✅ Get watchlist
3. ✅ Process news with Gemini
4. ✅ Context-aware chat
5. ✅ Check notifications
6. ✅ Remove symbol (cleanup)

**Expected Output**:
```
🚀 HERMES END-TO-END TEST SUITE
============================================================
  TEST 1: Add Symbol to Watchlist
============================================================
✅ PASS: Symbol added to watchlist

============================================================
  TEST 2: Get Watchlist
============================================================
✅ PASS: Watchlist contains 1 symbol(s)

...

============================================================
  ✅ ALL TESTS COMPLETED
============================================================
📊 Summary:
  - Watchlist: ✅ Working
  - News Processing: ✅ Working
  - Context-Aware Chat: ✅ Working
  - Notifications: ✅ Working

🎉 Hermes upgrade is fully functional!
```

---

## 🐛 Troubleshooting

### Issue: "Telegram notifications not sending"
**Check**:
```bash
# Verify environment variables
echo $TELEGRAM_BOT_TOKEN
echo $TELEGRAM_CHAT_ID

# Test Telegram endpoint
curl "http://localhost:8000/notifications/test"
```

### Issue: "Context-aware chat not showing last decision"
**Solution**: Run an analysis first to create a decision:
```bash
curl "http://localhost:8000/analysis/quick/NVDA?mode=STOCK"
```

### Issue: "Hermes not processing news"
**Check scheduler**:
```bash
curl "http://localhost:8000/notifications/scheduler/status"
```

**Expected**:
```json
{
  "scheduler_active": true,
  "scheduler_running": true,
  "jobs": [
    {
      "id": "hermes_news_processing",
      "next_run_time": "2026-01-10 12:30:00"
    }
  ]
}
```

### Issue: "LLM enrichment failing"
**Check Gemini API**:
```bash
# Verify API key
echo $GOOGLE_API_KEY

# Check usage endpoint
curl "http://localhost:8000/usage/monthly?year=2026&month=1"
```

---

## 📊 Monitoring

### Check Recent Notifications
```bash
curl "http://localhost:8000/notifications?limit=10"
```

### Check Watchlist
```bash
curl "http://localhost:8000/hermes/watchlist"
```

### Check Scheduler Status
```bash
curl "http://localhost:8000/notifications/scheduler/status"
```

### Check LLM Usage
```bash
curl "http://localhost:8000/usage/monthly?year=2026&month=1"
```

---

## 🎯 Best Practices

### 1. **Start Small**
- Add 3-5 symbols to watchlist initially
- Monitor for 1-2 days
- Adjust thresholds based on notification volume

### 2. **Tune Alert Threshold**
- Default: 80 (critical only)
- High volume: Increase to 85-90
- Low volume: Decrease to 70-75

### 3. **Use Context-Aware Chat**
- Always provide `context_data` with symbol info
- Include current price and RSI for better advice
- Reference past decisions in your questions

### 4. **Monitor API Usage**
- Check monthly LLM usage regularly
- Adjust watchlist size if approaching limits
- Use local scoring threshold (default: 60) to filter

### 5. **Telegram Cooldown**
- Default: 30 minutes per symbol
- Prevents notification fatigue
- Adjust in environment variables if needed

---

## 📈 What's Next?

### Planned Features:
- [ ] Watchlist auto-population from portfolio
- [ ] Multi-language Telegram notifications
- [ ] Watchlist groups/categories
- [ ] Historical impact prediction accuracy
- [ ] Custom alert rules per symbol

### Feedback:
- Report issues: Create GitHub issue
- Suggest features: Open discussion
- Share results: Post in community

---

## 🎉 You're Ready!

Hermes is now a **Context-Aware Mentor** that:
- ✅ Watches only the symbols you care about
- ✅ Analyzes news with AI-powered impact scoring
- ✅ Sends critical alerts to Telegram instantly
- ✅ Remembers past decisions for consistent advice

**Start using it now**: Add your first symbol to the watchlist! 🚀
