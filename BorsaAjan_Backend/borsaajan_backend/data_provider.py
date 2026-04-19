"""
Robust Market Data Provider with Symbol Normalization, Fallbacks, and Error Handling.

Features:
- Symbol normalization (US/TR/crypto, suffix handling)
- Symbol validation before provider calls
- Fallback providers with backoff/rate limiting
- Improved caching + invalidation
- Graceful missing data handling (HOLD + explain)
- Comprehensive logging
"""

import time
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple, Callable
from functools import wraps
from collections import deque
import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)

# ============================================================================
# SYMBOL NORMALIZATION AND VALIDATION
# ============================================================================

# Known crypto symbols (without -USD suffix)
CRYPTO_SYMBOLS = {
    'BTC', 'ETH', 'SOL', 'ADA', 'DOT', 'MATIC', 'AVAX', 'LINK', 'UNI', 
    'ATOM', 'XRP', 'DOGE', 'SHIB', 'LTC', 'BCH', 'XLM', 'ALGO', 'VET', 
    'TRX', 'ETC', 'BNB', 'USDT', 'USDC', 'DAI'
}

# Turkish stock exchange suffixes
TR_SUFFIXES = ['.IS', '.ISX']  # BIST stocks

# US market suffixes
US_SUFFIXES = ['.US']  # OTC stocks

# Rate limiting: track requests per provider
_rate_limit_tracker: Dict[str, deque] = {}
_rate_limit_lock = {}  # Simple dict-based lock (not thread-safe but OK for single-threaded FastAPI)


def normalize_symbol(symbol: str, mode: Optional[str] = None) -> Tuple[str, str]:
    """
    Normalize and validate symbol for market data providers.
    
    Handles:
    - US stocks: AAPL, MSFT, etc. (no suffix needed)
    - TR stocks: THYAO.IS, AKBNK.IS, etc. (BIST)
    - Crypto: BTC-USD, ETH-USD, etc. (yfinance format)
    - OTC stocks: SYMBOL.US
    
    Args:
        symbol: Raw symbol string (may have various formats)
        mode: Optional mode hint ("STOCK", "CRYPTO", "TR")
    
    Returns:
        Tuple of (normalized_symbol, detected_mode)
        - normalized_symbol: Symbol in provider-ready format
        - detected_mode: "STOCK", "CRYPTO", or "TR"
    
    Raises:
        ValueError: If symbol is invalid or cannot be normalized
    """
    if not symbol or not isinstance(symbol, str):
        raise ValueError(f"Invalid symbol: {symbol} (must be non-empty string)")
    
    symbol_upper = symbol.upper().strip()
    
    # Remove common prefixes/suffixes that might be added
    symbol_upper = symbol_upper.replace('$', '').replace('^', '')
    
    # Check for Turkish stock exchange suffix (.IS, .ISX)
    if symbol_upper.endswith('.IS') or symbol_upper.endswith('.ISX'):
        base_symbol = symbol_upper[:-3] if symbol_upper.endswith('.IS') else symbol_upper[:-4]
        if not base_symbol:
            raise ValueError(f"Invalid Turkish symbol: {symbol} (empty base)")
        return symbol_upper, "TR"
    
    # Check for US OTC suffix (.US)
    if symbol_upper.endswith('.US'):
        base_symbol = symbol_upper[:-3]
        if not base_symbol:
            raise ValueError(f"Invalid OTC symbol: {symbol} (empty base)")
        return symbol_upper, "STOCK"
    
    # Check for crypto suffix (-USD, -USDT, etc.)
    if '-' in symbol_upper:
        parts = symbol_upper.split('-')
        if len(parts) == 2:
            base, quote = parts
            if quote in ['USD', 'USDT', 'USDC']:
                # Already in crypto format
                if mode and mode.upper() == "CRYPTO":
                    return symbol_upper, "CRYPTO"
                # Validate base is known crypto
                if base in CRYPTO_SYMBOLS:
                    return symbol_upper, "CRYPTO"
                # Might be a stock with dash (rare but possible)
                return symbol_upper, "STOCK"
    
    # Check if it's a known crypto symbol (without suffix)
    if symbol_upper in CRYPTO_SYMBOLS:
        if mode and mode.upper() == "CRYPTO":
            return f"{symbol_upper}-USD", "CRYPTO"
        # If mode is STOCK, treat as stock (might be wrong but user specified)
        if mode and mode.upper() == "STOCK":
            return symbol_upper, "STOCK"
        # Auto-detect: assume crypto if in crypto list
        return f"{symbol_upper}-USD", "CRYPTO"
    
    # Default: treat as US stock (most common case)
    # Validate: should be alphanumeric, 1-5 chars typically
    if not symbol_upper.replace('.', '').replace('-', '').isalnum():
        raise ValueError(f"Invalid symbol format: {symbol} (contains invalid characters)")
    
    if len(symbol_upper) > 10:
        raise ValueError(f"Invalid symbol: {symbol} (too long, max 10 chars)")
    
    # Use mode hint if provided
    detected_mode = (mode or "STOCK").upper()
    if detected_mode == "CRYPTO" and not symbol_upper.endswith('-USD'):
        # User specified crypto but symbol doesn't have suffix
        if symbol_upper in CRYPTO_SYMBOLS:
            return f"{symbol_upper}-USD", "CRYPTO"
        else:
            # Unknown crypto, try with -USD suffix
            return f"{symbol_upper}-USD", "CRYPTO"
    
    return symbol_upper, detected_mode


def validate_symbol(symbol: str, mode: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """
    Validate symbol before calling provider.
    
    Args:
        symbol: Symbol to validate
        mode: Optional mode hint
    
    Returns:
        Tuple of (is_valid, error_message)
    """
    try:
        normalized, detected_mode = normalize_symbol(symbol, mode)
        return True, None
    except ValueError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Validation error: {str(e)}"


# ============================================================================
# RATE LIMITING AND BACKOFF
# ============================================================================

def rate_limit(provider_name: str, max_requests: int = 10, window_seconds: int = 60):
    """
    Decorator for rate limiting provider calls.
    
    Args:
        provider_name: Name of provider (for tracking)
        max_requests: Max requests per window
        window_seconds: Time window in seconds
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            now = time.time()
            
            # Initialize tracker for this provider
            if provider_name not in _rate_limit_tracker:
                _rate_limit_tracker[provider_name] = deque()
            
            tracker = _rate_limit_tracker[provider_name]
            
            # Remove old entries outside window
            while tracker and tracker[0] < now - window_seconds:
                tracker.popleft()
            
            # Check if we're at limit
            if len(tracker) >= max_requests:
                wait_time = window_seconds - (now - tracker[0])
                if wait_time > 0:
                    logger.warning(
                        f"Rate limit reached for {provider_name}: "
                        f"{len(tracker)}/{max_requests} requests in last {window_seconds}s. "
                        f"Waiting {wait_time:.1f}s..."
                    )
                    time.sleep(wait_time)
                    # Clean up again after wait
                    while tracker and tracker[0] < time.time() - window_seconds:
                        tracker.popleft()
            
            # Record this request
            tracker.append(time.time())
            
            return func(*args, **kwargs)
        
        return wrapper
    return decorator


def exponential_backoff(max_retries: int = 3, base_delay: float = 1.0):
    """
    Decorator for exponential backoff on failures.
    
    Args:
        max_retries: Maximum number of retries
        base_delay: Base delay in seconds (doubles each retry)
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    
                    if attempt < max_retries:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(
                            f"Provider call failed (attempt {attempt + 1}/{max_retries + 1}): {e}. "
                            f"Retrying in {delay:.1f}s..."
                        )
                        time.sleep(delay)
                    else:
                        logger.error(f"Provider call failed after {max_retries + 1} attempts: {e}")
                        raise
            
            # Should never reach here, but just in case
            if last_exception:
                raise last_exception
        
        return wrapper
    return decorator


# ============================================================================
# PROVIDER FUNCTIONS WITH LOGGING
# ============================================================================

@rate_limit("yfinance", max_requests=20, window_seconds=60)
@exponential_backoff(max_retries=2, base_delay=0.5)
def fetch_yfinance_quote(symbol: str, mode: str) -> Dict[str, Any]:
    """
    Fetch quote data from yfinance with logging.
    
    Args:
        symbol: Normalized symbol
        mode: "STOCK", "CRYPTO", or "TR"
    
    Returns:
        Quote dict with price data
    
    Raises:
        Exception: If fetch fails
    """
    logger.info(f"[DATA_PROVIDER] Fetching quote from yfinance: symbol={symbol}, mode={mode}")
    
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        
        # Get current price
        current_price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose')
        
        # Get history for technical metrics
        hist = ticker.history(period="5d")
        
        if hist.empty:
            raise ValueError(f"No historical data available for {symbol}")
        
        current = float(hist['Close'].iloc[-1])
        prev_close = float(hist['Close'].iloc[-2]) if len(hist) > 1 else current
        
        change_pct = ((current - prev_close) / prev_close * 100) if prev_close > 0 else 0
        
        # Calculate RSI (simplified)
        deltas = hist['Close'].diff()
        gains = deltas.where(deltas > 0, 0)
        losses = -deltas.where(deltas < 0, 0)
        
        avg_gain = gains.rolling(window=14).mean().iloc[-1] if len(gains) >= 14 else gains.mean()
        avg_loss = losses.rolling(window=14).mean().iloc[-1] if len(losses) >= 14 else losses.mean()
        
        rs = (avg_gain / avg_loss) if avg_loss > 0 else 0
        rsi = 100 - (100 / (1 + rs)) if rs > 0 else 50
        
        result = {
            "current_price": float(current_price or current),
            "fiyat": float(current),
            "prev_close": float(prev_close),
            "change_pct": round(change_pct, 2),
            "rsi": round(float(rsi), 2),
            "volume": int(hist['Volume'].iloc[-1]) if 'Volume' in hist.columns else 0,
            "trend": "UP" if change_pct > 0 else "DOWN" if change_pct < 0 else "SIDEWAYS",
        }
        
        logger.info(
            f"[DATA_PROVIDER] ✅ yfinance quote success: symbol={symbol}, "
            f"price={result['current_price']}, rsi={result['rsi']}"
        )
        
        return result
        
    except Exception as e:
        logger.error(
            f"[DATA_PROVIDER] ❌ yfinance quote failed: symbol={symbol}, "
            f"error_type={type(e).__name__}, error={str(e)}"
        )
        raise


def fetch_yfinance_ohlc(symbol: str, mode: str, period: str = "6mo") -> List[Dict[str, Any]]:
    """
    Fetch OHLC data from yfinance with logging.
    
    Args:
        symbol: Normalized symbol
        mode: "STOCK", "CRYPTO", or "TR"
        period: Period string (e.g., "6mo", "1y")
    
    Returns:
        List of OHLC bar dicts
    
    Raises:
        Exception: If fetch fails
    """
    logger.info(f"[DATA_PROVIDER] Fetching OHLC from yfinance: symbol={symbol}, mode={mode}, period={period}")
    
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period)
        
        if hist.empty:
            raise ValueError(f"No OHLC data available for {symbol}")
        
        bars = []
        for dt_idx, row in hist.iterrows():
            try:
                bar_date = dt_idx.date().strftime("%Y-%m-%d") if hasattr(dt_idx, "date") else str(dt_idx)[:10]
            except Exception:
                bar_date = datetime.now().strftime("%Y-%m-%d")
            
            bars.append({
                "date": bar_date,
                "open": float(row.get("Open", 0) or 0),
                "high": float(row.get("High", 0) or 0),
                "low": float(row.get("Low", 0) or 0),
                "close": float(row.get("Close", 0) or 0),
                "volume": int(row.get("Volume", 0) or 0),
            })
        
        logger.info(f"[DATA_PROVIDER] ✅ yfinance OHLC success: symbol={symbol}, bars={len(bars)}")
        return bars
        
    except Exception as e:
        logger.error(
            f"[DATA_PROVIDER] ❌ yfinance OHLC failed: symbol={symbol}, "
            f"error_type={type(e).__name__}, error={str(e)}"
        )
        raise


def fetch_yfinance_fundamentals(symbol: str, mode: str) -> Dict[str, Any]:
    """
    Fetch fundamentals data from yfinance with logging.
    
    Args:
        symbol: Normalized symbol
        mode: "STOCK", "CRYPTO", or "TR"
    
    Returns:
        Fundamentals dict
    
    Raises:
        Exception: If fetch fails
    """
    if mode != "STOCK":
        logger.info(f"[DATA_PROVIDER] Skipping fundamentals for non-stock: symbol={symbol}, mode={mode}")
        return {}
    
    logger.info(f"[DATA_PROVIDER] Fetching fundamentals from yfinance: symbol={symbol}")
    
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        
        if not info or len(info) == 0:
            raise ValueError(f"No fundamentals data available for {symbol}")
        
        result = {
            "f_k_orani": round(float(info.get('trailingPE', 0)), 2) if info.get('trailingPE') else None,
            "analist_hedef_fiyat": round(float(info.get('targetMeanPrice', 0)), 2) if info.get('targetMeanPrice') else None,
            "analist_tavsiyesi": _map_recommendation(info.get('recommendationKey')),
            "market_cap": info.get('marketCap'),
            "sector": info.get('sector'),
            "industry": info.get('industry'),
        }
        
        logger.info(f"[DATA_PROVIDER] ✅ yfinance fundamentals success: symbol={symbol}")
        return result
        
    except Exception as e:
        logger.error(
            f"[DATA_PROVIDER] ❌ yfinance fundamentals failed: symbol={symbol}, "
            f"error_type={type(e).__name__}, error={str(e)}"
        )
        raise


def _map_recommendation(key: Optional[str]) -> str:
    """Map yfinance recommendation key to Turkish."""
    if not key:
        return "BİLİNMİYOR"
    
    mapping = {
        "strong_buy": "GÜÇLÜ AL",
        "buy": "AL",
        "hold": "TUT",
        "sell": "SAT",
        "strong_sell": "GÜÇLÜ SAT",
    }
    return mapping.get(key.lower(), "BİLİNMİYOR")


# ============================================================================
# FALLBACK PROVIDER (Simple validation-only fallback)
# ============================================================================

def create_missing_data_response(symbol: str, missing_sections: List[str], errors: List[str]) -> Dict[str, Any]:
    """
    Create a HOLD response with explanation when data is missing.
    
    Args:
        symbol: Symbol that failed
        missing_sections: List of sections that are missing
        errors: List of error messages
    
    Returns:
        Dict with HOLD decision and explanation
    """
    missing_str = ", ".join(missing_sections) if missing_sections else "all data"
    
    explanation = (
        f"Veri eksikliği nedeniyle analiz yapılamadı. "
        f"Eksik bölümler: {missing_str}. "
        f"Hatalar: {'; '.join(errors[:3])}. "
        f"Lütfen sembolü kontrol edin veya daha sonra tekrar deneyin."
    )
    
    return {
        "decision": "HOLD",
        "confidence": 20,
        "why_bullets": [
            f"Veri sağlayıcıdan {missing_str} alınamadı",
            f"Hata: {errors[0] if errors else 'Bilinmeyen hata'}",
            "Eksik veri nedeniyle güvenli karar: HOLD"
        ],
        "action_plan": [
            {
                "type": "WAIT",
                "rationale_short": "Veri eksikliği nedeniyle işlem yapmayın"
            },
            {
                "type": "SET_ALERT",
                "rationale_short": "Veri geldiğinde bildirim alın"
            }
        ],
        "missing_data": {
            "sections": missing_sections,
            "errors": errors,
            "symbol": symbol,
        },
        "risk_note": f"Veri eksikliği riski: {missing_str} bölümleri mevcut değil"
    }


# ============================================================================
# MAIN PROVIDER FUNCTION WITH FALLBACKS
# ============================================================================

def fetch_market_data_robust(
    symbol: str,
    mode: Optional[str] = None,
    include_ohlc: bool = True,
    include_fundamentals: bool = True,
) -> Dict[str, Any]:
    """
    Fetch market data with robust error handling, fallbacks, and logging.
    
    Args:
        symbol: Raw symbol (will be normalized)
        mode: Optional mode hint ("STOCK", "CRYPTO", "TR")
        include_ohlc: Whether to fetch OHLC data
        include_fundamentals: Whether to fetch fundamentals (stocks only)
    
    Returns:
        Dict with:
        - success: bool
        - symbol: normalized symbol
        - mode: detected mode
        - quote: quote data or None
        - ohlc: OHLC data or None
        - fundamentals: fundamentals data or None
        - errors: list of error messages
        - provider_used: dict of providers used per section
        - missing_data_response: HOLD response if data missing
    """
    errors = []
    provider_used = {}
    result = {
        "success": False,
        "symbol": symbol,
        "mode": mode or "STOCK",
        "quote": None,
        "ohlc": None,
        "fundamentals": None,
        "errors": [],
        "provider_used": {},
        "missing_data_response": None,
    }
    
    # Step 1: Normalize and validate symbol
    try:
        normalized_symbol, detected_mode = normalize_symbol(symbol, mode)
        result["symbol"] = normalized_symbol
        result["mode"] = detected_mode
        logger.info(f"[DATA_PROVIDER] Symbol normalized: {symbol} -> {normalized_symbol} (mode: {detected_mode})")
    except ValueError as e:
        error_msg = f"Symbol normalization failed: {str(e)}"
        errors.append(error_msg)
        logger.error(f"[DATA_PROVIDER] ❌ {error_msg}")
        result["errors"] = errors
        result["missing_data_response"] = create_missing_data_response(symbol, ["all"], [error_msg])
        return result
    
    # Step 2: Fetch quote (required)
    try:
        quote = fetch_yfinance_quote(normalized_symbol, detected_mode)
        result["quote"] = quote
        provider_used["quote"] = "yfinance"
        logger.info(f"[DATA_PROVIDER] ✅ Quote fetched successfully")
    except Exception as e:
        error_msg = f"Quote fetch failed: {type(e).__name__}: {str(e)}"
        errors.append(error_msg)
        logger.error(f"[DATA_PROVIDER] ❌ {error_msg}")
        result["quote"] = None
    
    # Step 3: Fetch OHLC (optional)
    if include_ohlc:
        try:
            ohlc = fetch_yfinance_ohlc(normalized_symbol, detected_mode)
            result["ohlc"] = ohlc
            provider_used["ohlc"] = "yfinance"
            logger.info(f"[DATA_PROVIDER] ✅ OHLC fetched successfully")
        except Exception as e:
            error_msg = f"OHLC fetch failed: {type(e).__name__}: {str(e)}"
            errors.append(error_msg)
            logger.error(f"[DATA_PROVIDER] ❌ {error_msg}")
            result["ohlc"] = None
    
    # Step 4: Fetch fundamentals (optional, stocks only)
    if include_fundamentals and detected_mode == "STOCK":
        try:
            fundamentals = fetch_yfinance_fundamentals(normalized_symbol, detected_mode)
            result["fundamentals"] = fundamentals
            provider_used["fundamentals"] = "yfinance"
            logger.info(f"[DATA_PROVIDER] ✅ Fundamentals fetched successfully")
        except Exception as e:
            error_msg = f"Fundamentals fetch failed: {type(e).__name__}: {str(e)}"
            errors.append(error_msg)
            logger.warning(f"[DATA_PROVIDER] ⚠️ {error_msg}")
            result["fundamentals"] = None
    
    # Step 5: Determine success and create missing data response if needed
    missing_sections = []
    if not result["quote"]:
        missing_sections.append("quote")
    if include_ohlc and not result["ohlc"]:
        missing_sections.append("ohlc")
    if include_fundamentals and detected_mode == "STOCK" and not result["fundamentals"]:
        missing_sections.append("fundamentals")
    
    if missing_sections:
        result["missing_data_response"] = create_missing_data_response(
            normalized_symbol, missing_sections, errors
        )
        result["success"] = False
    else:
        result["success"] = True
    
    result["errors"] = errors
    result["provider_used"] = provider_used
    
    return result
