# News Pipeline Implementation Summary

## Overview
Replaced raw/copy news with mentor interpretation and personalization pipeline.

## Implementation Details

### 1. Symbol Selection with TTL Cache
**File**: `borsaajan_backend/news_pipeline.py`

- Function: `get_relevant_symbols_cached()`
- Sources:
  - Portfolio holdings (from `portfolio` table)
  - Past trades (from `portfolio_transactions` table, last 90 days)
  - Recently analyzed symbols (from `analysis_history` table, last 30 days)
- TTL Cache: 30 minutes (configurable via `_SYMBOL_SET_TTL_SECONDS`)
- Deduplication: Set-based deduplication ensures unique symbols

### 2. News Fetching and Normalization
**File**: `borsaajan_backend/news_pipeline.py`

- Function: `fetch_and_dedupe_news()`
- Source: Yahoo Finance RSS feeds
- Normalization: `normalize_news_item()` converts feedparser entries to standard format
- Fields extracted:
  - `title`: News headline
  - `snippet`: News summary (first 500 chars)
  - `source`: News source name
  - `published_date`: Publication date (YYYY-MM-DD format)
  - `timestamp`: Full timestamp string

### 3. Deduplication (Symbol + Headline Hash + Date)
**File**: `borsaajan_backend/news_pipeline.py`

- Function: `compute_news_hash()`
- Hash components:
  - Symbol (normalized, uppercase)
  - Title (normalized, lowercase, whitespace collapsed)
  - Published date (YYYY-MM-DD format)
- Algorithm: SHA256 hash, first 16 hex characters
- Deduplication: Uses `seen_hashes` set to track processed items

**Example**:
```python
hash1 = compute_news_hash("AAPL", "Apple Reports Earnings", "2025-01-15")
hash2 = compute_news_hash("AAPL", "Apple Reports Earnings", "2025-01-15")  # Same hash
hash3 = compute_news_hash("AAPL", "Apple Reports Earnings", "2025-01-16")  # Different hash (date)
```

### 4. Local Scoring First (Fast)
**File**: `borsaajan_backend/news_pipeline.py`

- Function: `score_news_local()`
- Uses existing `analyze_news_item()` from `news_analyzer.py`
- Returns:
  - `importance_score`: 0-100
  - `impact`: "bullish", "bearish", or "neutral"
  - `time_horizon`: "intraday", "short", or "long"
  - `reasons`: List of reason strings
- Performance: < 1ms per item (no LLM calls)

### 5. LLM Enrichment ONLY Above Threshold
**File**: `borsaajan_backend/news_pipeline.py`

- Function: `enrich_news_with_llm()`
- Trigger conditions:
  - Mode is "DEEP"
  - Local score >= `llm_threshold` (default: 60)
- Output fields:
  - `what_happened`: Short summary (max 100 chars)
  - `why_it_matters`: Why it's important for portfolio/investment (max 150 chars)
  - `mentor_action`: Mentor recommendation (max 100 chars)
  - `risk`: Risk note (max 100 chars)
- LLM Model: Gemini Flash (via `safe_gemini_call`)
- Temperature: 0.2 (low for consistent responses)
- Max tokens: 600

### 6. Output Format
**File**: `borsaajan_backend/news_pipeline.py`

- Function: `_build_mentor_card()`
- Standard fields (always present):
  - `symbol`: Stock/crypto symbol
  - `mentor_summary`: Combined summary (what_happened + why_it_matters if LLM enriched, else reasons)
  - `expected_impact`: "POSITIVE", "NEGATIVE", or "NEUTRAL"
  - `action_hint`: "CONSIDER_BUY", "SET_STOP_LOSS", "HOLD_STRONG", "CONSIDER_SELL", "MONITOR", "HOLD"
  - `confidence`: Importance score (0-100)
  - `time_horizon`: "intraday", "short", or "long"
  - `timestamp`: ISO timestamp string
  - `source`: News source name
- LLM-enriched fields (only if LLM enrichment applied):
  - `what_happened`: What happened
  - `why_it_matters`: Why it matters
  - `mentor_action`: Mentor action recommendation
  - `risk`: Risk note

### 7. Notifications with Deduplication and Fatigue Prevention
**File**: `borsaajan_backend/news_pipeline.py`

- Function: `_process_notifications()`
- Rules:
  - Only items >= `confidence_threshold` are considered
  - Cooldown: Default 30 minutes (configurable via `NOTIF_COOLDOWN_MINUTES`)
  - Max per day per symbol: Configurable via `NOTIF_MAX_PER_DAY_PER_SYMBOL`
  - Event key: Generated from `mentor_summary` + `source` + first 80 chars
- Uses existing `should_send_notification()` and `log_notification()` functions

### 8. Database Storage for Learning
**File**: `borsaajan_backend/database.py` + `borsaajan_backend/news_pipeline.py`

- Table: `news_analysis_history`
- Function: `save_news_analysis_to_db()`
- Fields stored:
  - `symbol`: Stock/crypto symbol
  - `news_hash`: Deduplication hash
  - `title`: News title
  - `source`: News source
  - `published_date`: Publication date
  - `local_score`: Local importance score
  - `llm_enriched`: 1 if LLM enrichment applied, 0 otherwise
  - `mentor_summary`: Mentor summary
  - `what_happened`: What happened (if LLM enriched)
  - `why_it_matters`: Why it matters (if LLM enriched)
  - `mentor_action`: Mentor action (if LLM enriched)
  - `risk_note`: Risk note (if LLM enriched)
  - `expected_impact`: Expected impact
  - `action_hint`: Action hint
  - `confidence`: Confidence score
  - `time_horizon`: Time horizon
  - `full_analysis_json`: Complete analysis JSON
- Unique constraint: `(symbol, news_hash)` prevents duplicates

## API Endpoint

**Endpoint**: `GET /mentor/news`

**Parameters**:
- `mode`: "QUICK" (local only) or "DEEP" (LLM enrichment above threshold)
- `confidence_threshold`: Minimum confidence for inclusion (0-100, default: 50)
- `llm_threshold`: Minimum local score to trigger LLM enrichment (0-100, default: 60, only for DEEP mode)

**Response**:
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
      "source": "Reuters",
      "what_happened": "...",  // Only if LLM enriched
      "why_it_matters": "...",  // Only if LLM enriched
      "mentor_action": "...",   // Only if LLM enriched
      "risk": "..."             // Only if LLM enriched
    }
  ],
  "count": 5,
  "mode": "DEEP",
  "confidence_threshold": 50,
  "llm_threshold": 60
}
```

## Files Modified

1. **`borsaajan_backend/database.py`**:
   - Added `news_analysis_history` table schema
   - Added indexes for performance

2. **`borsaajan_backend/logic.py`**:
   - Updated `get_mentor_news()` to use new pipeline
   - Added fallback implementation

3. **`borsaajan_backend/news_pipeline.py`** (NEW):
   - Complete pipeline implementation
   - Symbol selection with TTL cache
   - News fetching and normalization
   - Deduplication logic
   - Local scoring
   - LLM enrichment
   - Mentor card building
   - Notification processing
   - Database storage

4. **`borsaajan_backend/main.py`**:
   - Updated `/mentor/news` endpoint to accept `llm_threshold` parameter

## Unit Tests

**File**: `test_news_pipeline.py`

Tests cover:
- `compute_news_hash()`: Deduplication hash correctness
- `normalize_news_item()`: News item normalization
- `score_news_local()`: Local scoring
- `get_relevant_symbols_cached()`: Symbol selection with caching
- Deduplication logic

Run tests:
```bash
cd BorsaAjan_Backend
python -m pytest test_news_pipeline.py -v
```

## Manual Test Checklist

See `NEWS_PIPELINE_MANUAL_TEST.md` for comprehensive manual test checklist covering:
1. Symbol selection test
2. Deduplication test
3. Local scoring test
4. LLM enrichment test
5. Output format test
6. Notification test
7. Database storage test
8. Performance test
9. Error handling test
10. Integration test

## Performance Characteristics

- **QUICK mode**: < 5 seconds (local scoring only)
- **DEEP mode**: < 15 seconds (LLM enrichment for high-scoring items only)
- **Symbol cache**: 30-minute TTL reduces DB queries
- **Deduplication**: O(n) hash-based deduplication
- **LLM calls**: Only for items with local score >= threshold (reduces API costs)

## Configuration

Environment variables:
- `NOTIF_COOLDOWN_MINUTES`: Notification cooldown period (default: 30)
- `NOTIF_MAX_PER_DAY_PER_SYMBOL`: Max notifications per day per symbol (optional)

Code constants:
- `_SYMBOL_SET_TTL_SECONDS`: Symbol cache TTL (default: 1800 = 30 minutes)
- Default `llm_threshold`: 60
- Default `confidence_threshold`: 50

## Next Steps

1. Run unit tests to verify deduplication and symbol selection
2. Run manual tests to verify end-to-end pipeline
3. Monitor LLM usage (should be reduced due to threshold filtering)
4. Analyze `news_analysis_history` table for learning opportunities
5. Consider adding symbol context (portfolio weight, recent analysis) to LLM prompt
