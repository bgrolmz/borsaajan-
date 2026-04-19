"""
Finance Service: Extended hours (pre/post market) price data support.
Provides comprehensive price information including regular, pre-market, and post-market prices.
"""
import yfinance as yf
from datetime import datetime
import pytz
from typing import Dict, Optional

def get_extended_hours_price(symbol: str) -> Dict:
    """
    Get comprehensive price data including pre-market and post-market prices.
    
    Args:
        symbol: Stock symbol (e.g., 'AAPL', 'NVDA')
    
    Returns:
        Dictionary with:
        - current_price: Regular session close price
        - pre_market_price: Pre-market price if available
        - post_market_price: Post-market price if available
        - active_price_type: 'regular', 'pre_market', or 'post_market'
        - price_change_pct: Percentage change for pre/post market vs regular close
    """
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info
        
        # Get regular session close
        hist = ticker.history(period="1d")
        if hist.empty:
            return {
                "current_price": None,
                "pre_market_price": None,
                "post_market_price": None,
                "active_price_type": "regular",
                "price_change_pct": None
            }
        
        regular_close = float(hist['Close'].iloc[-1])
        
        # Get current time in market timezone
        market_tz = pytz.timezone('America/New_York')
        current_time_et = datetime.now(market_tz)
        hour_et = current_time_et.hour
        minute_et = current_time_et.minute
        
        pre_market_price = None
        post_market_price = None
        active_price_type = "regular"
        
        # Try to get pre-market price
        try:
            if 'preMarketPrice' in info and info['preMarketPrice']:
                pre_market_price = float(info['preMarketPrice'])
        except:
            pass
        
        # Try to get post-market price
        try:
            if 'postMarketPrice' in info and info['postMarketPrice']:
                post_market_price = float(info['postMarketPrice'])
        except:
            pass
        
        # Try extended hours history as fallback
        try:
            extended_hist = ticker.history(period="1d", interval="1m", prepost=True)
            if not extended_hist.empty:
                latest_extended = float(extended_hist['Close'].iloc[-1])
                
                # Before 9:30 AM ET = pre-market
                if hour_et < 9 or (hour_et == 9 and minute_et < 30):
                    if pre_market_price is None:
                        pre_market_price = latest_extended
                    active_price_type = "pre_market"
                # After 4:00 PM ET = post-market
                elif hour_et >= 16:
                    if post_market_price is None:
                        post_market_price = latest_extended
                    active_price_type = "post_market"
        except:
            pass
        
        # Calculate price change percentage
        price_change_pct = None
        active_price = regular_close
        
        if active_price_type == "pre_market" and pre_market_price:
            active_price = pre_market_price
            price_change_pct = ((pre_market_price - regular_close) / regular_close) * 100
        elif active_price_type == "post_market" and post_market_price:
            active_price = post_market_price
            price_change_pct = ((post_market_price - regular_close) / regular_close) * 100
        
        return {
            "current_price": round(regular_close, 2),
            "pre_market_price": round(pre_market_price, 2) if pre_market_price else None,
            "post_market_price": round(post_market_price, 2) if post_market_price else None,
            "active_price_type": active_price_type,
            "active_price": round(active_price, 2),
            "price_change_pct": round(price_change_pct, 2) if price_change_pct is not None else None
        }
    except Exception as e:
        print(f"⚠️ Error fetching extended hours price for {symbol}: {e}")
        return {
            "current_price": None,
            "pre_market_price": None,
            "post_market_price": None,
            "active_price_type": "regular",
            "active_price": None,
            "price_change_pct": None
        }

