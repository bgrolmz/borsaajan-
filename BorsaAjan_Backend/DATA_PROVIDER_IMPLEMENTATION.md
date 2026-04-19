# Data Provider Reliability Implementation

## Overview
Implemented robust market data provider with symbol normalization, fallback providers, backoff/rate limiting, improved caching, and graceful missing data handling.

## Key Features

### 1. Symbol Normalization and Validation
**File**: `borsaajan_backend/data_provider.py`

- **US Stocks**: AAPL, MSFT, NVDA (no suffix needed)
- **Turkish Stocks**: THYAO.IS, AKBNK.IS (BIST with .IS suffix)
- **Crypto**: BTC-USD, ETH-USD (auto-adds -USD if missing)
- **OTC Stocks**: SYMBOL.US (US OTC market)
- **Validation**: Checks format, length, invalid characters before provider calls

**Function**: `normalize_symbol(symbol, mode=None) -> (normalized_symbol, detected_mode)`

**Examples**:
```python
normalize_symbol("AAPL") -> ("AAPL", "STOCK")
normalize_symbol("BTC") -> ("BTC-USD", "CRYPTO")
normalize_symbol("THYAO.IS") -> ("THYAO.IS", "TR")
normalize_symbol("BTC", mode="STOCK") -> ("BTC", "STOCK")  # Mode override
```

### 2. Fallback Providers
**File**: `borsaajan_backend/data_provider.py`

- **Primary**: yfinance (existing)
- **Fallback**: Stale cache (memory → SQLite)
- **Error Handling**: Graceful degradation with detailed error messages

### 3. Rate Limiting and Backoff
**File**: `borsaajan_backend/data_provider.py`

- **Rate Limiting**: `@rate_limit(provider_name, max_requests=20, window_seconds=60)`
  - Tracks requests per provider
  - Auto-waits if limit reached
  - Logs warnings when rate limited

- **Exponential Backoff**: `@exponential_backoff(max_retries=2, base_delay=0.5)`
  - Retries failed requests with increasing delays
  - Logs retry attempts
  - Raises exception after max retries

### 4. Improved Caching + Invalidation
**File**: `borsaajan_backend/market_snapshot.py` (enhanced)

- **In-Memory Cache**: Fast TTL cache (20 minutes for quotes)
- **SQLite Cache**: Persistent cache across restarts
- **Stale Cache Fallback**: Uses stale data if fresh fetch fails
- **Cache Invalidation**: TTL-based expiration

**TTL Defaults** (configurable via env vars):
- Quote: 20 minutes (`SNAPSHOT_QUOTE_TTL_MIN`)
- OHLC: 6 hours (`SNAPSHOT_OHLC_TTL_MIN`)
- Fundamentals: 24 hours (`SNAPSHOT_FUNDAMENTALS_TTL_MIN`)
- News: 20 minutes (`SNAPSHOT_NEWS_TTL_MIN`)

### 5. Missing Data Handling
**File**: `borsaajan_backend/data_provider.py`

When data is missing, returns **HOLD** decision with:
- **Decision**: "HOLD"
- **Confidence**: 20 (low)
- **Why Bullets**: Explains what's missing and why
- **Action Plan**: WAIT + SET_ALERT recommendations
- **Missing Data**: Details about missing sections and errors
- **Risk Note**: Explains the risk of missing data

**Function**: `create_missing_data_response(symbol, missing_sections, errors)`

**Example Response**:
```json
{
  "decision": "HOLD",
  "confidence": 20,
  "why_bullets": [
    "Veri sağlayıcıdan quote alınamadı",
    "Hata: Provider timeout",
    "Eksik veri nedeniyle güvenli karar: HOLD"
  ],
  "action_plan": [
    {"type": "WAIT", "rationale_short": "Veri eksikliği nedeniyle işlem yapmayın"},
    {"type": "SET_ALERT", "rationale_short": "Veri geldiğinde bildirim alın"}
  ],
  "missing_data": {
    "sections": ["quote"],
    "errors": ["Provider timeout"],
    "symbol": "AAPL"
  },
  "risk_note": "Veri eksikliği riski: quote bölümleri mevcut değil"
}
```

### 6. Comprehensive Logging
**File**: `borsaajan_backend/data_provider.py`

All provider calls log:
- **Request**: Symbol, mode, provider name
- **Success**: Price, RSI, bars count, etc.
- **Failure**: Error type, error message, provider name
- **Rate Limiting**: Warnings when rate limited
- **Backoff**: Retry attempts and delays

**Log Format**:
```
[DATA_PROVIDER] Fetching quote from yfinance: symbol=AAPL, mode=STOCK
[DATA_PROVIDER] ✅ yfinance quote success: symbol=AAPL, price=150.25, rsi=65.3
[DATA_PROVIDER] ❌ yfinance quote failed: symbol=INVALID, error_type=ValueError, error=No data found
```

## Integration Points

### 1. Market Snapshot Integration
**File**: `borsaajan_backend/market_snapshot.py`

- Uses robust normalization before fetching
- Validates symbols before provider calls
- Logs validation errors

### 2. Canonical Analysis Integration
**File**: `borsaajan_backend/logic.py`

- `get_canonical_quick_analysis()` uses robust normalization
- Returns HOLD with explanation if symbol invalid
- Returns HOLD with explanation if data missing
- Includes `missing_data` and `flags` in response

## Testing

### Unit Tests
**File**: `test_data_provider.py`

Tests cover:
1. **Symbol Normalization**:
   - US stocks (AAPL, MSFT)
   - Crypto (BTC, ETH-USD)
   - Turkish stocks (THYAO.IS)
   - OTC stocks (SYMBOL.US)
   - Edge cases ($ prefix, whitespace, case)

2. **Symbol Validation**:
   - Valid symbols
   - Invalid symbols (empty, too long, invalid chars)

3. **Missing Data Response**:
   - Response structure
   - All sections missing

4. **Integration Tests**:
   - Real symbol fetch (requires network)
   - Invalid symbol handling
   - Crypto symbol handling

**Run Tests**:
```bash
cd BorsaAjan_Backend
python -m pytest test_data_provider.py -v
```

## Usage Examples

### Basic Usage
```python
from borsaajan_backend.data_provider import fetch_market_data_robust

# Fetch data with robust error handling
result = fetch_market_data_robust("AAPL", mode="STOCK")

if result["success"]:
    print(f"Price: {result['quote']['current_price']}")
else:
    print(f"Failed: {result['missing_data_response']['why_bullets']}")
```

### Symbol Normalization
```python
from borsaajan_backend.data_provider import normalize_symbol, validate_symbol

# Normalize symbol
symbol, mode = normalize_symbol("BTC", mode="CRYPTO")
# Returns: ("BTC-USD", "CRYPTO")

# Validate before use
is_valid, error = validate_symbol("INVALID@SYMBOL")
# Returns: (False, "Invalid symbol format: ...")
```

## Configuration

### Environment Variables
- `SNAPSHOT_QUOTE_TTL_MIN`: Quote cache TTL in minutes (default: 20)
- `SNAPSHOT_OHLC_TTL_MIN`: OHLC cache TTL in minutes (default: 360)
- `SNAPSHOT_FUNDAMENTALS_TTL_MIN`: Fundamentals cache TTL in minutes (default: 1440)
- `SNAPSHOT_NEWS_TTL_MIN`: News cache TTL in minutes (default: 20)

### Rate Limiting Configuration
- **yfinance**: 20 requests per 60 seconds (configurable in decorator)
- **Backoff**: 2 retries with exponential delay (0.5s, 1s)

## Error Handling Flow

1. **Symbol Validation**: If invalid → HOLD + explanation
2. **Provider Fetch**: If fails → Try backoff retries
3. **Rate Limiting**: If limit reached → Wait and retry
4. **Missing Data**: If data missing → HOLD + explanation + missing_data flags
5. **Stale Cache**: If all fails → Use stale cache (if available)

## Benefits

1. **Reliability**: Handles invalid symbols, network failures, rate limits
2. **Performance**: Caching reduces API calls
3. **User Experience**: Clear error messages and HOLD decisions when data missing
4. **Debugging**: Comprehensive logging for troubleshooting
5. **Flexibility**: Supports US/TR/crypto symbols with auto-detection

## Next Steps

1. Run unit tests to verify normalization and error handling
2. Test with real symbols to verify provider integration
3. Monitor logs for rate limiting and backoff behavior
4. Consider adding more fallback providers (Alpha Vantage, etc.)
5. Add metrics/telemetry for provider success rates
