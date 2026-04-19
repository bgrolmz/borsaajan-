# News Pipeline - Manual Test Checklist

## Overview
This checklist verifies the mentor news pipeline implementation:
1. Symbol selection (portfolio + trades + analyzed, with TTL cache)
2. News fetching with normalization
3. Deduplication (symbol + headline hash + date)
4. Local scoring first (fast)
5. LLM enrichment ONLY above threshold
6. Output: what_happened + why_it_matters + mentor_action + risk
7. Notifications with deduplication and fatigue prevention
8. Store to DB for learning (news_analysis_history)

## Prerequisites
- Backend running on http://127.0.0.1:8000
- Database initialized
- Portfolio has at least 1 stock (for symbol selection test)
- GOOGLE_API_KEY set (for LLM enrichment test)

## Test Cases

### 1. Symbol Selection Test
**Endpoint**: Internal (via `/mentor/news`)

**Steps**:
1. Add a stock to portfolio: `POST /portfolio/add {"symbol": "AAPL", "avg_cost": 150, "quantity": 10}`
2. Call `/mentor/news?mode=QUICK&confidence_threshold=30`
3. Check logs for: `[news_pipeline] Processing X symbols`
4. Verify symbols include AAPL

**Expected**:
- ✅ Symbols include portfolio holdings
- ✅ Symbols include recently analyzed symbols (if any)
- ✅ Symbols include past trades (if any)
- ✅ Cache works (second call should be faster)

**Logs to check**:
```
[news_pipeline] Processing X symbols
[news_pipeline] Fetched Y deduplicated news items
```

### 2. Deduplication Test
**Endpoint**: `/mentor/news`

**Steps**:
1. Call `/mentor/news?mode=QUICK&confidence_threshold=30` twice within 1 minute
2. Compare results

**Expected**:
- ✅ Same news items should not appear twice
- ✅ Deduplication uses symbol + headline hash + date
- ✅ Different dates = different items (even if same title)
- ✅ Different symbols = different items (even if same title)

**Verification**:
- Check response: no duplicate `news_hash` values
- Check logs: `[news_pipeline] Fetched X deduplicated news items`

### 3. Local Scoring Test
**Endpoint**: `/mentor/news?mode=QUICK`

**Steps**:
1. Call `/mentor/news?mode=QUICK&confidence_threshold=50`
2. Check response structure

**Expected**:
- ✅ All items have `confidence >= 50`
- ✅ All items have `importance_score` (from local analysis)
- ✅ All items have `impact` (POSITIVE/NEGATIVE/NEUTRAL)
- ✅ All items have `time_horizon` (intraday/short/long)
- ✅ Response is fast (< 5 seconds)

**Response structure**:
```json
{
  "mentor_news_cards": [
    {
      "symbol": "AAPL",
      "mentor_summary": "...",
      "expected_impact": "POSITIVE",
      "action_hint": "CONSIDER_BUY",
      "confidence": 75,
      "time_horizon": "short",
      "timestamp": "2025-01-15T10:30:00Z",
      "source": "Reuters"
    }
  ]
}
```

### 4. LLM Enrichment Test (DEEP Mode)
**Endpoint**: `/mentor/news?mode=DEEP&llm_threshold=60`

**Steps**:
1. Call `/mentor/news?mode=DEEP&confidence_threshold=50&llm_threshold=60`
2. Check response for LLM-enriched fields

**Expected**:
- ✅ Items with `confidence >= 60` have LLM-enriched fields:
  - `what_happened` (present)
  - `why_it_matters` (present)
  - `mentor_action` (present)
  - `risk` (present)
- ✅ Items with `confidence < 60` do NOT have LLM-enriched fields
- ✅ LLM is only called for items above threshold (check logs)

**Logs to check**:
```
🤖 [NEWS LLM] Enriching news for AAPL: '...'
✅ [NEWS LLM] Successfully enriched news
```

**Response structure (LLM-enriched)**:
```json
{
  "symbol": "AAPL",
  "mentor_summary": "...",
  "what_happened": "Apple reported record earnings...",
  "why_it_matters": "Strong earnings support price appreciation...",
  "mentor_action": "Consider holding position, review profit targets",
  "risk": "RSI high, watch for pullback",
  "expected_impact": "POSITIVE",
  "action_hint": "CONSIDER_BUY",
  "confidence": 75,
  "time_horizon": "short"
}
```

### 5. Output Format Test
**Endpoint**: `/mentor/news?mode=DEEP&llm_threshold=60`

**Steps**:
1. Call endpoint
2. Verify all required fields are present

**Expected**:
- ✅ All items have: `symbol`, `mentor_summary`, `expected_impact`, `action_hint`, `confidence`, `time_horizon`, `timestamp`
- ✅ LLM-enriched items have: `what_happened`, `why_it_matters`, `mentor_action`, `risk`
- ✅ No null values in required fields
- ✅ All strings are non-empty (or have sensible defaults)

### 6. Notification Test
**Endpoint**: `/mentor/news`

**Steps**:
1. Call `/mentor/news?mode=QUICK&confidence_threshold=50` multiple times within cooldown period
2. Check notification logs

**Expected**:
- ✅ Notifications sent only for items >= confidence_threshold
- ✅ Notifications respect cooldown (same event_key not sent twice within cooldown)
- ✅ Notifications respect max_per_day_per_symbol limit
- ✅ Logs show: `[news_pipeline] Notification sent` or `[news_pipeline] Notification suppressed`

**Logs to check**:
```
[news_pipeline] Notification sent: symbol=AAPL confidence=75
[news_pipeline] Notification suppressed: symbol=AAPL reason=cooldown_active
```

### 7. Database Storage Test
**Endpoint**: `/mentor/news`

**Steps**:
1. Call `/mentor/news?mode=DEEP&confidence_threshold=50`
2. Query database: `SELECT * FROM news_analysis_history ORDER BY created_at DESC LIMIT 10`

**Expected**:
- ✅ All processed news items are stored in DB
- ✅ `news_hash` is unique (no duplicates)
- ✅ `llm_enriched` = 1 for items that used LLM, 0 otherwise
- ✅ All fields populated: `what_happened`, `why_it_matters`, `mentor_action`, `risk` (if LLM enriched)
- ✅ `full_analysis_json` contains complete analysis

**SQL Query**:
```sql
SELECT 
    symbol, 
    news_hash, 
    title, 
    local_score, 
    llm_enriched, 
    what_happened, 
    why_it_matters,
    mentor_action,
    risk,
    confidence,
    created_at
FROM news_analysis_history
ORDER BY created_at DESC
LIMIT 10;
```

### 8. Performance Test
**Endpoint**: `/mentor/news`

**Steps**:
1. Time the call: `time curl "http://127.0.0.1:8000/mentor/news?mode=QUICK&confidence_threshold=50"`
2. Time DEEP mode: `time curl "http://127.0.0.1:8000/mentor/news?mode=DEEP&confidence_threshold=50&llm_threshold=60"`

**Expected**:
- ✅ QUICK mode: < 5 seconds (local scoring only)
- ✅ DEEP mode: < 15 seconds (LLM enrichment for high-scoring items)
- ✅ Cache works: second call faster than first

### 9. Error Handling Test
**Endpoint**: `/mentor/news`

**Steps**:
1. Test with invalid mode: `/mentor/news?mode=INVALID`
2. Test with empty portfolio (no symbols)
3. Test with network error (disconnect internet temporarily)

**Expected**:
- ✅ Invalid mode falls back to QUICK
- ✅ Empty portfolio returns empty array (not error)
- ✅ Network errors are handled gracefully (fallback, no crash)

### 10. Integration Test
**Endpoint**: `/mentor/news`

**Steps**:
1. Add multiple stocks to portfolio
2. Analyze some stocks (to add to analyzed symbols)
3. Call `/mentor/news?mode=DEEP&confidence_threshold=50&llm_threshold=60`
4. Verify end-to-end flow

**Expected**:
- ✅ Symbols include portfolio + analyzed symbols
- ✅ News fetched for all relevant symbols
- ✅ Deduplication works across symbols
- ✅ Local scoring filters low-confidence items
- ✅ LLM enrichment only for high-confidence items
- ✅ All items stored to DB
- ✅ Notifications sent (if applicable)

## Verification Commands

### Check Database
```bash
sqlite3 data/borsa.db "SELECT COUNT(*) FROM news_analysis_history;"
sqlite3 data/borsa.db "SELECT symbol, COUNT(*) as count FROM news_analysis_history GROUP BY symbol ORDER BY count DESC LIMIT 10;"
sqlite3 data/borsa.db "SELECT symbol, llm_enriched, COUNT(*) FROM news_analysis_history GROUP BY symbol, llm_enriched;"
```

### Check Notifications
```bash
sqlite3 data/borsa.db "SELECT symbol, event_key, importance_score, created_at FROM notification_log ORDER BY created_at DESC LIMIT 10;"
```

### Test API
```bash
# QUICK mode
curl "http://127.0.0.1:8000/mentor/news?mode=QUICK&confidence_threshold=50" | jq '.mentor_news_cards | length'

# DEEP mode
curl "http://127.0.0.1:8000/mentor/news?mode=DEEP&confidence_threshold=50&llm_threshold=60" | jq '.mentor_news_cards[] | select(.what_happened != null) | .symbol'
```

## Success Criteria

- ✅ All test cases pass
- ✅ No duplicate news items in response
- ✅ LLM enrichment only for items above threshold
- ✅ All items stored to database
- ✅ Notifications respect cooldown and limits
- ✅ Performance acceptable (< 5s QUICK, < 15s DEEP)
- ✅ Error handling graceful
- ✅ Logs show clear pipeline stages

## Known Issues / Notes

- Symbol cache TTL: 30 minutes (configurable via `_SYMBOL_SET_TTL_SECONDS`)
- LLM threshold: Default 60 (configurable via `llm_threshold` parameter)
- Notification cooldown: Default 30 minutes (configurable via `NOTIF_COOLDOWN_MINUTES` env var)
- Max notifications per day per symbol: Configurable via `NOTIF_MAX_PER_DAY_PER_SYMBOL` env var
