"""
Paper Trading Simulation Engine
--------------------------------
Simulates stock buy/sell orders without real money.
Uses yfinance for real-time prices.
Stores positions and trades in SQLite.
"""

import sqlite3
import yfinance as yf
import logging
from datetime import datetime
from typing import Optional
from .database import get_db_path

logger = logging.getLogger(__name__)

# ============================================================================
# DB SETUP
# ============================================================================

def init_paper_trading_tables():
    """Create paper trading tables if not exist."""
    db_path = get_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS pt_portfolio (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cash REAL NOT NULL DEFAULT 100000.0,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pt_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL UNIQUE,
                shares REAL NOT NULL DEFAULT 0,
                avg_cost REAL NOT NULL DEFAULT 0,
                opened_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS pt_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                action TEXT NOT NULL,
                shares REAL NOT NULL,
                price REAL NOT NULL,
                total REAL NOT NULL,
                pnl REAL DEFAULT 0,
                executed_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_pt_trades_executed_at
                ON pt_trades(executed_at DESC);

            CREATE INDEX IF NOT EXISTS idx_pt_trades_symbol_executed
                ON pt_trades(symbol, executed_at DESC);
        """)
        # Init portfolio with $100k if empty
        row = conn.execute("SELECT COUNT(*) FROM pt_portfolio").fetchone()
        if row[0] == 0:
            conn.execute(
                "INSERT INTO pt_portfolio (cash, updated_at) VALUES (?, ?)",
                (100000.0, datetime.utcnow().isoformat())
            )
            conn.commit()
    logger.info("Paper trading tables ready.")


# ============================================================================
# PRICE FETCH
# ============================================================================

def get_current_price(symbol: str) -> Optional[float]:
    """Fetch latest price from yfinance."""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        price = info.last_price
        if price and price > 0:
            return round(float(price), 4)
        # fallback: history
        hist = ticker.history(period="1d")
        if not hist.empty:
            return round(float(hist["Close"].iloc[-1]), 4)
        return None
    except Exception as e:
        logger.error(f"Price fetch failed for {symbol}: {e}")
        return None


# ============================================================================
# PORTFOLIO
# ============================================================================

def get_portfolio() -> dict:
    """Return cash balance + all open positions with current value."""
    db_path = get_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row

        portfolio = conn.execute(
            "SELECT * FROM pt_portfolio ORDER BY id DESC LIMIT 1"
        ).fetchone()
        cash = portfolio["cash"] if portfolio else 100000.0

        positions = conn.execute(
            "SELECT * FROM pt_positions WHERE shares > 0"
        ).fetchall()

    position_list = []
    total_market_value = 0.0

    for pos in positions:
        symbol = pos["symbol"]
        shares = pos["shares"]
        avg_cost = pos["avg_cost"]
        current_price = get_current_price(symbol)

        if current_price:
            market_value = shares * current_price
            cost_basis = shares * avg_cost
            pnl = market_value - cost_basis
            pnl_pct = (pnl / cost_basis * 100) if cost_basis > 0 else 0
        else:
            market_value = shares * avg_cost
            pnl = 0.0
            pnl_pct = 0.0
            current_price = avg_cost

        total_market_value += market_value
        position_list.append({
            "symbol": symbol,
            "shares": shares,
            "avg_cost": avg_cost,
            "current_price": current_price,
            "market_value": round(market_value, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": round(pnl_pct, 2),
        })

    total_equity = cash + total_market_value
    return {
        "cash": round(cash, 2),
        "positions_value": round(total_market_value, 2),
        "total_equity": round(total_equity, 2),
        "positions": position_list,
        "as_of": datetime.utcnow().isoformat(),
    }


# ============================================================================
# ORDERS
# ============================================================================

def buy(symbol: str, shares: float) -> dict:
    """
    Simulate a market buy order.
    Returns: {success, symbol, shares, price, total, cash_remaining, error}
    """
    symbol = symbol.upper()
    price = get_current_price(symbol)
    if not price:
        return {"success": False, "error": f"Cannot fetch price for {symbol}"}

    total = round(shares * price, 2)
    db_path = get_db_path()
    now = datetime.utcnow().isoformat()

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        portfolio = conn.execute(
            "SELECT * FROM pt_portfolio ORDER BY id DESC LIMIT 1"
        ).fetchone()
        cash = portfolio["cash"]

        if cash < total:
            return {
                "success": False,
                "error": f"Insufficient cash. Need ${total:.2f}, have ${cash:.2f}"
            }

        # Update cash
        new_cash = round(cash - total, 2)
        conn.execute(
            "UPDATE pt_portfolio SET cash = ?, updated_at = ? WHERE id = ?",
            (new_cash, now, portfolio["id"])
        )

        # Upsert position
        existing = conn.execute(
            "SELECT * FROM pt_positions WHERE symbol = ?", (symbol,)
        ).fetchone()

        if existing:
            new_shares = existing["shares"] + shares
            new_avg = round(
                (existing["shares"] * existing["avg_cost"] + shares * price) / new_shares, 4
            )
            conn.execute(
                "UPDATE pt_positions SET shares=?, avg_cost=?, updated_at=? WHERE symbol=?",
                (new_shares, new_avg, now, symbol)
            )
        else:
            conn.execute(
                "INSERT INTO pt_positions (symbol, shares, avg_cost, opened_at, updated_at) VALUES (?,?,?,?,?)",
                (symbol, shares, price, now, now)
            )

        # Log trade
        conn.execute(
            "INSERT INTO pt_trades (symbol, action, shares, price, total, pnl, executed_at) VALUES (?,?,?,?,?,?,?)",
            (symbol, "BUY", shares, price, total, 0.0, now)
        )
        conn.commit()

    logger.info(f"BUY {shares} {symbol} @ ${price} = ${total}")
    return {
        "success": True,
        "action": "BUY",
        "symbol": symbol,
        "shares": shares,
        "price": price,
        "total": total,
        "cash_remaining": new_cash,
    }


def sell(symbol: str, shares: float) -> dict:
    """
    Simulate a market sell order.
    Returns: {success, symbol, shares, price, total, pnl, cash_remaining, error}
    """
    symbol = symbol.upper()
    price = get_current_price(symbol)
    if not price:
        return {"success": False, "error": f"Cannot fetch price for {symbol}"}

    db_path = get_db_path()
    now = datetime.utcnow().isoformat()

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        pos = conn.execute(
            "SELECT * FROM pt_positions WHERE symbol = ?", (symbol,)
        ).fetchone()

        if not pos or pos["shares"] < shares:
            held = pos["shares"] if pos else 0
            return {
                "success": False,
                "error": f"Not enough shares. Trying to sell {shares}, holding {held}"
            }

        total = round(shares * price, 2)
        pnl = round(shares * (price - pos["avg_cost"]), 2)

        portfolio = conn.execute(
            "SELECT * FROM pt_portfolio ORDER BY id DESC LIMIT 1"
        ).fetchone()
        new_cash = round(portfolio["cash"] + total, 2)
        new_shares = pos["shares"] - shares

        conn.execute(
            "UPDATE pt_portfolio SET cash = ?, updated_at = ? WHERE id = ?",
            (new_cash, now, portfolio["id"])
        )
        conn.execute(
            "UPDATE pt_positions SET shares=?, updated_at=? WHERE symbol=?",
            (new_shares, now, symbol)
        )
        conn.execute(
            "INSERT INTO pt_trades (symbol, action, shares, price, total, pnl, executed_at) VALUES (?,?,?,?,?,?,?)",
            (symbol, "SELL", shares, price, total, pnl, now)
        )
        conn.commit()

    logger.info(f"SELL {shares} {symbol} @ ${price} = ${total} | PnL: ${pnl}")
    return {
        "success": True,
        "action": "SELL",
        "symbol": symbol,
        "shares": shares,
        "price": price,
        "total": total,
        "pnl": pnl,
        "cash_remaining": new_cash,
    }


def get_trade_history(limit: int = 50) -> list:
    """Return last N trades."""
    db_path = get_db_path()
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM pt_trades ORDER BY executed_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def reset_portfolio(starting_cash: float = 100000.0) -> dict:
    """Reset paper portfolio to fresh state."""
    db_path = get_db_path()
    now = datetime.utcnow().isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM pt_positions")
        conn.execute("DELETE FROM pt_trades")
        conn.execute("UPDATE pt_portfolio SET cash = ?, updated_at = ?", (starting_cash, now))
        conn.commit()
    return {"success": True, "cash": starting_cash, "message": "Portfolio reset."}
