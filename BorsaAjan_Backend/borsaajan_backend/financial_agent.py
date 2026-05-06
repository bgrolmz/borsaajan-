"""
Financial Analysis Agent
-------------------------
Analyzes US stocks using:
- yfinance: price + fundamentals
- EV (Expected Value) calculation
- Kelly Criterion (position sizing)
- Bayesian updating (news impact)
- Gemini AI (synthesis + narrative)

Main entry: analyze_ticker(symbol, portfolio_size)
"""

import os
import logging
import yfinance as yf
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ============================================================================
# PRICE & FUNDAMENTALS
# ============================================================================

def get_stock_data(symbol: str) -> dict:
    """Fetch price, fundamentals, recent news from yfinance."""
    try:
        ticker = yf.Ticker(symbol)
        info = ticker.info

        # Price
        price = info.get("currentPrice") or info.get("regularMarketPrice") or 0
        prev_close = info.get("previousClose") or price
        change_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0

        # Fundamentals
        pe_ratio = info.get("trailingPE") or info.get("forwardPE")
        eps = info.get("trailingEps")
        revenue_growth = info.get("revenueGrowth")
        gross_margins = info.get("grossMargins")
        debt_to_equity = info.get("debtToEquity")
        free_cashflow = info.get("freeCashflow")
        market_cap = info.get("marketCap")
        fifty_two_week_high = info.get("fiftyTwoWeekHigh")
        fifty_two_week_low = info.get("fiftyTwoWeekLow")
        analyst_target = info.get("targetMeanPrice")
        recommendation = info.get("recommendationKey", "none")
        sector = info.get("sector", "Unknown")
        short_name = info.get("shortName", symbol)

        # Recent news (last 5)
        news_items = []
        try:
            raw_news = ticker.news or []
            for n in raw_news[:5]:
                content = n.get("content", {})
                title = content.get("title", "") if isinstance(content, dict) else str(content)
                news_items.append(title)
        except Exception:
            pass

        return {
            "symbol": symbol.upper(),
            "name": short_name,
            "sector": sector,
            "price": round(float(price), 2) if price else None,
            "change_pct": round(change_pct, 2),
            "prev_close": round(float(prev_close), 2) if prev_close else None,
            "pe_ratio": round(pe_ratio, 2) if pe_ratio else None,
            "eps": round(eps, 2) if eps else None,
            "revenue_growth": round(revenue_growth * 100, 1) if revenue_growth else None,
            "gross_margins": round(gross_margins * 100, 1) if gross_margins else None,
            "debt_to_equity": round(debt_to_equity, 2) if debt_to_equity else None,
            "free_cashflow": free_cashflow,
            "market_cap": market_cap,
            "52w_high": fifty_two_week_high,
            "52w_low": fifty_two_week_low,
            "analyst_target": round(float(analyst_target), 2) if analyst_target else None,
            "analyst_recommendation": recommendation,
            "recent_news": news_items,
            "fetched_at": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error(f"Stock data fetch failed for {symbol}: {e}")
        return {"symbol": symbol.upper(), "error": str(e)}


# ============================================================================
# MATH: EV + KELLY + BAYES
# ============================================================================

def calculate_ev(win_probability: float, target_price: float, entry_price: float, stop_loss: float) -> dict:
    """
    Calculate Expected Value for a trade.

    EV = (P_win × profit) - (P_lose × loss)
    All prices in dollars.
    """
    if entry_price <= 0:
        return {"ev": 0, "roi": 0, "verdict": "SKIP", "error": "Invalid entry price"}

    p_win = max(0.0, min(1.0, win_probability))
    p_lose = 1.0 - p_win
    profit = target_price - entry_price
    loss = entry_price - stop_loss

    ev = (p_win * profit) - (p_lose * loss)
    roi = (ev / entry_price) * 100 if entry_price > 0 else 0

    return {
        "ev": round(ev, 4),
        "roi_pct": round(roi, 2),
        "verdict": "BUY" if ev > 0 else "SKIP",
        "p_win": p_win,
        "p_lose": p_lose,
        "profit_if_win": round(profit, 2),
        "loss_if_lose": round(loss, 2),
    }


def calculate_kelly(win_probability: float, target_price: float, entry_price: float, portfolio_size: float = 10000) -> dict:
    """
    Kelly Criterion — optimal position size.
    Quarter-Kelly applied for safety. Hard cap 5%.

    b = (target - entry) / entry  (net odds)
    f* = (b*p - q) / b
    """
    if entry_price <= 0 or target_price <= entry_price:
        return {"full_kelly_pct": 0, "quarter_kelly_pct": 0, "capped_pct": 0, "dollar_amount": 0, "shares": 0}

    p = max(0.01, min(0.99, win_probability))
    q = 1 - p
    profit = target_price - entry_price
    loss = entry_price - (entry_price * (1 - 0.07))  # default stop ~7%
    b = profit / loss if loss > 0 else 1.0  # win/loss ratio (net odds)

    full_kelly = (b * p - q) / b if b > 0 else 0
    full_kelly = max(0.0, full_kelly)
    quarter_kelly = full_kelly * 0.25
    capped = min(quarter_kelly, 0.05)  # Hard cap 5%

    dollar_amount = round(portfolio_size * capped, 2)
    shares = int(dollar_amount / entry_price) if entry_price > 0 else 0

    return {
        "full_kelly_pct": round(full_kelly * 100, 2),
        "quarter_kelly_pct": round(quarter_kelly * 100, 2),
        "capped_pct": round(capped * 100, 2),
        "dollar_amount": dollar_amount,
        "shares": shares,
    }


def bayesian_update(prior: float, p_evidence_if_true: float, p_evidence_if_false: float) -> dict:
    """
    Bayesian update: P(H|E) = P(E|H)*P(H) / P(E)

    prior: initial probability (0-1)
    p_evidence_if_true: P(this evidence | bull thesis)
    p_evidence_if_false: P(this evidence | bear thesis)
    """
    prior = max(0.01, min(0.99, prior))
    numerator = p_evidence_if_true * prior
    denominator = numerator + p_evidence_if_false * (1 - prior)
    posterior = numerator / denominator if denominator > 0 else prior
    lr = p_evidence_if_true / p_evidence_if_false if p_evidence_if_false > 0 else 1.0

    return {
        "prior": round(prior, 3),
        "posterior": round(posterior, 3),
        "change": round((posterior - prior) * 100, 1),
        "likelihood_ratio": round(lr, 2),
        "direction": "BULLISH" if posterior > prior else "BEARISH",
    }


def estimate_probability_from_fundamentals(data: dict) -> float:
    """
    Estimate win probability (bull thesis) from fundamentals.
    Heuristic scoring — not a guarantee.
    Score 0-100, convert to 0.3-0.75 probability range.
    """
    score = 50  # Neutral start

    # Analyst recommendation
    rec = (data.get("analyst_recommendation") or "").lower()
    if rec in ["strong_buy", "buy"]:
        score += 15
    elif rec in ["hold", "neutral"]:
        score += 0
    elif rec in ["sell", "underperform"]:
        score -= 15

    # Analyst target vs current price
    target = data.get("analyst_target")
    price = data.get("price")
    if target and price and price > 0:
        upside = (target - price) / price * 100
        if upside > 20:
            score += 10
        elif upside > 10:
            score += 5
        elif upside < -10:
            score -= 10

    # Revenue growth
    rev_growth = data.get("revenue_growth")
    if rev_growth is not None:
        if rev_growth > 20:
            score += 8
        elif rev_growth > 10:
            score += 4
        elif rev_growth < 0:
            score -= 8

    # P/E ratio (rough valuation check)
    pe = data.get("pe_ratio")
    if pe:
        if 10 < pe < 25:
            score += 5   # Reasonable valuation
        elif pe > 50:
            score -= 5   # Potentially overvalued
        elif pe < 0:
            score -= 10  # Negative earnings

    # Debt/equity
    de = data.get("debt_to_equity")
    if de is not None:
        if de < 50:
            score += 5
        elif de > 200:
            score -= 5

    # Price vs 52w range
    high = data.get("52w_high")
    low = data.get("52w_low")
    if high and low and price:
        position = (price - low) / (high - low) if high != low else 0.5
        if position < 0.3:
            score += 5   # Near bottom — potential upside
        elif position > 0.9:
            score -= 5   # Near top — limited upside

    # Clamp and normalize to probability
    score = max(10, min(90, score))
    probability = 0.30 + (score / 100) * 0.45  # Maps 10-90 → 0.35-0.705
    return round(probability, 3)


# ============================================================================
# GEMINI SYNTHESIS
# ============================================================================

def _gemini_analyze(symbol: str, data: dict, ev: dict, kelly: dict, bayes: dict) -> str:
    """Call Gemini to synthesize analysis into readable Turkish text."""
    try:
        try:
            from google import genai
        except ImportError:
            import google.generativeai as genai  # fallback
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            return _fallback_analysis(symbol, data, ev, kelly)

        client = genai.Client(api_key=api_key)

        prompt = f"""Sen deneyimli bir Amerikan borsası analistisin. Kısa, net ve Türkçe analiz yaz.

HİSSE: {symbol} ({data.get('name', '')}) - Sektör: {data.get('sector', 'Bilinmiyor')}
Fiyat: ${data.get('price', 'N/A')} | Günlük değişim: {data.get('change_pct', 0):+.1f}%
P/E: {data.get('pe_ratio', 'N/A')} | EPS: {data.get('eps', 'N/A')}
Gelir büyümesi: {data.get('revenue_growth', 'N/A')}% | Brüt marj: {data.get('gross_margins', 'N/A')}%
Analist hedef: ${data.get('analyst_target', 'N/A')} | Öneri: {data.get('analyst_recommendation', 'N/A')}
52 hafta: ${data.get('52w_low', 'N/A')} - ${data.get('52w_high', 'N/A')}

QUANT ANALİZ:
- EV: ${ev.get('ev', 0):.2f} ({ev.get('verdict', 'N/A')})
- Tahmini kazanma olasılığı: {ev.get('p_win', 0)*100:.0f}%
- Kelly pozisyon: %{kelly.get('capped_pct', 0):.1f} (${kelly.get('dollar_amount', 0):.0f})
- Bayesian güncelleme: {bayes.get('prior', 0)*100:.0f}% → {bayes.get('posterior', 0)*100:.0f}%

SON HABERLER:
{chr(10).join(f'- {n}' for n in data.get('recent_news', [])[:3]) or '- Haber yok'}

Şu formatta yaz (başka bir şey ekleme):
ÖZET: [2 cümle — ne durumda bu hisse]
GÜÇ: [en güçlü 2 nokta]
RİSK: [en önemli 2 risk]
KARAR: [AL / SAT / BEKLE — tek kelime] — [tek cümle gerekçe]"""

        models_to_try = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]
        for model in models_to_try:
            try:
                response = client.models.generate_content(model=model, contents=prompt)
                if response and response.text:
                    return response.text.strip()
            except Exception:
                continue

        return _fallback_analysis(symbol, data, ev, kelly)

    except Exception as e:
        logger.error(f"Gemini analysis failed: {e}")
        return _fallback_analysis(symbol, data, ev, kelly)


def _fallback_analysis(symbol: str, data: dict, ev: dict, kelly: dict) -> str:
    """Simple text output when Gemini unavailable."""
    verdict = ev.get("verdict", "SKIP")
    return (
        f"{symbol} analizi tamamlandı.\n"
        f"Fiyat: ${data.get('price', 'N/A')} | EV: ${ev.get('ev', 0):.2f}\n"
        f"Karar: {verdict} | Kelly: %{kelly.get('capped_pct', 0):.1f}\n"
        f"(AI yorumu şu an mevcut değil)"
    )


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def analyze_ticker(
    symbol: str,
    portfolio_size: float = 10000,
    target_upside_pct: float = 15.0,
    stop_loss_pct: float = 7.0,
    prior_probability: Optional[float] = None,
) -> dict:
    """
    Full analysis pipeline for a US stock ticker.

    Args:
        symbol: Ticker (e.g. 'AAPL')
        portfolio_size: Total portfolio in USD (for Kelly sizing)
        target_upside_pct: Expected upside % (default 15%)
        stop_loss_pct: Stop loss % below entry (default 7%)
        prior_probability: Override bull probability (0-1). Auto-estimated if None.

    Returns: Complete analysis dict with EV, Kelly, Bayes, AI commentary.
    """
    symbol = symbol.upper().strip()
    logger.info(f"Analyzing {symbol}...")

    # 1. Fetch data
    data = get_stock_data(symbol)
    if "error" in data or not data.get("price"):
        return {
            "symbol": symbol,
            "success": False,
            "error": data.get("error", "Price fetch failed"),
        }

    price = data["price"]

    # 2. Calculate targets
    target_price = round(price * (1 + target_upside_pct / 100), 2)
    stop_price = round(price * (1 - stop_loss_pct / 100), 2)

    # 3. Estimate probability
    p_win = prior_probability if prior_probability else estimate_probability_from_fundamentals(data)

    # 4. EV
    ev = calculate_ev(p_win, target_price, price, stop_price)

    # 5. Kelly
    kelly = calculate_kelly(p_win, target_price, price, portfolio_size)

    # 6. Bayesian update from recent news sentiment
    news = data.get("recent_news", [])
    bayes = {"prior": p_win, "posterior": p_win, "change": 0, "direction": "NEUTRAL"}
    if news:
        bullish_words = {"surge", "beat", "beats", "record", "growth", "upgrade", "strong", "buy", "positive", "profit", "rally"}
        bearish_words = {"miss", "drop", "fall", "downgrade", "sell", "risk", "loss", "warning", "fraud", "cut", "weak"}
        bull_count = sum(1 for n in news for w in n.lower().split() if w in bullish_words)
        bear_count = sum(1 for n in news for w in n.lower().split() if w in bearish_words)

        if bull_count > bear_count:
            bayes = bayesian_update(p_win, 0.65, 0.35)
        elif bear_count > bull_count:
            bayes = bayesian_update(p_win, 0.35, 0.65)

    # 7. Final verdict
    updated_p = bayes["posterior"]
    final_ev = calculate_ev(updated_p, target_price, price, stop_price)

    if final_ev["ev"] > 0 and updated_p >= 0.55:
        verdict = "AL"
        confidence = "YÜKSEK" if updated_p >= 0.65 else "ORTA"
    elif final_ev["ev"] < 0 or updated_p < 0.40:
        verdict = "SAT/KAÇIN"
        confidence = "YÜKSEK" if updated_p < 0.35 else "ORTA"
    else:
        verdict = "BEKLE"
        confidence = "DÜŞÜK"

    # 8. Gemini AI commentary
    ai_comment = _gemini_analyze(symbol, data, final_ev, kelly, bayes)

    # 9. Longshot check
    longshot_warning = updated_p < 0.15

    return {
        "success": True,
        "symbol": symbol,
        "name": data.get("name"),
        "sector": data.get("sector"),
        "price": price,
        "change_pct": data.get("change_pct"),
        "analyst_target": data.get("analyst_target"),
        "analyst_recommendation": data.get("analyst_recommendation"),

        "targets": {
            "entry": price,
            "target": target_price,
            "stop_loss": stop_price,
            "upside_pct": target_upside_pct,
            "stop_pct": stop_loss_pct,
        },

        "probability": {
            "initial": round(p_win, 3),
            "after_news": round(updated_p, 3),
            "bayes_change": bayes.get("change"),
            "news_direction": bayes.get("direction"),
        },

        "ev": {
            "value": final_ev["ev"],
            "roi_pct": final_ev["roi_pct"],
            "verdict": final_ev["verdict"],
        },

        "kelly": {
            "full_pct": kelly["full_kelly_pct"],
            "quarter_pct": kelly["quarter_kelly_pct"],
            "recommended_pct": kelly["capped_pct"],
            "dollar_amount": kelly["dollar_amount"],
            "shares": kelly["shares"],
        },

        "verdict": verdict,
        "confidence": confidence,
        "longshot_warning": longshot_warning,

        "fundamentals": {
            "pe_ratio": data.get("pe_ratio"),
            "eps": data.get("eps"),
            "revenue_growth": data.get("revenue_growth"),
            "gross_margins": data.get("gross_margins"),
            "debt_to_equity": data.get("debt_to_equity"),
            "52w_high": data.get("52w_high"),
            "52w_low": data.get("52w_low"),
        },

        "recent_news": data.get("recent_news", []),
        "ai_commentary": ai_comment,
        "analyzed_at": datetime.utcnow().isoformat(),
    }
