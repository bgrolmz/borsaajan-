"""
Production-level SQLite database layer for Borsa Ajani backend.

This module provides a clean, type-safe interface for storing and retrieving
analysis history, portfolio analysis, and user profile data.

DB Path Strategy:
- Uses BORSA_DB_PATH env var if set (absolute path recommended)
- Otherwise uses <repo_root>/data/borsa.db
- <repo_root> is the parent directory of borsaajan_backend package
- Path is always resolved to absolute for consistency
"""

import sqlite3
import os
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple, Union, Literal
from datetime import date, timedelta

# Configure logging
logger = logging.getLogger(__name__)

# ============================================================================
# JSON SERIALIZATION HELPERS
# ============================================================================

def _json_safe(obj):
    """
    Recursively convert non-JSON-native types to native Python types.
    
    Handles:
    - numpy.bool_ -> bool
    - numpy.integer -> int
    - numpy.floating -> float
    - numpy.ndarray -> list
    - pandas Timestamp -> ISO string
    - datetime/date -> ISO string
    - Unknown objects -> str(obj) as last resort
    """
    try:
        import numpy as np
    except Exception:
        np = None

    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, tuple):
        return [_json_safe(v) for v in obj]
    if np is not None:
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.ndarray,)):
            return obj.tolist()
    # pandas Timestamp / datetime-like
    try:
        import pandas as pd
        if isinstance(obj, (pd.Timestamp,)):
            return obj.isoformat()
    except Exception:
        pass

    # regular datetime/date objects
    try:
        from datetime import datetime, date
        if isinstance(obj, (datetime, date)):
            return obj.isoformat()
    except Exception:
        pass

    # plain primitives pass through
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj

    # last resort: stringify
    return str(obj)

# ============================================================================
# DATABASE PATH CONFIGURATION - SINGLE SOURCE OF TRUTH
# ============================================================================

# Global cache for DB path (lazy initialization)
_DB_PATH_CACHE: Optional[Path] = None
_STRAY_DB_CHECKED = False


def get_db_path() -> Path:
    """
    Get the absolute path to the database file.
    
    Priority:
    1. BORSA_DB_PATH environment variable (if set, converted to absolute)
    2. <repo_root>/data/borsa.db (default)
    
    <repo_root> is determined by: Path(__file__).resolve().parent.parent
    (parent of borsaajan_backend package directory)
    
    Returns:
        Path: Absolute path to database file
    """
    global _DB_PATH_CACHE
    
    # Return cached path if available
    if _DB_PATH_CACHE is not None:
        return _DB_PATH_CACHE
    
    # Check environment variable first (DB_PATH or BORSA_DB_PATH)
    env_db_path = os.environ.get("DB_PATH") or os.environ.get("BORSA_DB_PATH")
    if env_db_path:
        # Convert to Path and resolve to absolute (handles relative paths)
        db_path = Path(env_db_path).resolve()
        # Ensure parent directory exists
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _DB_PATH_CACHE = db_path
        return db_path
    
    # Default: <repo_root>/data/borsa.db
    # repo_root = parent of borsaajan_backend package directory
    current_file = Path(__file__).resolve()
    # current_file is: <repo_root>/borsaajan_backend/database.py
    # repo_root = current_file.parent.parent
    repo_root = current_file.parent.parent
    data_dir = repo_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    
    db_path = data_dir / "borsa.db"
    _DB_PATH_CACHE = db_path.resolve()
    
    # Check for stray DB files in current working directory (once per module load)
    _check_stray_db(_DB_PATH_CACHE)
    
    return _DB_PATH_CACHE


def _check_stray_db(db_path: Path) -> None:
    """Check for stray borsa.db in CWD and log warning if found."""
    global _STRAY_DB_CHECKED
    
    if _STRAY_DB_CHECKED:
        return
    
    _STRAY_DB_CHECKED = True
    
    try:
        cwd = Path.cwd().resolve()
        stray_db = cwd / "borsa.db"
        if stray_db.exists() and stray_db.resolve() != db_path.resolve():
            logger.warning(f"[DB] Detected stray borsa.db at CWD; ignoring: {stray_db}")
    except Exception:
        # Ignore errors during stray DB check
        pass


# Export DB_PATH for backward compatibility (deprecated - use get_db_path())
# This is initialized lazily on first access
_DB_PATH_STR: Optional[str] = None

def _get_db_path_str() -> str:
    """Get DB_PATH as string for backward compatibility."""
    global _DB_PATH_STR
    if _DB_PATH_STR is None:
        _DB_PATH_STR = str(get_db_path())
    return _DB_PATH_STR

# Export DB_PATH as a property-like accessor
class _DBPathStr:
    """Backward compatibility wrapper for DB_PATH string export."""
    def __str__(self) -> str:
        return _get_db_path_str()
    
    def __repr__(self) -> str:
        return f"DB_PATH({_get_db_path_str()})"

DB_PATH = _DBPathStr()


# ============================================================================
# CONNECTION HELPER - SINGLE ENTRY POINT
# ============================================================================

def get_connection() -> sqlite3.Connection:
    """
    Get a database connection with proper PRAGMA settings.
    Use this as the single entry point for all DB connections.
    
    PRAGMA settings (applied on every connection):
    - journal_mode=WAL (Write-Ahead Logging for better concurrency)
    - synchronous=NORMAL (compatible with WAL)
    - foreign_keys=ON (enforce referential integrity)
    - busy_timeout=5000 (wait up to 5 seconds on locked DB)
    
    Returns:
        sqlite3.Connection: Configured database connection
    """
    db_path = get_db_path()
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    
    # Set PRAGMA settings for production use (every connection)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    
    return conn


# Alias for backward compatibility
get_conn = get_connection


# ============================================================================
# DATABASE INITIALIZATION
# ============================================================================

def init_db() -> None:
    """
    Initialize the database: create tables if they don't exist.
    This function is idempotent - safe to call multiple times.
    Data is NEVER deleted - only creates tables if missing.
    
    Should be called once at application startup (main.py).
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Create analysis_history table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analysis_history (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol               TEXT NOT NULL,
                mode                 TEXT NOT NULL,
                raw_prompt           TEXT,
                raw_response         TEXT,
                summary              TEXT,
                risk_level           INTEGER,
                full_analysis_json   TEXT,
                price_at_analysis    REAL,
                created_at           TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Canonical decision DEEP cache (hash-keyed by symbol + as_of + quick_features_hash)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS deep_decision_cache (
                cache_key            TEXT PRIMARY KEY,
                symbol               TEXT NOT NULL,
                as_of_analysis       TEXT NOT NULL,
                quick_features_hash  TEXT NOT NULL,
                deep_json            TEXT NOT NULL,
                created_at           TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_deep_decision_cache_symbol_created
            ON deep_decision_cache(symbol, created_at DESC)
        """)

        # MarketSnapshot section cache (hybrid caching layer: SQLite persistence + in-memory TTL in provider)
        # Keyed by (symbol, mode, section) so each section can have its own TTL and payload.
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS market_snapshot_section_cache (
                symbol               TEXT NOT NULL,
                mode                 TEXT NOT NULL,
                section              TEXT NOT NULL,
                as_of                TEXT,
                fetched_at           TEXT NOT NULL,
                expires_at           TEXT NOT NULL,
                payload_json         TEXT NOT NULL,
                PRIMARY KEY(symbol, mode, section)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_snapshot_cache_expires_at
            ON market_snapshot_section_cache(expires_at)
        """)
        
        # Create portfolio table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS portfolio (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL UNIQUE,
                avg_cost REAL NOT NULL,
                quantity REAL NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create portfolio_transactions table (for transaction history)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS portfolio_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                quantity REAL NOT NULL,
                price REAL NOT NULL,
                transaction_type TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create portfolio_analysis_history table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS portfolio_analysis_history (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                portfolio_json       TEXT,
                summary              TEXT,
                risk_level           INTEGER,
                full_json            TEXT,
                created_at           TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create portfolio_analyses table (mentor system - normalized structure)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS portfolio_analyses (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                as_of                TEXT NOT NULL,
                mode                 TEXT NOT NULL,
                summary_json         TEXT,
                full_json            TEXT,
                created_at           TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create portfolio_features table (feature vectors for similarity search)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS portfolio_features (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id          INTEGER NOT NULL,
                feature_json         TEXT NOT NULL,
                created_at           TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (analysis_id) REFERENCES portfolio_analyses(id) ON DELETE CASCADE
            )
        """)
        
        # Create portfolio_outcomes table (forward returns for learning)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS portfolio_outcomes (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                analysis_id          INTEGER NOT NULL,
                horizon              INTEGER NOT NULL,
                return_pct           REAL,
                return_usd           REAL,
                computed_at          TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (analysis_id) REFERENCES portfolio_analyses(id) ON DELETE CASCADE,
                UNIQUE(analysis_id, horizon)
            )
        """)
        
        # Create indexes for faster queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_portfolio_features_analysis_id 
            ON portfolio_features(analysis_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_portfolio_outcomes_analysis_id 
            ON portfolio_outcomes(analysis_id)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_portfolio_analyses_created_at 
            ON portfolio_analyses(created_at DESC)
        """)
        
        # Create user_profile table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_profile (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                settings_json        TEXT,
                created_at           TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create notifications table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                type TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create notification_log table (for cooldown tracking)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notification_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                event_key TEXT NOT NULL,
                importance_score INTEGER,
                title TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Create news_analysis_history table (for learning from news interpretations)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS news_analysis_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                news_hash TEXT NOT NULL,
                title TEXT NOT NULL,
                source TEXT,
                published_date TEXT,
                local_score INTEGER,
                llm_enriched INTEGER DEFAULT 0,
                mentor_summary TEXT,
                what_happened TEXT,
                why_it_matters TEXT,
                mentor_action TEXT,
                risk_note TEXT,
                expected_impact TEXT,
                action_hint TEXT,
                confidence INTEGER,
                time_horizon TEXT,
                full_analysis_json TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, news_hash)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_news_analysis_symbol_date 
            ON news_analysis_history(symbol, published_date)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_news_analysis_hash 
            ON news_analysis_history(news_hash)
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS news_price_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                news_hash TEXT NOT NULL,
                symbol TEXT NOT NULL,
                price_at_news REAL NOT NULL,
                captured_at TEXT NOT NULL,
                outcome_checked INTEGER DEFAULT 0,
                UNIQUE(news_hash, symbol)
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_news_snapshots_pending
            ON news_price_snapshots(outcome_checked, captured_at)
        """)

        try:
            cursor.execute("ALTER TABLE notification_log ADD COLUMN title TEXT")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE news_analysis_history ADD COLUMN advice TEXT")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE news_analysis_history ADD COLUMN comment TEXT")
        except sqlite3.OperationalError:
            pass
        
        # Create index for faster cooldown queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_notification_log_symbol_event_time 
            ON notification_log(symbol, event_key, created_at)
        """)
        
        # Drop old index if it exists (migration)
        try:
            cursor.execute("DROP INDEX IF EXISTS idx_notification_log_symbol_event")
        except sqlite3.OperationalError:
            pass
        
        # Create market_bars table (for chart data caching)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS market_bars (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                mode TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                bar_date TEXT NOT NULL,
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(symbol, mode, timeframe, bar_date)
            )
        """)
        
        # Create index for faster queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_market_bars_symbol_mode_timeframe_date 
            ON market_bars(symbol, mode, timeframe, bar_date)
        """)
        
        # Create llm_usage_log table (for LLM usage tracking and budget control)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS llm_usage_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                model TEXT NOT NULL,
                purpose TEXT NOT NULL,
                symbol TEXT,
                request_id TEXT,
                prompt_chars INTEGER,
                output_chars INTEGER,
                prompt_tokens INTEGER,
                output_tokens INTEGER,
                total_tokens INTEGER,
                estimated_cost_usd REAL NOT NULL,
                is_estimated INTEGER NOT NULL
            )
        """)
        
        # Create index for monthly queries
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_llm_usage_created_at 
            ON llm_usage_log(created_at)
        """)
        
        # Create watched_symbols table (Hermes watchlist mechanism)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS watched_symbols (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL UNIQUE,
                mode TEXT NOT NULL DEFAULT 'STOCK',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_watched_symbols_symbol 
            ON watched_symbols(symbol)
        """)
        
        # ARCHITECT CLEANUP: Remove bad/invalid symbols from watchlist on startup
        # - Symbols longer than 6 chars (most stock symbols are 1-5 chars)
        # - Symbols with spaces (typos)
        # - Empty or NULL symbols
        try:
            cursor.execute("""
                DELETE FROM watched_symbols 
                WHERE length(symbol) > 6 
                   OR symbol LIKE '% %' 
                   OR symbol IS NULL 
                   OR symbol = ''
            """)
            cleaned_count = cursor.rowcount
            if cleaned_count > 0:
                logger.info(f"🧹 Watchlist cleanup: Removed {cleaned_count} invalid symbols")
        except Exception as cleanup_err:
            logger.warning(f"⚠️ Watchlist cleanup failed (non-fatal): {cleanup_err}")
        
        conn.commit()
        conn.close()
        
        db_path = get_db_path()
        logger.info(f"✅ Database initialized: {db_path}")
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize database: {e}", exc_info=True)
        raise


# ============================================================================
# PUBLIC API - All exported functions
# ============================================================================

__all__ = [
    # Core
    "DB_PATH",
    "get_db_path",
    "get_connection",
    "get_conn",
    "init_db",
    # Analysis functions
    "save_analysis",
    "get_last_analysis",
    "get_last_decision_for_symbol",
    "get_memory_context",
    "get_symbol_analysis_history",
    "get_all_history",
    # Canonical decision caching
    "get_deep_decision_cache",
    "set_deep_decision_cache",
    # MarketSnapshot section caching
    "get_snapshot_section_cache",
    "set_snapshot_section_cache",
    # Portfolio functions
    "add_to_portfolio",
    "remove_from_portfolio",
    "get_portfolio",
    "add_portfolio_transaction",
    "get_relevant_symbols_for_news",
    # Watched symbols (Hermes watchlist)
    "get_watched_symbols",
    "add_watched_symbol",
    "remove_watched_symbol",
    "get_watched_symbols_only",
    # Portfolio analysis
    "save_portfolio_analysis",
    "get_portfolio_analysis_history",
    "get_latest_portfolio_analysis",
    # Mentor system
    "save_portfolio_analysis_mentor",
    "save_portfolio_outcome",
    "get_recent_features",
    "get_analysis_outcomes",
    "get_analyses_without_outcomes",
    "find_similar_analyses",
    # User profile functions
    "get_user_profile",
    "update_user_profile",
    "save_user_profile",
    "load_user_profile",
    # Notifications
    "get_notifications",
    "should_send_notification",
    "log_notification",
    # Market bars cache
    "get_cached_market_bars",
    "get_last_bar_date",
    "upsert_market_bars",
    "get_cached_range",
    "get_missing_dates",
    # Legacy/Test
    "add_test_data",
    # LLM usage logging
    "log_llm_usage",
    "get_monthly_llm_usage",
]


# ============================================================================
# ANALYSIS FUNCTIONS
# ============================================================================

def get_deep_decision_cache(cache_key: str) -> Optional[Dict[str, Any]]:
    """
    Get cached DEEP canonical decision JSON by cache_key.

    Cache entries are stored in the `deep_decision_cache` table.
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT deep_json
            FROM deep_decision_cache
            WHERE cache_key = ?
            """,
            (cache_key,),
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        deep_json_str = row["deep_json"]
        if not deep_json_str:
            return None

        try:
            return json.loads(deep_json_str)
        except json.JSONDecodeError:
            return None
    except Exception as e:
        logger.error(f"❌ Failed to read deep_decision_cache: {e}", exc_info=True)
        return None


def set_deep_decision_cache(
    cache_key: str,
    symbol: str,
    as_of_analysis: str,
    quick_features_hash: str,
    deep_json: Dict[str, Any],
) -> None:
    """Insert or replace cached DEEP canonical decision JSON."""
    try:
        conn = get_connection()
        cursor = conn.cursor()

        deep_json_safe = _json_safe(deep_json)
        deep_json_str = json.dumps(deep_json_safe, ensure_ascii=False)

        cursor.execute(
            """
            INSERT OR REPLACE INTO deep_decision_cache
            (cache_key, symbol, as_of_analysis, quick_features_hash, deep_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (cache_key, symbol, as_of_analysis, quick_features_hash, deep_json_str),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Failed to write deep_decision_cache: {e}", exc_info=True)
        # Cache failures must never break the API
        return


# ============================================================================
# MARKET SNAPSHOT SECTION CACHE (PERSISTENT)
# ============================================================================

SnapshotSection = Literal["quote", "ohlc", "fundamentals", "news"]


def _iso_utc_now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_expired(expires_at: str, now_iso: Optional[str] = None) -> bool:
    """
    Best-effort expiration check for ISO timestamps.
    Stored format should be UTC '...Z', but we tolerate other ISO shapes.
    """
    if not expires_at:
        return True
    now_s = now_iso or _iso_utc_now()
    try:
        # fromisoformat does not accept 'Z' suffix directly
        exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        now_dt = datetime.fromisoformat(now_s.replace("Z", "+00:00"))
        return now_dt >= exp_dt
    except Exception:
        # If parsing fails, treat as expired to avoid serving bad cache silently.
        return True


def get_snapshot_section_cache(
    symbol: str,
    mode: str,
    section: SnapshotSection,
    *,
    allow_stale: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Read a cached MarketSnapshot section.

    Returns:
        None if missing/expired (unless allow_stale=True).
        Otherwise returns:
        {
          "payload": <dict|list>,
          "as_of": str|None,
          "fetched_at": str,
          "expires_at": str,
          "stale": bool
        }
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT as_of, fetched_at, expires_at, payload_json
            FROM market_snapshot_section_cache
            WHERE symbol = ? AND mode = ? AND section = ?
            """,
            (symbol.upper(), mode.upper(), section),
        )
        row = cursor.fetchone()
        conn.close()

        if not row:
            return None

        expires_at = row["expires_at"] or ""
        stale = _is_expired(expires_at)
        if stale and not allow_stale:
            return None

        payload_str = row["payload_json"] or ""
        if not payload_str:
            return None

        try:
            payload = json.loads(payload_str)
        except json.JSONDecodeError:
            return None

        return {
            "payload": payload,
            "as_of": row["as_of"],
            "fetched_at": row["fetched_at"],
            "expires_at": expires_at,
            "stale": bool(stale),
        }
    except Exception as e:
        logger.error(f"❌ Failed to read market_snapshot_section_cache: {e}", exc_info=True)
        return None


def set_snapshot_section_cache(
    symbol: str,
    mode: str,
    section: SnapshotSection,
    *,
    payload: Any,
    as_of: Optional[str],
    expires_at: str,
    fetched_at: Optional[str] = None,
) -> None:
    """
    Upsert a cached MarketSnapshot section.

    Notes:
    - Cache failures must never break the API.
    - `expires_at` must be an ISO timestamp (UTC recommended).
    """
    try:
        fetched_at_s = fetched_at or _iso_utc_now()
        payload_safe = _json_safe(payload)
        payload_str = json.dumps(payload_safe, ensure_ascii=False)

        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO market_snapshot_section_cache
            (symbol, mode, section, as_of, fetched_at, expires_at, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol, mode, section) DO UPDATE SET
                as_of=excluded.as_of,
                fetched_at=excluded.fetched_at,
                expires_at=excluded.expires_at,
                payload_json=excluded.payload_json
            """,
            (
                symbol.upper(),
                mode.upper(),
                section,
                as_of,
                fetched_at_s,
                expires_at,
                payload_str,
            ),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"❌ Failed to write market_snapshot_section_cache: {e}", exc_info=True)
        return

def save_analysis(
    symbol: str,
    mode: str,
    raw_prompt: str,
    raw_response: str,
    summary: str,
    risk_level: int,
    full_analysis_json: dict,
    price_at_analysis: float
) -> None:
    """Save a new analysis to the database."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        full_analysis_json_str = json.dumps(full_analysis_json, ensure_ascii=False) if full_analysis_json else None
        
        cursor.execute("""
            INSERT INTO analysis_history 
            (symbol, mode, raw_prompt, raw_response, summary, risk_level, full_analysis_json, price_at_analysis)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            symbol.upper(),
            mode,
            raw_prompt,
            raw_response,
            summary,
            risk_level,
            full_analysis_json_str,
            price_at_analysis
        ))
        
        conn.commit()
        conn.close()
        
        logger.info(f"💾 Analysis saved for {symbol.upper()} (mode: {mode})")
        
    except Exception as e:
        logger.error(f"❌ Failed to save analysis: {e}", exc_info=True)
        raise


def get_last_analysis(symbol: str, mode: str) -> Optional[Dict[str, Any]]:
    """Get the most recent analysis for a given symbol and mode."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, symbol, mode, raw_prompt, raw_response, summary, risk_level, 
                   full_analysis_json, price_at_analysis, created_at
            FROM analysis_history
            WHERE symbol = ? AND mode = ?
            ORDER BY created_at DESC
            LIMIT 1
        """, (symbol.upper(), mode))
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            result = dict(row)
            if result.get("full_analysis_json"):
                try:
                    result["full_analysis_json"] = json.loads(result["full_analysis_json"])
                except json.JSONDecodeError:
                    result["full_analysis_json"] = {}
            return result
        
        return None
        
    except Exception as e:
        logger.error(f"❌ Failed to get last analysis: {e}", exc_info=True)
        return None


def get_last_decision_for_symbol(symbol: str, mode: str) -> Optional[Dict[str, Any]]:
    """
    Get the most recent decision data for a specific symbol (for context-aware analysis).
    
    This function retrieves the last analysis to provide context for comparative reasoning.
    Extracted fields: decision, price, confidence, key reasoning, timestamp
    
    Args:
        symbol: Stock/crypto symbol (e.g., "NVDA")
        mode: "STOCK" or "CRYPTO"
    
    Returns:
        Dict with previous decision context or None if no history:
        {
            "decision": "BUY|HOLD|AVOID",
            "price_at_analysis": float,
            "confidence": int,
            "created_at": str (ISO timestamp),
            "verdict": str (Turkish: AL|TUT|SAT|KAÇIN),
            "headline_tr": str (previous headline),
            "key_reasoning": str (summary of main points),
            "technical_snapshot": dict (RSI, trend, etc.)
        }
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT full_analysis_json, price_at_analysis, created_at
            FROM analysis_history
            WHERE symbol = ? AND mode = ?
            ORDER BY created_at DESC
            LIMIT 1
        """, (symbol.upper(), mode.upper()))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        # Parse full_analysis_json to extract decision details
        full_json_str = row[0]
        price_at_analysis = row[1]
        created_at = row[2]
        
        if not full_json_str:
            return None
        
        try:
            full_json = json.loads(full_json_str)
        except json.JSONDecodeError:
            return None
        
        # Extract key fields for context
        decision = full_json.get("decision", "HOLD")
        verdict = full_json.get("verdict", "TUT")
        headline_tr = full_json.get("headline_tr", "")
        confidence = full_json.get("confidence", 50)
        
        # Extract technical snapshot if available
        technical_snapshot = {}
        evidence = full_json.get("evidence", {})
        if evidence and isinstance(evidence, dict):
            technical = evidence.get("technical", {})
            if technical:
                technical_snapshot = {
                    "rsi": technical.get("rsi", 50),
                    "trend": technical.get("trend", "NEUTRAL"),
                    "volatility": technical.get("volatility", "MEDIUM"),
                    "price": technical.get("current_price", price_at_analysis)
                }
        
        # Build key reasoning summary from reasons array
        reasons = full_json.get("reasons", [])
        thesis_bullets = full_json.get("thesis_bullets", [])
        key_reasoning = ""
        
        if reasons:
            key_reasoning = ". ".join(reasons[:3])
        elif thesis_bullets:
            key_reasoning = ". ".join(thesis_bullets[:3])
        else:
            key_reasoning = headline_tr if headline_tr else "No detailed reasoning available"
        
        # Truncate to 300 chars
        if len(key_reasoning) > 300:
            key_reasoning = key_reasoning[:297] + "..."
        
        return {
            "decision": decision,
            "verdict": verdict,
            "price_at_analysis": price_at_analysis,
            "confidence": confidence,
            "created_at": created_at,
            "headline_tr": headline_tr,
            "key_reasoning": key_reasoning,
            "technical_snapshot": technical_snapshot
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to get last decision for symbol: {e}", exc_info=True)
        return None


def get_memory_context(symbol: str, mode: str, limit: int = 20) -> List[str]:
    """Get summary fields from past analyses for AI memory context."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT summary
            FROM analysis_history
            WHERE symbol = ? AND mode = ? AND summary IS NOT NULL AND summary != ''
            ORDER BY created_at DESC
            LIMIT ?
        """, (symbol.upper(), mode, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [row[0] for row in rows if row[0]]
        
    except Exception as e:
        logger.error(f"❌ Failed to get memory context: {e}", exc_info=True)
        return []


def get_symbol_analysis_history(symbol: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Return recent analysis records for a specific symbol."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, symbol, mode, raw_prompt, raw_response, summary, risk_level,
                   full_analysis_json, price_at_analysis, created_at
            FROM analysis_history
            WHERE symbol = ?
            ORDER BY datetime(created_at) DESC
            LIMIT ?
        """, (symbol.upper(), limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
        
    except Exception as e:
        logger.error(f"❌ Failed to get symbol analysis history: {e}", exc_info=True)
        return []


def get_all_history() -> List[Dict[str, Any]]:
    """Get all analysis history from database."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, symbol, mode, raw_prompt, raw_response, summary, risk_level, 
                   full_analysis_json, price_at_analysis, created_at
            FROM analysis_history
            ORDER BY created_at DESC
        """)
        
        rows = cursor.fetchall()
        conn.close()
        
        history = []
        for row in rows:
            result = dict(row)
            if result.get("full_analysis_json"):
                try:
                    result["full_analysis_json"] = json.loads(result["full_analysis_json"])
                except json.JSONDecodeError:
                    result["full_analysis_json"] = {}
            history.append(result)
        
        return history
        
    except Exception as e:
        logger.error(f"❌ Failed to get all history: {e}", exc_info=True)
        return []


# ============================================================================
# PORTFOLIO FUNCTIONS
# ============================================================================

def add_to_portfolio(symbol: str, avg_cost: float, quantity: float) -> Dict[str, Any]:
    """Add or update a stock in the portfolio."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        symbol_upper = symbol.upper().strip()
        updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        cursor.execute("SELECT id, quantity, avg_cost FROM portfolio WHERE symbol = ?", (symbol_upper,))
        existing = cursor.fetchone()
        
        if existing:
            old_id, old_quantity, old_avg_cost = existing
            total_old_value = old_quantity * old_avg_cost
            total_new_value = quantity * avg_cost
            total_quantity = old_quantity + quantity
            new_avg_cost = (total_old_value + total_new_value) / total_quantity if total_quantity > 0 else avg_cost
            
            cursor.execute("""
                UPDATE portfolio 
                SET avg_cost = ?, quantity = ?, updated_at = ?
                WHERE symbol = ?
            """, (new_avg_cost, total_quantity, updated_at, symbol_upper))
            
            conn.commit()
            conn.close()
            
            return {
                "success": True,
                "message": f"Portfolio updated: {symbol_upper}",
                "symbol": symbol_upper,
                "avg_cost": new_avg_cost,
                "quantity": total_quantity
            }
        else:
            cursor.execute("""
                INSERT INTO portfolio (symbol, avg_cost, quantity, updated_at)
                VALUES (?, ?, ?, ?)
            """, (symbol_upper, avg_cost, quantity, updated_at))
            
            conn.commit()
            portfolio_id = cursor.lastrowid
            conn.close()
            
            return {
                "success": True,
                "message": f"Added to portfolio: {symbol_upper}",
                "id": portfolio_id,
                "symbol": symbol_upper,
                "avg_cost": avg_cost,
                "quantity": quantity
            }
            
    except Exception as e:
        logger.error(f"❌ Failed to add to portfolio: {e}", exc_info=True)
        return {"success": False, "message": str(e)}


def remove_from_portfolio(symbol: str, quantity: Optional[float] = None) -> Dict[str, Any]:
    """Remove a stock from portfolio (partial or full)."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        symbol_upper = symbol.upper().strip()
        
        cursor.execute("SELECT id, quantity, avg_cost FROM portfolio WHERE symbol = ?", (symbol_upper,))
        existing = cursor.fetchone()
        
        if not existing:
            conn.close()
            return {
                "success": False,
                "message": f"Symbol {symbol_upper} not found in portfolio"
            }
        
        portfolio_id, current_quantity, avg_cost = existing
        
        if quantity is None or quantity >= current_quantity:
            cursor.execute("DELETE FROM portfolio WHERE symbol = ?", (symbol_upper,))
            conn.commit()
            conn.close()
            return {
                "success": True,
                "message": f"Removed {symbol_upper} from portfolio",
                "symbol": symbol_upper
            }
        else:
            new_quantity = current_quantity - quantity
            updated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
                UPDATE portfolio 
                SET quantity = ?, updated_at = ?
                WHERE symbol = ?
            """, (new_quantity, updated_at, symbol_upper))
            
            conn.commit()
            conn.close()
            
            return {
                "success": True,
                "message": f"Removed {quantity} shares of {symbol_upper}",
                "symbol": symbol_upper,
                "remaining_quantity": new_quantity,
                "avg_cost": avg_cost
            }
            
    except Exception as e:
        logger.error(f"❌ Failed to remove from portfolio: {e}", exc_info=True)
        return {"success": False, "message": str(e)}


def get_portfolio() -> List[Dict[str, Any]]:
    """Get all stocks in the portfolio."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, symbol, avg_cost, quantity, created_at, updated_at
            FROM portfolio
            ORDER BY symbol
        """)
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
        
    except Exception as e:
        logger.error(f"❌ Failed to get portfolio: {e}", exc_info=True)
        return []


def get_relevant_symbols_for_news() -> set:
    """
    Get all symbols that should be monitored for news:
    - Portfolio holdings (portfolio table)
    - Past trades (portfolio_transactions table, last 90 days)
    - Analyzed symbols (analysis_history table, last 30 days)
    
    Returns:
        Set of normalized symbol strings (uppercase)
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        symbols = set()
        
        # 1. Portfolio holdings
        cursor.execute("""
            SELECT DISTINCT symbol FROM portfolio
        """)
        for row in cursor.fetchall():
            if row["symbol"]:
                symbols.add(row["symbol"].upper().strip())
        
        # 2. Past trades (last 90 days)
        cursor.execute("""
            SELECT DISTINCT symbol 
            FROM portfolio_transactions 
            WHERE created_at >= date('now', '-90 days')
        """)
        for row in cursor.fetchall():
            if row["symbol"]:
                symbols.add(row["symbol"].upper().strip())
        
        # 3. Analyzed symbols (last 30 days)
        cursor.execute("""
            SELECT DISTINCT symbol 
            FROM analysis_history 
            WHERE created_at >= date('now', '-30 days')
        """)
        for row in cursor.fetchall():
            if row["symbol"]:
                symbols.add(row["symbol"].upper().strip())
        
        conn.close()
        
        logger.info(f"📊 Found {len(symbols)} relevant symbols for news monitoring")
        return symbols
        
    except Exception as e:
        logger.error(f"❌ Failed to get relevant symbols for news: {e}", exc_info=True)
        return set()


def get_watched_symbols() -> List[Dict[str, Any]]:
    """
    Get all watched symbols from the watchlist.
    
    Returns:
        List of dicts with symbol, mode, created_at, updated_at
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, symbol, mode, created_at, updated_at
            FROM watched_symbols
            ORDER BY symbol
        """)
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]
        
    except Exception as e:
        logger.error(f"❌ Failed to get watched symbols: {e}", exc_info=True)
        return []


def add_watched_symbol(symbol: str, mode: str = "STOCK") -> Dict[str, Any]:
    """
    Add a symbol to the watchlist.
    
    Args:
        symbol: Stock/crypto symbol (e.g., "NVDA", "AAPL")
        mode: "STOCK" or "CRYPTO" (default: "STOCK")
    
    Returns:
        Dict with success status and message
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        symbol_norm = symbol.upper().strip()
        mode_norm = mode.upper().strip()
        
        if mode_norm not in ["STOCK", "CRYPTO"]:
            mode_norm = "STOCK"
        
        # Insert or replace (upsert)
        cursor.execute("""
            INSERT OR REPLACE INTO watched_symbols (symbol, mode, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        """, (symbol_norm, mode_norm))
        
        conn.commit()
        conn.close()
        
        logger.info(f"✅ Added watched symbol: {symbol_norm} ({mode_norm})")
        return {
            "success": True,
            "message": f"Added {symbol_norm} to watchlist",
            "symbol": symbol_norm,
            "mode": mode_norm
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to add watched symbol: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"Failed to add watched symbol: {str(e)}"
        }


def remove_watched_symbol(symbol: str) -> Dict[str, Any]:
    """
    Remove a symbol from the watchlist.
    
    Args:
        symbol: Stock/crypto symbol to remove
    
    Returns:
        Dict with success status and message
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        symbol_norm = symbol.upper().strip()
        
        cursor.execute("""
            DELETE FROM watched_symbols WHERE symbol = ?
        """, (symbol_norm,))
        
        deleted_count = cursor.rowcount
        conn.commit()
        conn.close()
        
        if deleted_count > 0:
            logger.info(f"✅ Removed watched symbol: {symbol_norm}")
            return {
                "success": True,
                "message": f"Removed {symbol_norm} from watchlist"
            }
        else:
            return {
                "success": False,
                "message": f"Symbol {symbol_norm} not found in watchlist"
            }
        
    except Exception as e:
        logger.error(f"❌ Failed to remove watched symbol: {e}", exc_info=True)
        return {
            "success": False,
            "message": f"Failed to remove watched symbol: {str(e)}"
        }


def get_watched_symbols_only() -> set:
    """
    Get only watched symbols (for Hermes watchlist mechanism).
    This is the primary source for news processing in Hermes mode.
    
    Returns:
        Set of normalized symbol strings (uppercase)
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT DISTINCT symbol FROM watched_symbols
        """)
        
        symbols = set()
        for row in cursor.fetchall():
            if row["symbol"]:
                symbols.add(row["symbol"].upper().strip())
        
        conn.close()
        
        return symbols
        
    except Exception as e:
        logger.error(f"❌ Failed to get watched symbols: {e}", exc_info=True)
        return set()


def add_portfolio_transaction(symbol: str, quantity: float, price: float, transaction_type: str) -> Dict[str, Any]:
    """
    Add a portfolio transaction (BUY or SELL) and update portfolio accordingly.
    
    Args:
        symbol: Stock symbol
        quantity: Number of shares
        price: Price per share
        transaction_type: "BUY" or "SELL"
    
    Returns:
        Dictionary with success status and details
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        symbol_upper = symbol.upper().strip()
        tx_type = transaction_type.upper().strip()
        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Record the transaction
        cursor.execute("""
            INSERT INTO portfolio_transactions (symbol, quantity, price, transaction_type, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (symbol_upper, quantity, price, tx_type, created_at))
        
        conn.commit()
        conn.close()
        
        # Update portfolio based on transaction type
        if tx_type == "BUY":
            result = add_to_portfolio(symbol_upper, price, quantity)
        elif tx_type == "SELL":
            result = remove_from_portfolio(symbol_upper, quantity)
        else:
            result = {"success": False, "message": f"Unknown transaction type: {tx_type}"}
        
        if result.get("success"):
            result["transaction_recorded"] = True
            result["transaction_type"] = tx_type
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Failed to add portfolio transaction: {e}", exc_info=True)
        return {"success": False, "message": str(e)}


# ============================================================================
# PORTFOLIO ANALYSIS FUNCTIONS
# ============================================================================

def save_portfolio_analysis(
    portfolio_json: str,
    summary: str,
    risk_level: int,
    full_json: dict
) -> None:
    """Save a portfolio analysis to the database."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Sanitize full_json to ensure JSON serializability
        safe_full_json = _json_safe(full_json) if full_json else None
        full_json_str = json.dumps(safe_full_json, ensure_ascii=False) if safe_full_json else None
        
        cursor.execute("""
            INSERT INTO portfolio_analysis_history 
            (portfolio_json, summary, risk_level, full_json)
            VALUES (?, ?, ?, ?)
        """, (portfolio_json, summary, risk_level, full_json_str))
        
        conn.commit()
        conn.close()
        
        logger.info("💾 Portfolio analysis saved")
        
    except Exception as e:
        logger.error(f"❌ Failed to save portfolio analysis: {e}", exc_info=True)
        raise


def get_portfolio_analysis_history(limit: int = 50) -> List[Dict[str, Any]]:
    """Get portfolio analysis history from database."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, portfolio_json, summary, risk_level, full_json, created_at
            FROM portfolio_analysis_history
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        history = []
        for row in rows:
            result = dict(row)
            if result.get("portfolio_json"):
                try:
                    result["portfolio_json"] = json.loads(result["portfolio_json"])
                except json.JSONDecodeError:
                    pass
            if result.get("full_json"):
                try:
                    result["full_json"] = json.loads(result["full_json"])
                except json.JSONDecodeError:
                    result["full_json"] = {}
            history.append(result)
        
        return history
        
    except Exception as e:
        logger.error(f"❌ Failed to get portfolio analysis history: {e}", exc_info=True)
        return []


def get_latest_portfolio_analysis() -> Optional[Dict[str, Any]]:
    """Get the most recent portfolio analysis from database (for cache check)."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, portfolio_json, summary, risk_level, full_json, created_at
            FROM portfolio_analysis_history
            ORDER BY created_at DESC
            LIMIT 1
        """)
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            result = dict(row)
            if result.get("portfolio_json"):
                try:
                    result["portfolio_json"] = json.loads(result["portfolio_json"])
                except json.JSONDecodeError:
                    pass
            if result.get("full_json"):
                try:
                    result["full_json"] = json.loads(result["full_json"])
                except json.JSONDecodeError:
                    result["full_json"] = {}
            return result
        
        return None
        
    except Exception as e:
        logger.error(f"❌ Failed to get latest portfolio analysis: {e}", exc_info=True)
        return None


# ============================================================================
# MENTOR SYSTEM FUNCTIONS (Portfolio Analysis with Features & Outcomes)
# ============================================================================

def save_portfolio_analysis_mentor(
    as_of: str,
    mode: str,
    summary_json: dict,
    full_json: dict,
    feature_json: dict
) -> int:
    """
    Save portfolio analysis to mentor system tables.
    Returns the analysis_id for linking features/outcomes.
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Sanitize JSON data
        safe_summary = _json_safe(summary_json) if summary_json else None
        safe_full = _json_safe(full_json) if full_json else None
        safe_features = _json_safe(feature_json) if feature_json else None
        
        summary_str = json.dumps(safe_summary, ensure_ascii=False) if safe_summary else None
        full_str = json.dumps(safe_full, ensure_ascii=False) if safe_full else None
        feature_str = json.dumps(safe_features, ensure_ascii=False) if safe_features else None
        
        # Insert into portfolio_analyses
        cursor.execute("""
            INSERT INTO portfolio_analyses (as_of, mode, summary_json, full_json)
            VALUES (?, ?, ?, ?)
        """, (as_of, mode, summary_str, full_str))
        
        analysis_id = cursor.lastrowid
        
        # Insert feature vector
        if feature_str:
            cursor.execute("""
                INSERT INTO portfolio_features (analysis_id, feature_json)
                VALUES (?, ?)
            """, (analysis_id, feature_str))
        
        conn.commit()
        conn.close()
        
        logger.info(f"💾 Portfolio analysis saved to mentor system (id={analysis_id})")
        return analysis_id
        
    except Exception as e:
        logger.error(f"❌ Failed to save portfolio analysis to mentor system: {e}", exc_info=True)
        raise


def save_portfolio_outcome(
    analysis_id: int,
    horizon: int,
    return_pct: float,
    return_usd: float
) -> None:
    """Save forward return outcome for an analysis."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT OR REPLACE INTO portfolio_outcomes 
            (analysis_id, horizon, return_pct, return_usd)
            VALUES (?, ?, ?, ?)
        """, (analysis_id, horizon, return_pct, return_usd))
        
        conn.commit()
        conn.close()
        
        logger.info(f"💾 Portfolio outcome saved (analysis_id={analysis_id}, horizon={horizon}d)")
        
    except Exception as e:
        logger.error(f"❌ Failed to save portfolio outcome: {e}", exc_info=True)
        raise


def get_recent_features(limit: int = 100) -> List[Dict[str, Any]]:
    """Get recent feature vectors with their analysis IDs."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT pf.id, pf.analysis_id, pf.feature_json, pa.created_at
            FROM portfolio_features pf
            JOIN portfolio_analyses pa ON pf.analysis_id = pa.id
            ORDER BY pa.created_at DESC
            LIMIT ?
        """, (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        features = []
        for row in rows:
            result = dict(row)
            if result.get("feature_json"):
                try:
                    result["feature_json"] = json.loads(result["feature_json"])
                except json.JSONDecodeError:
                    result["feature_json"] = {}
            features.append(result)
        
        return features
        
    except Exception as e:
        logger.error(f"❌ Failed to get recent features: {e}", exc_info=True)
        return []


def get_analysis_outcomes(analysis_id: int) -> Dict[int, Dict[str, Any]]:
    """Get outcomes for a specific analysis, keyed by horizon."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT horizon, return_pct, return_usd, computed_at
            FROM portfolio_outcomes
            WHERE analysis_id = ?
        """, (analysis_id,))
        
        rows = cursor.fetchall()
        conn.close()
        
        outcomes = {}
        for row in rows:
            outcomes[row["horizon"]] = dict(row)
        
        return outcomes
        
    except Exception as e:
        logger.error(f"❌ Failed to get analysis outcomes: {e}", exc_info=True)
        return {}


def get_analyses_without_outcomes(horizon: int, limit: int = 50) -> List[Dict[str, Any]]:
    """Get analyses that don't have outcomes for a given horizon yet."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT pa.id, pa.as_of, pa.full_json, pa.created_at
            FROM portfolio_analyses pa
            LEFT JOIN portfolio_outcomes po ON pa.id = po.analysis_id AND po.horizon = ?
            WHERE po.id IS NULL
            ORDER BY pa.created_at ASC
            LIMIT ?
        """, (horizon, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        analyses = []
        for row in rows:
            result = dict(row)
            if result.get("full_json"):
                try:
                    result["full_json"] = json.loads(result["full_json"])
                except json.JSONDecodeError:
                    result["full_json"] = {}
            analyses.append(result)
        
        return analyses
        
    except Exception as e:
        logger.error(f"❌ Failed to get analyses without outcomes: {e}", exc_info=True)
        return []


def find_similar_analyses(current_features: dict, k: int = 5, limit_recent: int = 100) -> List[Dict[str, Any]]:
    """
    Find k most similar analyses using cosine similarity on feature vectors.
    Returns list of dicts with: analysis_id, similarity_score, outcomes
    """
    try:
        import math
        
        # Get recent features
        recent_features = get_recent_features(limit=limit_recent)
        
        if not recent_features:
            return []
        
        # Extract feature vector from current_features
        current_vec = _extract_feature_vector(current_features)
        if not current_vec:
            return []
        
        # Compute similarities
        similarities = []
        for feat in recent_features:
            feat_vec = _extract_feature_vector(feat.get("feature_json", {}))
            if not feat_vec:
                continue
            
            # Cosine similarity
            similarity = _cosine_similarity(current_vec, feat_vec)
            if similarity > 0:  # Only include positive similarities
                analysis_id = feat.get("analysis_id")
                outcomes = get_analysis_outcomes(analysis_id)
                similarities.append({
                    "analysis_id": analysis_id,
                    "similarity_score": similarity,
                    "outcomes": outcomes,
                    "created_at": feat.get("created_at")
                })
        
        # Sort by similarity (descending) and return top k
        similarities.sort(key=lambda x: x["similarity_score"], reverse=True)
        return similarities[:k]
        
    except Exception as e:
        logger.error(f"❌ Failed to find similar analyses: {e}", exc_info=True)
        return []


def _extract_feature_vector(features: dict) -> List[float]:
    """Extract normalized feature vector from features dict."""
    try:
        # Order matters - must be consistent
        vec = [
            features.get("top3_weight_pct", 0.0) / 100.0,  # Normalize to 0-1
            features.get("concentration_score", 0.0) / 100.0,
            features.get("avg_rsi", 50.0) / 100.0,  # Normalize RSI to 0-1
            features.get("avg_vol_level", 0.0) / 2.0,  # LOW=0, MED=1, HIGH=2 -> 0-1
            features.get("bearish_news_count", 0.0) / 10.0,  # Cap at 10
            features.get("avg_news_score", 0.0) / 100.0,
            features.get("pnl_dispersion", 0.0) / 100.0,  # Normalize
            features.get("portfolio_return_recent", 0.0) / 50.0  # Cap at ±50%
        ]
        return vec
    except Exception as e:
        logger.error(f"❌ Failed to extract feature vector: {e}", exc_info=True)
        return []


def _cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    try:
        import math
        if len(vec1) != len(vec2):
            return 0.0
        
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        magnitude1 = math.sqrt(sum(a * a for a in vec1))
        magnitude2 = math.sqrt(sum(a * a for a in vec2))
        
        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0
        
        return dot_product / (magnitude1 * magnitude2)
    except Exception as e:
        logger.error(f"❌ Failed to compute cosine similarity: {e}", exc_info=True)
        return 0.0


# ============================================================================
# USER PROFILE FUNCTIONS
# ============================================================================

def get_user_profile() -> Optional[Dict[str, Any]]:
    """Return the latest user profile settings as a dict, or None if not set."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, settings_json, created_at
            FROM user_profile
            ORDER BY id DESC
            LIMIT 1
        """)
        
        row = cursor.fetchone()
        conn.close()
        
        if row:
            result = dict(row)
            if result.get("settings_json"):
                try:
                    result["settings_json"] = json.loads(result["settings_json"])
                except json.JSONDecodeError:
                    result["settings_json"] = {}
            return result
        
        return None
        
    except Exception as e:
        logger.error(f"❌ Failed to get user profile: {e}", exc_info=True)
        return None


# Alias for backward compatibility
load_user_profile = get_user_profile


def save_user_profile(settings: Dict[str, Any]) -> None:
    """Save or update user profile settings in the database."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        settings_json_str = json.dumps(settings, ensure_ascii=False) if settings else None
        
        cursor.execute("SELECT COUNT(*) FROM user_profile")
        count = cursor.fetchone()[0]
        
        if count == 0:
            cursor.execute("""
                INSERT INTO user_profile (settings_json)
                VALUES (?)
            """, (settings_json_str,))
        else:
            cursor.execute("""
                UPDATE user_profile
                SET settings_json = ?
                WHERE id = (SELECT id FROM user_profile ORDER BY id DESC LIMIT 1)
            """, (settings_json_str,))
        
        conn.commit()
        conn.close()
        
        logger.info("💾 User profile saved")
        
    except Exception as e:
        logger.error(f"❌ Failed to save user profile: {e}", exc_info=True)
        raise


def update_user_profile(risk_profile: Optional[str] = None, system_instruction: Optional[str] = None) -> Dict[str, Any]:
    """Update user profile (risk profile and/or system instruction)."""
    try:
        current = get_user_profile()
        
        if current and current.get("settings_json"):
            settings = current["settings_json"]
            if isinstance(settings, str):
                try:
                    settings = json.loads(settings)
                except:
                    settings = {}
        else:
            settings = {}
        
        if risk_profile is not None:
            settings["risk_profile"] = risk_profile
        if system_instruction is not None:
            settings["system_instruction"] = system_instruction
        
        save_user_profile(settings)
        
        return {
            "success": True,
            "message": "Profil güncellendi",
            "risk_profile": settings.get("risk_profile"),
            "system_instruction": settings.get("system_instruction")
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to update user profile: {e}", exc_info=True)
        return {"success": False, "message": str(e)}


# ============================================================================
# NOTIFICATIONS
# ============================================================================

def get_notifications(limit: int = 50) -> List[Dict[str, Any]]:
    """Get notifications from database."""
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, timestamp, title, message, type
            FROM notifications
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))
        
        rows = cursor.fetchall()
        conn.close()
        
        return [dict(row) for row in rows]

    except Exception as e:
        logger.error(f"❌ Failed to get notifications: {e}", exc_info=True)
        return []


def save_news_outcome(symbol: str, news_hash: str, actual_impact: str, price_change_pct: float) -> bool:
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE news_analysis_history
            SET what_happened = ?, full_analysis_json = json_patch(
                COALESCE(full_analysis_json, '{}'),
                json_object('actual_impact', ?, 'price_change_pct', ?)
            )
            WHERE symbol = ? AND news_hash = ?
        """, (actual_impact, actual_impact, price_change_pct, symbol.upper(), news_hash))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"❌ save_news_outcome failed: {e}")
        return False


def get_similar_news_outcomes(symbol: str, title_keywords: List[str], limit: int = 5) -> List[Dict[str, Any]]:
    try:
        conn = get_connection()
        cursor = conn.cursor()
        like_clauses = " OR ".join(["LOWER(title) LIKE ?" for _ in title_keywords])
        params = [f"%{kw.lower()}%" for kw in title_keywords] + [symbol.upper(), limit]
        cursor.execute(f"""
            SELECT title, expected_impact, what_happened, confidence, time_horizon,
                   full_analysis_json, created_at
            FROM news_analysis_history
            WHERE ({like_clauses}) AND symbol = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, params)
        rows = cursor.fetchall()
        conn.close()
        results = []
        for row in rows:
            r = dict(row)
            price_change = None
            if r.get("full_analysis_json"):
                try:
                    parsed = json.loads(r["full_analysis_json"])
                    price_change = parsed.get("price_change_pct")
                except Exception:
                    pass
            results.append({
                "title": r["title"],
                "expected_impact": r["expected_impact"],
                "actual_impact": r["what_happened"],
                "price_change_pct": price_change,
                "confidence": r["confidence"],
                "time_horizon": r["time_horizon"],
                "created_at": r["created_at"],
            })
        return results
    except Exception as e:
        logger.error(f"❌ get_similar_news_outcomes failed: {e}")
        return []


def _parse_news_row(r: dict) -> dict:
    price_change = None
    reason = None
    impact_reason = r.get("impact_reason") or ""
    if r.get("full_analysis_json"):
        try:
            parsed = json.loads(r["full_analysis_json"])
            price_change = parsed.get("price_change_pct")
            reason = parsed.get("impact_reason") or parsed.get("reason") or parsed.get("reasons")
            if isinstance(reason, list):
                reason = "; ".join(reason)
            if not impact_reason:
                impact_reason = parsed.get("impact_reason", "")
        except Exception:
            pass
    return {
        "id": r["id"],
        "symbol": r.get("symbol", ""),
        "title": r["title"],
        "source": r.get("source"),
        "impact": r["expected_impact"],
        "actual_impact": r.get("what_happened"),
        "confidence": r["confidence"],
        "time_horizon": r["time_horizon"],
        "price_change_pct": price_change,
        "reason": reason or impact_reason,
        "advice": r.get("advice") or "",
        "comment": r.get("comment") or "",
        "created_at": r["created_at"],
    }


def get_news_history(symbol: str, limit: int = 20) -> List[Dict[str, Any]]:
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, symbol, title, source, expected_impact, what_happened, confidence,
                   time_horizon, full_analysis_json, advice, comment, created_at
            FROM news_analysis_history
            WHERE symbol = ?
            ORDER BY created_at DESC
            LIMIT ?
        """, (symbol.upper(), limit))
        rows = cursor.fetchall()
        conn.close()
        return [_parse_news_row(dict(r)) for r in rows]
    except Exception as e:
        logger.error(f"❌ get_news_history failed: {e}")
        return []


def get_all_news_history(limit: int = 50) -> List[Dict[str, Any]]:
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, symbol, title, source, expected_impact, what_happened, confidence,
                   time_horizon, full_analysis_json, advice, comment, created_at
            FROM news_analysis_history
            ORDER BY created_at DESC
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        conn.close()
        return [_parse_news_row(dict(r)) for r in rows]
    except Exception as e:
        logger.error(f"❌ get_all_news_history failed: {e}")
        return []


def save_price_snapshot(news_hash: str, symbol: str, price: float) -> bool:
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO news_price_snapshots
                (news_hash, symbol, price_at_news, captured_at, outcome_checked)
            VALUES (?, ?, ?, ?, 0)
        """, (news_hash, symbol.upper(), price, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"❌ save_price_snapshot failed: {e}")
        return False


def get_pending_snapshots(older_than_minutes: int = 120) -> List[Dict[str, Any]]:
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cutoff = (datetime.now() - timedelta(minutes=older_than_minutes)).isoformat()
        cursor.execute("""
            SELECT id, news_hash, symbol, price_at_news, captured_at
            FROM news_price_snapshots
            WHERE outcome_checked = 0 AND captured_at <= ?
            ORDER BY captured_at ASC
        """, (cutoff,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"❌ get_pending_snapshots failed: {e}")
        return []


def mark_snapshot_done(snapshot_id: int) -> None:
    try:
        conn = get_connection()
        conn.execute("UPDATE news_price_snapshots SET outcome_checked = 1 WHERE id = ?", (snapshot_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"❌ mark_snapshot_done failed: {e}")


# ============================================================================
# NOTIFICATION GATING (Cooldown System)
# ============================================================================

def generate_event_key(title: str, source: Optional[str] = None, content: Optional[str] = None) -> str:
    """
    Generate a stable event key from news title, source, and content.
    Used for deduplication - same news should produce same key.
    
    Args:
        title: News headline
        source: News source (e.g., "Reuters")
        content: Optional content text (first 80 chars used)
    
    Returns:
        str: Hash-based event key (stable for same input)
    """
    import hashlib
    import re
    
    # Normalize: lowercase, remove extra whitespace
    normalized_parts = []
    
    if title:
        normalized_title = re.sub(r'\s+', ' ', title.strip().lower())
        normalized_parts.append(normalized_title)
    
    if source:
        normalized_source = re.sub(r'\s+', ' ', source.strip().lower())
        normalized_parts.append(normalized_source)
    
    if content:
        # Use first 80 characters
        normalized_content = re.sub(r'\s+', ' ', content.strip().lower())[:80]
        normalized_parts.append(normalized_content)
    
    # Combine and hash
    combined = "|".join(normalized_parts)
    event_key = hashlib.md5(combined.encode('utf-8')).hexdigest()[:16]
    
    return event_key


def should_send_notification(
    symbol: str, 
    event_key: str, 
    score: int,
    cooldown_minutes: int = 30,
    min_score: int = 25,
    max_per_day_per_symbol: Optional[int] = None
) -> Tuple[bool, str]:
    """
    Check if notification should be sent based on score threshold, cooldown, and deduplication.
    
    Args:
        symbol: Stock symbol (e.g., "NVDA")
        event_key: Event identifier (hash-based, stable for same news)
        score: Importance score (0-100)
        cooldown_minutes: Cooldown period in minutes (default: 30)
        min_score: Minimum score threshold (default: 25)
        max_per_day_per_symbol: Optional max notifications per day per symbol (default: None = no limit)
    
    Returns:
        Tuple[bool, str]: (should_send, reason)
            - (True, "sent") if should send
            - (False, "below_threshold") if score < min_score
            - (False, "cooldown") if within cooldown period
            - (False, "dedupe") if same event_key already sent today
            - (False, "max_per_day") if exceeded max_per_day_per_symbol
    """
    try:
        # Check score threshold
        if score < min_score:
            return (False, "below_threshold")
        
        conn = get_connection()
        cursor = conn.cursor()
        
        # Check deduplication: same event_key for same symbol today
        cursor.execute("""
            SELECT COUNT(*) 
            FROM notification_log
            WHERE symbol = ? 
              AND event_key = ?
              AND date(created_at) = date('now')
        """, (symbol.upper(), event_key))
        
        dedupe_count = cursor.fetchone()[0]
        if dedupe_count > 0:
            conn.close()
            return (False, "dedupe")
        
        # Check cooldown: same symbol+event_key within cooldown period
        cursor.execute(f"""
            SELECT COUNT(*) 
            FROM notification_log
            WHERE symbol = ? 
              AND event_key = ?
              AND datetime(created_at) > datetime('now', '-{cooldown_minutes} minutes')
        """, (symbol.upper(), event_key))
        
        cooldown_count = cursor.fetchone()[0]
        if cooldown_count > 0:
            conn.close()
            return (False, "cooldown")
        
        # Check max_per_day_per_symbol if specified
        if max_per_day_per_symbol is not None:
            cursor.execute("""
                SELECT COUNT(*) 
                FROM notification_log
                WHERE symbol = ? 
                  AND date(created_at) = date('now')
            """, (symbol.upper(),))
            
            daily_count = cursor.fetchone()[0]
            if daily_count >= max_per_day_per_symbol:
                conn.close()
                return (False, "max_per_day")
        
        conn.close()
        return (True, "sent")
        
    except Exception as e:
        logger.error(f"❌ Failed to check notification gating: {e}", exc_info=True)
        # On error, allow notification (fail open)
        return (True, "sent")


def log_notification(symbol: str, event_key: str, importance_score: int, title: Optional[str] = None) -> None:
    """
    Log a notification event to track cooldown periods.
    
    Args:
        symbol: Stock symbol (e.g., "NVDA")
        event_key: Event identifier (hash-based, stable for same news)
        importance_score: Importance score (0-100)
        title: Optional news title
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO notification_log (symbol, event_key, importance_score, title)
            VALUES (?, ?, ?, ?)
        """, (symbol.upper(), event_key, importance_score, title))
        
        conn.commit()
        conn.close()
        
        logger.debug(f"📝 Notification logged: {symbol.upper()}, {event_key}, score={importance_score}")
        
    except Exception as e:
        logger.error(f"❌ Failed to log notification: {e}", exc_info=True)
        # Don't raise - logging failure shouldn't block notification


# ============================================================================
# LEGACY/TEST FUNCTIONS
# ============================================================================

def add_test_data(symbol: str = "", price: float = 0.0, decision: str = "") -> None:
    """Legacy compatibility function. No-op."""
    pass


# ============================================================================
# LLM USAGE LOGGING (Budget tracking)
# ============================================================================

def log_llm_usage(
    model: str,
    purpose: str,
    symbol: Optional[str],
    request_id: Optional[str],
    prompt_text: str,
    output_text: str,
    prompt_tokens: Optional[int],
    output_tokens: Optional[int],
    estimated_cost_usd: float,
    is_estimated: bool
) -> None:
    """
    Log LLM usage to database for budget tracking.
    
    Args:
        model: Model name (e.g., "gemini-flash-latest")
        purpose: Purpose of the call (e.g., "ai_insight", "news_batch", "telegram_digest")
        symbol: Optional stock/crypto symbol
        request_id: Optional request identifier (UUID)
        prompt_text: Prompt text (for character count)
        output_text: Output text (for character count)
        prompt_tokens: Actual prompt tokens from SDK (None if not available)
        output_tokens: Actual output tokens from SDK (None if not available)
        estimated_cost_usd: Estimated cost in USD (always provided)
        is_estimated: True if cost/tokens are estimated, False if from SDK
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        prompt_chars = len(prompt_text) if prompt_text else 0
        output_chars = len(output_text) if output_text else 0
        
        total_tokens = None
        if prompt_tokens is not None and output_tokens is not None:
            total_tokens = prompt_tokens + output_tokens
        
        cursor.execute("""
            INSERT INTO llm_usage_log (
                model, purpose, symbol, request_id,
                prompt_chars, output_chars,
                prompt_tokens, output_tokens, total_tokens,
                estimated_cost_usd, is_estimated
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            model,
            purpose,
            symbol,
            request_id,
            prompt_chars,
            output_chars,
            prompt_tokens,
            output_tokens,
            total_tokens,
            estimated_cost_usd,
            1 if is_estimated else 0
        ))
        
        conn.commit()
        conn.close()
        
    except Exception as e:
        logger.error(f"❌ Failed to log LLM usage: {e}", exc_info=True)
        # Don't raise - logging failure shouldn't block the main flow


def get_monthly_llm_usage(year: int, month: int) -> Dict[str, Any]:
    """
    Get monthly LLM usage statistics.
    
    Args:
        year: Year (e.g., 2025)
        month: Month (1-12)
    
    Returns:
        dict with keys:
        - year: int
        - month: int
        - calls: int (total number of calls)
        - total_tokens: int | None (sum of total_tokens, None if all are None)
        - total_cost_usd: float (sum of estimated_cost_usd)
        - last_30_entries: list[dict] (last 30 log entries)
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Query for the month
        cursor.execute("""
            SELECT 
                COUNT(*) as calls,
                SUM(total_tokens) as total_tokens,
                SUM(estimated_cost_usd) as total_cost_usd
            FROM llm_usage_log
            WHERE strftime('%Y', created_at) = ? 
              AND strftime('%m', created_at) = ?
        """, (str(year), f"{month:02d}"))
        
        row = cursor.fetchone()
        calls = row[0] if row[0] else 0
        total_tokens = row[1] if row[1] is not None else None
        total_cost_usd = float(row[2]) if row[2] is not None else 0.0
        
        # Get last 30 entries
        cursor.execute("""
            SELECT 
                id, created_at, model, purpose, symbol, request_id,
                prompt_chars, output_chars,
                prompt_tokens, output_tokens, total_tokens,
                estimated_cost_usd, is_estimated
            FROM llm_usage_log
            ORDER BY created_at DESC
            LIMIT 30
        """)
        
        rows = cursor.fetchall()
        last_30_entries = []
        for row in rows:
            last_30_entries.append({
                "id": row[0],
                "created_at": row[1],
                "model": row[2],
                "purpose": row[3],
                "symbol": row[4],
                "request_id": row[5],
                "prompt_chars": row[6],
                "output_chars": row[7],
                "prompt_tokens": row[8],
                "output_tokens": row[9],
                "total_tokens": row[10],
                "estimated_cost_usd": float(row[11]) if row[11] is not None else 0.0,
                "is_estimated": bool(row[12])
            })
        
        conn.close()
        
        return {
            "year": year,
            "month": month,
            "calls": calls,
            "total_tokens": total_tokens,
            "total_cost_usd": total_cost_usd,
            "last_30_entries": last_30_entries
        }
        
    except Exception as e:
        logger.error(f"❌ Failed to get monthly LLM usage: {e}", exc_info=True)
        return {
            "year": year,
            "month": month,
            "calls": 0,
            "total_tokens": None,
            "total_cost_usd": 0.0,
            "last_30_entries": []
        }


# ============================================================================
# MARKET BARS CACHE (Self-healing chart data)
# ============================================================================

def get_cached_market_bars(symbol: str, mode: str, timeframe: str, limit: int = 2000) -> List[Dict[str, Any]]:
    """
    Get cached market bars from database.
    Returns bars in ascending date order (oldest first) for frontend chart.
    
    Args:
        symbol: Stock/crypto symbol (e.g., "NVDA")
        mode: "STOCK" or "CRYPTO"
        timeframe: Timeframe string (e.g., "1d")
        limit: Maximum number of bars to return (default: 2000)
    
    Returns:
        List of dicts with keys: date, open, high, low, close, volume
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT bar_date, open, high, low, close, volume
            FROM market_bars
            WHERE symbol = ? AND mode = ? AND timeframe = ?
            ORDER BY bar_date ASC
            LIMIT ?
        """, (symbol.upper(), mode.upper(), timeframe, limit))
        
        rows = cursor.fetchall()
        conn.close()
        
        bars = []
        for row in rows:
            bars.append({
                "date": row[0],
                "open": float(row[1]) if row[1] is not None else 0.0,
                "high": float(row[2]) if row[2] is not None else 0.0,
                "low": float(row[3]) if row[3] is not None else 0.0,
                "close": float(row[4]) if row[4] is not None else 0.0,
                "volume": int(row[5]) if row[5] is not None else 0
            })
        
        return bars
        
    except Exception as e:
        logger.error(f"❌ Failed to get cached market bars: {e}", exc_info=True)
        return []


def get_last_bar_date(symbol: str, mode: str, timeframe: str) -> Optional[str]:
    """
    Get the most recent bar date from cache.
    
    Args:
        symbol: Stock/crypto symbol
        mode: "STOCK" or "CRYPTO"
        timeframe: Timeframe string (e.g., "1d")
    
    Returns:
        ISO date string (YYYY-MM-DD) or None if no data
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT MAX(bar_date)
            FROM market_bars
            WHERE symbol = ? AND mode = ? AND timeframe = ?
        """, (symbol.upper(), mode.upper(), timeframe))
        
        row = cursor.fetchone()
        conn.close()
        
        if row and row[0]:
            return row[0]
        return None
        
    except Exception as e:
        logger.error(f"❌ Failed to get last bar date: {e}", exc_info=True)
        return None


def upsert_market_bars(symbol: str, mode: str, timeframe: str, bars: List[Dict[str, Any]]) -> int:
    """
    Insert or update market bars in cache (idempotent).
    
    Args:
        symbol: Stock/crypto symbol
        mode: "STOCK" or "CRYPTO"
        timeframe: Timeframe string (e.g., "1d")
        bars: List of dicts with keys: date (YYYY-MM-DD), open, high, low, close, volume
    
    Returns:
        Number of bars inserted/updated
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        count = 0
        for bar in bars:
            bar_date = bar.get("date", "")
            if not bar_date:
                continue
            
            # Extract values with defaults
            open_val = bar.get("open", 0.0)
            high_val = bar.get("high", 0.0)
            low_val = bar.get("low", 0.0)
            close_val = bar.get("close", 0.0)
            volume_val = bar.get("volume", 0)
            
            # INSERT OR REPLACE (idempotent)
            cursor.execute("""
                INSERT OR REPLACE INTO market_bars 
                (symbol, mode, timeframe, bar_date, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol.upper(),
                mode.upper(),
                timeframe,
                bar_date,
                open_val,
                high_val,
                low_val,
                close_val,
                volume_val
            ))
            count += 1
        
        conn.commit()
        conn.close()
        
        logger.info(f"💾 Upserted {count} market bars: {symbol.upper()}, {mode.upper()}, {timeframe}")
        return count
        
    except Exception as e:
        logger.error(f"❌ Failed to upsert market bars: {e}", exc_info=True)
        return 0


def get_cached_range(symbol: str, mode: str, timeframe: str) -> Tuple[Optional[str], Optional[str], int]:
    """
    Get the date range and count of cached market bars.
    
    Args:
        symbol: Stock/crypto symbol
        mode: "STOCK" or "CRYPTO"
        timeframe: Timeframe string (e.g., "1d")
    
    Returns:
        Tuple of (min_date, max_date, count) where dates are YYYY-MM-DD strings
        Returns (None, None, 0) if no data exists
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT MIN(bar_date), MAX(bar_date), COUNT(*)
            FROM market_bars
            WHERE symbol = ? AND mode = ? AND timeframe = ?
        """, (symbol.upper(), mode.upper(), timeframe))
        
        row = cursor.fetchone()
        conn.close()
        
        if row and row[2] and row[2] > 0:
            return (row[0], row[1], row[2])
        return (None, None, 0)
        
    except Exception as e:
        logger.error(f"❌ Failed to get cached range: {e}", exc_info=True)
        return (None, None, 0)


def is_trading_day(d: date) -> bool:
    """
    Check if a date is a trading day (Monday-Friday).
    
    Args:
        d: Date to check
    
    Returns:
        True if Monday-Friday, False for weekends
    """
    # Monday = 0, Sunday = 6
    return d.weekday() < 5


def get_missing_dates(symbol: str, mode: str, timeframe: str, start_date: date, end_date: date) -> List[date]:
    """
    Get list of missing trading days in the date range.
    Trading days only (excludes weekends).
    
    Args:
        symbol: Stock/crypto symbol
        mode: "STOCK" or "CRYPTO"
        timeframe: Timeframe string (e.g., "1d")
        start_date: Start date (inclusive)
        end_date: End date (inclusive)
    
    Returns:
        List of missing trading day dates (YYYY-MM-DD format as date objects)
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        # Get all cached dates in range
        cursor.execute("""
            SELECT bar_date
            FROM market_bars
            WHERE symbol = ? AND mode = ? AND timeframe = ?
                AND bar_date >= ? AND bar_date <= ?
            ORDER BY bar_date
        """, (symbol.upper(), mode.upper(), timeframe, start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d")))
        
        rows = cursor.fetchall()
        conn.close()
        
        # Convert to set of date objects for fast lookup
        cached_dates = set()
        for row in rows:
            try:
                cached_dates.add(date.fromisoformat(row[0]))
            except (ValueError, TypeError):
                continue
        
        # Generate all trading days in range
        missing_dates = []
        current = start_date
        while current <= end_date:
            if is_trading_day(current):
                if current not in cached_dates:
                    missing_dates.append(current)
            current += timedelta(days=1)
        
        return missing_dates
        
    except Exception as e:
        logger.error(f"❌ Failed to get missing dates: {e}", exc_info=True)
        return []
