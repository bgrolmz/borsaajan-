"""borsaajan_backend.market_snapshot

Robust market data provider contract.

This module defines a single interface for collecting market data into a
MarketSnapshot with:
- per-section as_of timestamps
- per-section data availability flags
- non-fatal errors list

Implementation notes:
- This module is the single backend interface for market data used by QUICK/DEEP.
- It implements hybrid caching:
  - in-memory TTL (fast)
  - SQLite section cache (persistent across restarts)
- It implements provider fallback:
  - primary fetch
  - fallback to cached (stale allowed) on failure/empty
"""

from __future__ import annotations

import os
import warnings
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from .database import get_snapshot_section_cache, set_snapshot_section_cache

# SILENCE yfinance warnings (e.g., "possibly delisted", market holiday messages)
warnings.filterwarnings("ignore", message=".*possibly delisted.*")
warnings.filterwarnings("ignore", message=".*No price data found.*")
warnings.filterwarnings("ignore", category=FutureWarning, module="yfinance")


SnapshotSection = Literal["quote", "ohlc", "fundamentals", "news"]


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(ts: str) -> Optional[datetime]:
    if not ts or not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _is_expired(expires_at: str, now_iso: Optional[str] = None) -> bool:
    exp_dt = _parse_iso(expires_at)
    now_dt = _parse_iso(now_iso or _iso_utc_now())
    if not exp_dt or not now_dt:
        return True
    return now_dt >= exp_dt


def _env_int(name: str, default: int) -> int:
    try:
        v = int(os.getenv(name, str(default)))
        return v
    except Exception:
        return default


# In-memory TTL cache for snapshot sections: (symbol, mode, section) -> meta/payload
_MEM_SECTION_CACHE: Dict[tuple, Dict[str, Any]] = {}


def _mem_get(symbol: str, mode: str, section: SnapshotSection, *, allow_stale: bool) -> Optional[Dict[str, Any]]:
    key = (symbol.upper(), mode.upper(), section)
    entry = _MEM_SECTION_CACHE.get(key)
    if not isinstance(entry, dict):
        return None
    expires_at = str(entry.get("expires_at") or "")
    stale = _is_expired(expires_at)
    if stale and not allow_stale:
        return None
    out = dict(entry)
    out["stale"] = bool(stale)
    out["cache_source"] = "memory"
    return out


def _mem_set(
    symbol: str,
    mode: str,
    section: SnapshotSection,
    *,
    payload: Any,
    as_of: Optional[str],
    fetched_at: str,
    expires_at: str,
) -> None:
    key = (symbol.upper(), mode.upper(), section)
    _MEM_SECTION_CACHE[key] = {
        "payload": payload,
        "as_of": as_of,
        "fetched_at": fetched_at,
        "expires_at": expires_at,
        "stale": False,
        "cache_source": "memory",
    }


def _compute_expires_at(ttl_seconds: int, now_iso: Optional[str] = None) -> str:
    base = _parse_iso(now_iso or _iso_utc_now()) or datetime.now(timezone.utc)
    return (base + timedelta(seconds=max(1, int(ttl_seconds)))).strftime("%Y-%m-%dT%H:%M:%SZ")


class SectionAvailability(BaseModel):
    available: bool = False
    stale: bool = False


class MarketSnapshotError(BaseModel):
    section: SnapshotSection
    provider: str
    error_type: str
    message: str
    timestamp: str = Field(default_factory=_iso_utc_now)


class MarketSnapshot(BaseModel):
    # Identity
    symbol: str
    mode: Literal["STOCK", "CRYPTO"]

    # As-of timestamps per section
    analysis_as_of: str
    quote_as_of: str
    ohlc_as_of: str
    fundamentals_as_of: str
    news_as_of: str

    # Availability flags per section
    data_availability: Dict[SnapshotSection, SectionAvailability] = Field(default_factory=dict)

    # Non-fatal errors
    errors: List[MarketSnapshotError] = Field(default_factory=list)

    # Payloads (lightly-typed dicts to avoid invasive refactors)
    quote: Optional[Dict[str, Any]] = None
    ohlc: Optional[List[Dict[str, Any]]] = None
    fundamentals: Optional[Dict[str, Any]] = None
    news: Optional[Dict[str, Any]] = None


def _coerce_section_payload(section: SnapshotSection, payload: Any) -> Any:
    """
    SQLite returns JSON-decoded payloads; ensure the type matches our expected shapes.
    """
    if section == "ohlc":
        return payload if isinstance(payload, list) else None
    return payload if isinstance(payload, dict) else None


def _is_quote_available(quote: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(quote, dict):
        return False
    # Prefer active current_price; fall back to regular close (fiyat)
    for k in ["current_price", "active_price", "fiyat"]:
        try:
            v = quote.get(k)
            if isinstance(v, (int, float)) and float(v) > 0:
                return True
        except Exception:
            continue
    return False


def _is_ohlc_available(ohlc: Optional[List[Dict[str, Any]]]) -> bool:
    if not isinstance(ohlc, list) or not ohlc:
        return False
    # Consider available if at least one bar has a non-zero close
    for bar in ohlc[:5]:
        if not isinstance(bar, dict):
            continue
        close = bar.get("close")
        if isinstance(close, (int, float)) and float(close) > 0:
            return True
    return True  # Non-empty list is still useful for charts


def _is_fundamentals_available(fundamentals: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(fundamentals, dict) or not fundamentals:
        return False
    # Available if any key has a non-null, non-empty value
    for v in fundamentals.values():
        if v is None:
            continue
        if isinstance(v, str) and not v.strip():
            continue
        return True
    return False


def _is_news_available(news: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(news, dict):
        return False
    items = news.get("ai_interpreted")
    if isinstance(items, list) and len(items) > 0:
        # Filter out the placeholder case
        if len(items) == 1 and isinstance(items[0], dict) and (items[0].get("title") or "").strip().lower() in [
            "haber yok",
            "haber çekilemedi",
        ]:
            return False
        return True
    # Some callers use "titles" array
    titles = news.get("titles")
    if isinstance(titles, list) and any(isinstance(t, str) and t.strip() and t.strip() != "Haber yok" for t in titles):
        return True
    return False


def _load_section_with_cache(
    *,
    symbol: str,
    mode: str,
    section: SnapshotSection,
    ttl_seconds: int,
    primary_provider: str,
    fetch_primary,
    secondary_provider: Optional[str] = None,
    fetch_secondary=None,
    is_available,
    errors_out: List[MarketSnapshotError],
    analysis_ts: str,
) -> Dict[str, Any]:
    """
    Returns a dict:
    {
      "payload": Any|None,
      "as_of": str,
      "stale": bool,
      "cache_hit": 0|1,
      "cache_source": "memory"|"sqlite"|"none"
    }
    """
    sym_u = symbol.upper()
    mode_u = mode.upper()

    # 1) In-memory cache
    mem = _mem_get(sym_u, mode_u, section, allow_stale=False)
    if mem is not None:
        return {
            "payload": _coerce_section_payload(section, mem.get("payload")),
            "as_of": str(mem.get("as_of") or analysis_ts),
            "stale": bool(mem.get("stale", False)),
            "cache_hit": 1,
            "cache_source": "memory",
        }

    # 2) SQLite cache (fresh only)
    try:
        cached = get_snapshot_section_cache(sym_u, mode_u, section, allow_stale=False)
    except Exception as e:
        cached = None
        errors_out.append(
            MarketSnapshotError(
                section=section,
                provider="sqlite",
                error_type=type(e).__name__,
                message=str(e),
            )
        )

    if isinstance(cached, dict) and "payload" in cached:
        payload = _coerce_section_payload(section, cached.get("payload"))
        if payload is not None:
            _mem_set(
                sym_u,
                mode_u,
                section,
                payload=payload,
                as_of=str(cached.get("as_of") or analysis_ts),
                fetched_at=str(cached.get("fetched_at") or analysis_ts),
                expires_at=str(cached.get("expires_at") or analysis_ts),
            )
            return {
                "payload": payload,
                "as_of": str(cached.get("as_of") or analysis_ts),
                "stale": bool(cached.get("stale", False)),
                "cache_hit": 1,
                "cache_source": "sqlite",
            }

    # 3) Primary provider
    now_s = _iso_utc_now()
    expires_at = _compute_expires_at(ttl_seconds, now_s)
    try:
        payload = fetch_primary()
        if is_available(payload):
            payload_typed = _coerce_section_payload(section, payload)
            if payload_typed is None:
                raise ValueError(f"Primary provider returned wrong type for section={section}")

            # Store in caches (best-effort)
            _mem_set(sym_u, mode_u, section, payload=payload_typed, as_of=now_s, fetched_at=now_s, expires_at=expires_at)
            set_snapshot_section_cache(
                sym_u,
                mode_u,
                section,
                payload=payload_typed,
                as_of=now_s,
                fetched_at=now_s,
                expires_at=expires_at,
            )
            return {"payload": payload_typed, "as_of": now_s, "stale": False, "cache_hit": 0, "cache_source": "none"}

        errors_out.append(
            MarketSnapshotError(
                section=section,
                provider=primary_provider,
                error_type="EmptyData",
                message="Primary provider returned empty/no usable data",
            )
        )
    except Exception as e:
        errors_out.append(
            MarketSnapshotError(
                section=section,
                provider=primary_provider,
                error_type=type(e).__name__,
                message=str(e),
            )
        )

    # 3b) Secondary provider (optional)
    if fetch_secondary is not None and secondary_provider:
        try:
            payload2 = fetch_secondary()
            if is_available(payload2):
                payload2_typed = _coerce_section_payload(section, payload2)
                if payload2_typed is None:
                    raise ValueError(f"Secondary provider returned wrong type for section={section}")

                _mem_set(
                    sym_u,
                    mode_u,
                    section,
                    payload=payload2_typed,
                    as_of=now_s,
                    fetched_at=now_s,
                    expires_at=expires_at,
                )
                set_snapshot_section_cache(
                    sym_u,
                    mode_u,
                    section,
                    payload=payload2_typed,
                    as_of=now_s,
                    fetched_at=now_s,
                    expires_at=expires_at,
                )
                errors_out.append(
                    MarketSnapshotError(
                        section=section,
                        provider="fallback",
                        error_type="SecondaryProviderUsed",
                        message=f"Primary provider failed/empty; served secondary provider ({secondary_provider})",
                    )
                )
                return {
                    "payload": payload2_typed,
                    "as_of": now_s,
                    "stale": False,
                    "cache_hit": 0,
                    "cache_source": "none",
                }

            errors_out.append(
                MarketSnapshotError(
                    section=section,
                    provider=secondary_provider,
                    error_type="EmptyData",
                    message="Secondary provider returned empty/no usable data",
                )
            )
        except Exception as e:
            errors_out.append(
                MarketSnapshotError(
                    section=section,
                    provider=secondary_provider,
                    error_type=type(e).__name__,
                    message=str(e),
                )
            )

    # 4) Fallback to stale cache (memory then sqlite)
    mem_stale = _mem_get(sym_u, mode_u, section, allow_stale=True)
    if isinstance(mem_stale, dict) and mem_stale.get("payload") is not None:
        errors_out.append(
            MarketSnapshotError(
                section=section,
                provider="fallback",
                error_type="StaleCacheUsed",
                message="Primary provider failed/empty; served stale cached data (memory)",
            )
        )
        return {
            "payload": _coerce_section_payload(section, mem_stale.get("payload")),
            "as_of": str(mem_stale.get("as_of") or analysis_ts),
            "stale": True,
            "cache_hit": 1,
            "cache_source": "memory",
        }

    try:
        cached_stale = get_snapshot_section_cache(sym_u, mode_u, section, allow_stale=True)
    except Exception as e:
        cached_stale = None
        errors_out.append(
            MarketSnapshotError(
                section=section,
                provider="sqlite",
                error_type=type(e).__name__,
                message=str(e),
            )
        )
    if isinstance(cached_stale, dict) and cached_stale.get("payload") is not None:
        payload = _coerce_section_payload(section, cached_stale.get("payload"))
        if payload is not None:
            _mem_set(
                sym_u,
                mode_u,
                section,
                payload=payload,
                as_of=str(cached_stale.get("as_of") or analysis_ts),
                fetched_at=str(cached_stale.get("fetched_at") or analysis_ts),
                expires_at=str(cached_stale.get("expires_at") or analysis_ts),
            )
            errors_out.append(
                MarketSnapshotError(
                    section=section,
                    provider="fallback",
                    error_type="StaleCacheUsed",
                    message="Primary provider failed/empty; served stale cached data (sqlite)",
                )
            )
            return {
                "payload": payload,
                "as_of": str(cached_stale.get("as_of") or analysis_ts),
                "stale": True,
                "cache_hit": 1,
                "cache_source": "sqlite",
            }

    # Nothing usable
    return {"payload": None, "as_of": analysis_ts, "stale": False, "cache_hit": 0, "cache_source": "none"}


def get_market_snapshot(
    symbol: str,
    mode: str = "STOCK",
    as_of: Optional[str] = None,
    include_ohlc: bool = True,
) -> MarketSnapshot:
    """Collect market data into a single MarketSnapshot.

    This is the single backend interface for downstream analysis.

    Args:
        symbol: Stock/crypto symbol.
        mode: "STOCK" or "CRYPTO".
        as_of: Optional analysis timestamp (ISO). If None, uses now (UTC).
        include_ohlc: Whether to fetch OHLC bars (can be disabled for ultra-fast paths).

    Returns:
        MarketSnapshot with section timestamps, availability flags, and non-fatal errors.
    """

    # Local imports to avoid heavy imports at module load time
    from .logic import get_chart_data, get_technical_metrics, get_fundamental_data, get_news
    from .data_provider import normalize_symbol, validate_symbol, fetch_market_data_robust

    # Use robust normalization with validation
    try:
        normalized_symbol, detected_mode = normalize_symbol(symbol, mode)
        is_valid, validation_error = validate_symbol(symbol, mode)
        if not is_valid:
            snap.errors.append(
                MarketSnapshotError(
                    section="quote",
                    provider="validation",
                    error_type="InvalidSymbol",
                    message=f"Symbol validation failed: {validation_error}",
                )
            )
    except ValueError as e:
        snap.errors.append(
            MarketSnapshotError(
                section="quote",
                provider="validation",
                error_type="InvalidSymbol",
                message=f"Symbol normalization failed: {str(e)}",
            )
        )
        normalized_symbol = symbol.upper().strip()  # Fallback to basic normalization
        detected_mode = mode_upper
    mode_upper = (mode or "STOCK").upper()
    if mode_upper not in ["STOCK", "CRYPTO"]:
        mode_upper = "STOCK"

    analysis_ts = as_of or _iso_utc_now()

    snap = MarketSnapshot(
        symbol=normalized_symbol,
        mode=mode_upper,  # type: ignore[arg-type]
        analysis_as_of=analysis_ts,
        quote_as_of=analysis_ts,
        ohlc_as_of=analysis_ts,
        fundamentals_as_of=analysis_ts,
        news_as_of=analysis_ts,
        data_availability={},
        errors=[],
        quote=None,
        ohlc=None,
        fundamentals=None,
        news=None,
    )

    # TTL defaults (minutes) - configurable via env vars
    quote_ttl_min = _env_int("SNAPSHOT_QUOTE_TTL_MIN", 20)
    news_ttl_min = _env_int("SNAPSHOT_NEWS_TTL_MIN", 20)
    fundamentals_ttl_min = _env_int("SNAPSHOT_FUNDAMENTALS_TTL_MIN", 24 * 60)
    ohlc_ttl_min = _env_int("SNAPSHOT_OHLC_TTL_MIN", 6 * 60)

    # QUOTE (primary: technical metrics -> active/current price)
    # Import here to keep module import side-effects low.
    try:
        from .services.finance_service import get_extended_hours_price as _get_extended_hours_price  # type: ignore
    except Exception:
        _get_extended_hours_price = None  # type: ignore

    quote_meta = _load_section_with_cache(
        symbol=normalized_symbol,
        mode=mode_upper,
        section="quote",
        ttl_seconds=quote_ttl_min * 60,
        primary_provider="yfinance",
        fetch_primary=lambda: get_technical_metrics(normalized_symbol),
        secondary_provider="finance_service",
        fetch_secondary=(lambda: _get_extended_hours_price(normalized_symbol)) if _get_extended_hours_price else None,
        is_available=_is_quote_available,
        errors_out=snap.errors,
        analysis_ts=analysis_ts,
    )
    snap.quote = quote_meta.get("payload")
    snap.quote_as_of = str(quote_meta.get("as_of") or analysis_ts)

    # OHLC (primary: get_chart_data already cache-first; we still section-cache for provider consistency)
    if include_ohlc:
        def _fetch_ohlc_secondary_direct() -> List[Dict[str, Any]]:
            # Secondary provider: direct yfinance history to bypass DB/cache issues.
            # UNSHACKLED MODE: Fetch 2 YEARS of data for long-term pattern detection (bubble detection, etc.)
            import yfinance as yf  # local import

            t = yf.Ticker(normalized_symbol)
            
            # Enhanced retry logic for yfinance failures (3 attempts with exponential backoff)
            hist = None
            for attempt in range(3):  # 3 attempts total (IMPROVED FROM 2)
                try:
                    hist = t.history(period="2y")  # CHANGED FROM 1y TO 2y
                    if hist is not None and len(hist) >= 1:
                        break
                    # SILENCED: Market holidays cause this - not an error
                    # print(f"⚠️ yfinance returned empty data for {normalized_symbol} (attempt {attempt + 1}/3)")
                except Exception as e:
                    print(f"⚠️ yfinance fetch failed for {normalized_symbol} (attempt {attempt + 1}/3): {e}")
                    if attempt < 2:  # Don't sleep on last attempt
                        import time
                        time.sleep(1.5 ** attempt)  # Exponential backoff: 1s, 1.5s
            
            if hist is None or len(hist) < 1:
                raise ValueError(f"Failed to fetch historical data for {normalized_symbol} after 3 attempts with retries")
            
            # ARCHITECT FIX: Filter out future dates BEFORE processing
            from datetime import datetime
            today = datetime.now()
            
            # Make today timezone-aware if hist.index is timezone-aware
            if hist.index.tz is not None:
                import pytz
                today = today.replace(tzinfo=pytz.UTC)
            
            original_len = len(hist)
            hist = hist[hist.index <= today]
            filtered_count = original_len - len(hist)
            
            if filtered_count > 0:
                print(f"⚠️ ARCHITECT BLOCK: Pre-filtered {filtered_count} future dates for {normalized_symbol}")
            
            if len(hist) < 1:
                raise ValueError(f"All data was future dates for {normalized_symbol}")
            
            # Calculate enhanced technical indicators on the full 1-year dataset
            import pandas as pd
            import numpy as np
            
            # SMA200
            hist['SMA200'] = hist['Close'].rolling(window=200).mean()
            
            # Bollinger Bands (20-day)
            hist['SMA20'] = hist['Close'].rolling(window=20).mean()
            hist['BB_STD'] = hist['Close'].rolling(window=20).std()
            hist['BB_Upper'] = hist['SMA20'] + (hist['BB_STD'] * 2)
            hist['BB_Lower'] = hist['SMA20'] - (hist['BB_STD'] * 2)
            
            # MACD (12, 26, 9)
            exp12 = hist['Close'].ewm(span=12, adjust=False).mean()
            exp26 = hist['Close'].ewm(span=26, adjust=False).mean()
            hist['MACD'] = exp12 - exp26
            hist['MACD_Signal'] = hist['MACD'].ewm(span=9, adjust=False).mean()
            hist['MACD_Hist'] = hist['MACD'] - hist['MACD_Signal']
            
            bars: List[Dict[str, Any]] = []
            
            # NOTE: Future dates already filtered above before technical indicators calc
            today_date = datetime.now().date()
            
            for dt_idx, row in hist.iterrows():
                try:
                    bar_date_str = dt_idx.date().strftime("%Y-%m-%d") if hasattr(dt_idx, "date") else str(dt_idx)[:10]
                    bar_date_obj = dt_idx.date() if hasattr(dt_idx, "date") else datetime.strptime(bar_date_str, "%Y-%m-%d").date()
                    
                    # ARCHITECT RULE: Double-check - skip any future dates (should already be filtered)
                    if bar_date_obj > today_date:
                        continue  # Skip silently (already logged above)
                        
                    bar_date = bar_date_str
                except Exception:
                    bar_date = _iso_utc_now()[:10]
                
                # Include enhanced technical indicators in bars
                bar_data = {
                    "date": bar_date,
                    "open": float(row.get("Open", 0) or 0),
                    "high": float(row.get("High", 0) or 0),
                    "low": float(row.get("Low", 0) or 0),
                    "close": float(row.get("Close", 0) or 0),
                    "volume": int(row.get("Volume", 0) or 0),
                }
                
                # Add technical indicators (handle NaN values)
                sma200 = row.get("SMA200")
                if pd.notna(sma200):
                    bar_data["sma200"] = float(sma200)
                
                bb_upper = row.get("BB_Upper")
                bb_lower = row.get("BB_Lower")
                if pd.notna(bb_upper) and pd.notna(bb_lower):
                    bar_data["bb_upper"] = float(bb_upper)
                    bar_data["bb_lower"] = float(bb_lower)
                
                macd = row.get("MACD")
                macd_signal = row.get("MACD_Signal")
                macd_hist = row.get("MACD_Hist")
                if pd.notna(macd) and pd.notna(macd_signal) and pd.notna(macd_hist):
                    bar_data["macd"] = float(macd)
                    bar_data["macd_signal"] = float(macd_signal)
                    bar_data["macd_hist"] = float(macd_hist)
                
                bars.append(bar_data)
            
            # Summary log (cleaner)
            print(f"✅ Fetched {len(bars)} bars (2 YEARS - UNSHACKLED) with SMA200, BB, MACD for {normalized_symbol}")
            return bars

        ohlc_meta = _load_section_with_cache(
            symbol=normalized_symbol,
            mode=mode_upper,
            section="ohlc",
            ttl_seconds=ohlc_ttl_min * 60,
            primary_provider="yfinance/db_cache",
            fetch_primary=lambda: get_chart_data(normalized_symbol, mode_upper),
            secondary_provider="yfinance_direct",
            fetch_secondary=_fetch_ohlc_secondary_direct,
            is_available=_is_ohlc_available,
            errors_out=snap.errors,
            analysis_ts=analysis_ts,
        )
        snap.ohlc = ohlc_meta.get("payload")
        snap.ohlc_as_of = str(ohlc_meta.get("as_of") or analysis_ts)

    # FUNDAMENTALS (stocks only; for crypto mark unavailable without error)
    if mode_upper == "STOCK":
        def _fetch_fundamentals_secondary_direct() -> Dict[str, Any]:
            # Secondary provider: direct yfinance.info read (best-effort).
            # UNSHACKLED MODE: Fetch FULL valuation metrics, not just PE ratio
            import yfinance as yf  # local import

            # Add retry logic for .info (can fail intermittently)
            info = None
            for attempt in range(3):
                try:
                    info = yf.Ticker(normalized_symbol).info or {}
                    if info and isinstance(info, dict) and len(info) > 5:
                        break
                    print(f"⚠️ yfinance .info incomplete for {normalized_symbol} (attempt {attempt + 1}/3)")
                except Exception as e:
                    print(f"⚠️ yfinance .info failed for {normalized_symbol} (attempt {attempt + 1}/3): {e}")
                    if attempt < 2:
                        import time
                        time.sleep(0.5)
            
            if not info or not isinstance(info, dict):
                info = {}
            
            # Extract comprehensive valuation metrics
            trailing_pe = info.get("trailingPE", None)
            forward_pe = info.get("forwardPE", None)
            peg_ratio = info.get("pegRatio", None)
            target_mean_price = info.get("targetMeanPrice", None)
            target_high_price = info.get("targetHighPrice", None)
            target_low_price = info.get("targetLowPrice", None)
            recommendation_key = info.get("recommendationKey", None)
            market_cap = info.get("marketCap", None)
            ebitda_margins = info.get("ebitdaMargins", None)
            sector = info.get("sector", None)
            industry = info.get("industry", None)
            
            recommendation_map = {
                "strong_buy": "GÜÇLÜ AL",
                "buy": "AL",
                "hold": "TUT",
                "sell": "SAT",
                "strong_sell": "GÜÇLÜ SAT",
            }
            recommendation = recommendation_map.get(recommendation_key, "BİLİNMİYOR") if recommendation_key else "BİLİNMİYOR"
            
            return {
                # Legacy fields
                "f_k_orani": round(float(trailing_pe), 2) if trailing_pe else None,
                "analist_hedef_fiyat": round(float(target_mean_price), 2) if target_mean_price else None,
                "analist_tavsiyesi": recommendation,
                # NEW: Comprehensive valuation
                "forward_pe": round(float(forward_pe), 2) if forward_pe else None,
                "trailing_pe": round(float(trailing_pe), 2) if trailing_pe else None,
                "peg_ratio": round(float(peg_ratio), 3) if peg_ratio else None,
                "target_mean": round(float(target_mean_price), 2) if target_mean_price else None,
                "target_high": round(float(target_high_price), 2) if target_high_price else None,
                "target_low": round(float(target_low_price), 2) if target_low_price else None,
                "market_cap": market_cap,
                "ebitda_margins": round(float(ebitda_margins) * 100, 2) if ebitda_margins else None,
                "sector": sector,
                "industry": industry,
            }

        fundamentals_meta = _load_section_with_cache(
            symbol=normalized_symbol,
            mode=mode_upper,
            section="fundamentals",
            ttl_seconds=fundamentals_ttl_min * 60,
            primary_provider="yfinance",
            fetch_primary=lambda: get_fundamental_data(normalized_symbol),
            secondary_provider="yfinance_info",
            fetch_secondary=_fetch_fundamentals_secondary_direct,
            is_available=_is_fundamentals_available,
            errors_out=snap.errors,
            analysis_ts=analysis_ts,
        )
        snap.fundamentals = fundamentals_meta.get("payload")
        snap.fundamentals_as_of = str(fundamentals_meta.get("as_of") or analysis_ts)

    # NEWS (local heuristic only; must never call LLM here)
    def _fetch_news_secondary_yfinance() -> Dict[str, Any]:
        # Secondary provider: yfinance .news list (no LLM). Normalize to get_news()-like shape.
        import yfinance as yf  # local import

        items = []
        try:
            items = yf.Ticker(normalized_symbol).news or []
        except Exception:
            items = []

        ai_interpreted: List[Dict[str, Any]] = []
        for it in items[:5]:
            title = str(it.get("title") or "").strip()
            if not title:
                continue
            ai_interpreted.append(
                {
                    "title": title,
                    "is_critical": False,
                    "priority": "LOW",
                    "impact": "Nötr",
                    "explanation": "Yedek haber kaynağı (yfinance) - detay sınırlı.",
                    "importance_score": 30,
                    "time_horizon": "short",
                    "reasons": [],
                    "low_priority": True,
                    "link": it.get("link", ""),
                }
            )

        sentiment_score = 50
        return {
            "titles": [x.get("title", "") for x in ai_interpreted] or ["Haber yok"],
            "sentiment_score": sentiment_score,
            "snippets": [x.get("explanation", "") for x in ai_interpreted],
            "ai_interpreted": ai_interpreted,
        }

    news_meta = _load_section_with_cache(
        symbol=normalized_symbol,
        mode=mode_upper,
        section="news",
        ttl_seconds=news_ttl_min * 60,
        primary_provider="feedparser",
        fetch_primary=lambda: get_news(normalized_symbol, use_llm=0, mode=mode_upper),
        secondary_provider="yfinance_news",
        fetch_secondary=_fetch_news_secondary_yfinance,
        is_available=_is_news_available,
        errors_out=snap.errors,
        analysis_ts=analysis_ts,
    )
    snap.news = news_meta.get("payload")
    snap.news_as_of = str(news_meta.get("as_of") or analysis_ts)

    # Availability flags (explicit)
    snap.data_availability = {
        "quote": SectionAvailability(available=_is_quote_available(snap.quote), stale=bool(quote_meta.get("stale"))),
        "ohlc": SectionAvailability(
            available=_is_ohlc_available(snap.ohlc) if include_ohlc else False,
            stale=bool((ohlc_meta.get("stale") if include_ohlc else False)),
        ),
        "fundamentals": SectionAvailability(
            available=_is_fundamentals_available(snap.fundamentals) if mode_upper == "STOCK" else False,
            stale=bool((fundamentals_meta.get("stale") if mode_upper == "STOCK" else False)),
        ),
        "news": SectionAvailability(available=_is_news_available(snap.news), stale=bool(news_meta.get("stale"))),
    }

    # If still empty, add explicit EmptyData error (never silent)
    if not snap.data_availability["quote"].available:
        snap.errors.append(
            MarketSnapshotError(
                section="quote",
                provider="provider_chain",
                error_type="EmptyData",
                message="No usable quote data after cache+primary+fallback",
            )
        )
    if include_ohlc and not snap.data_availability["ohlc"].available:
        snap.errors.append(
            MarketSnapshotError(
                section="ohlc",
                provider="provider_chain",
                error_type="EmptyData",
                message="No usable OHLC data after cache+primary+fallback",
            )
        )
    if mode_upper == "STOCK" and not snap.data_availability["fundamentals"].available:
        snap.errors.append(
            MarketSnapshotError(
                section="fundamentals",
                provider="provider_chain",
                error_type="EmptyData",
                message="No usable fundamentals data after cache+primary+fallback",
            )
        )
    if not snap.data_availability["news"].available:
        snap.errors.append(
            MarketSnapshotError(
                section="news",
                provider="provider_chain",
                error_type="EmptyData",
                message="No usable news data after cache+primary+fallback",
            )
        )

    return snap


# ============================================================================
# BACKFILL FUNCTION - ARCHITECT FIX: STRICTLY BLOCKS FUTURE DATES
# ============================================================================

def backfill_missing_data(symbol: str, missing_days: int = 730, interval: str = "1d"):
    """
    Backfills missing data segments from Yahoo Finance.
    ARCHITECT FIX: STRICTLY BLOCKS FUTURE DATES.
    
    Args:
        symbol: Stock/crypto symbol
        missing_days: Number of days to backfill (default 730 = 2 years)
        interval: Data interval (default "1d")
    
    Returns:
        DataFrame or None if failed
    """
    from datetime import datetime, timedelta
    import yfinance as yf
    
    # FORCED REFRESH LOGIC FOR MENTOR MODE:
    # Instead of complex gap filling which is buggy, let's just fetch the last 2 years 
    # if we need deep context.
    
    print(f"[market] Force-fetching last 2 years for {symbol} to ensure clean context...")
    try:
        ticker = yf.Ticker(symbol)
        
        # ARCHITECT FIX: Only fetch up to NOW - never future dates
        df = ticker.history(period="2y", interval=interval)
        
        if df is None or df.empty:
            # SILENCED: Market holidays cause this - not an error
            # print(f"⚠️ No data found for {symbol}")
            return None

        # ARCHITECT FIX: Filter out any future garbage if YF returns it
        now = datetime.now()
        if df.index.tz is not None:
            # If index is timezone-aware, make now timezone-aware too
            import pytz
            now = now.replace(tzinfo=pytz.UTC)
        
        # Hard filter: Remove any dates > today
        original_len = len(df)
        df = df[df.index <= now]
        filtered_len = len(df)
        
        if filtered_len < original_len:
            print(f"⚠️ ARCHITECT BLOCK: Filtered out {original_len - filtered_len} future dates for {symbol}")
        
        if df.empty:
            print(f"⚠️ All data was future dates for {symbol} - nothing to save")
            return None
        
        # Convert to list of dicts for upsert
        bars = []
        for dt_idx, row in df.iterrows():
            bar_date = dt_idx.date().strftime("%Y-%m-%d") if hasattr(dt_idx, "date") else str(dt_idx)[:10]
            bars.append({
                "date": bar_date,
                "open": float(row.get("Open", 0) or 0),
                "high": float(row.get("High", 0) or 0),
                "low": float(row.get("Low", 0) or 0),
                "close": float(row.get("Close", 0) or 0),
                "volume": int(row.get("Volume", 0) or 0),
            })
        
        # Save to DB (Upsert)
        from .database import upsert_market_bars
        count = upsert_market_bars(symbol, "STOCK", interval, bars)
        print(f"✅ Refreshed {count} bars for {symbol} (filtered {original_len - filtered_len} future dates)")
        return df
        
    except Exception as e:
        print(f"❌ Backfill failed for {symbol}: {e}")
        return None
