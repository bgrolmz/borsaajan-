"""
Mentor News Pipeline - Intelligent news processing with personalization.

Pipeline stages:
1. Symbol selection (portfolio + trades + analyzed, with TTL cache)
2. News fetching with normalization
3. Deduplication (symbol + headline hash + date)
4. Local scoring first (fast)
5. LLM enrichment ONLY above threshold
6. Output: what_happened + why_it_matters + mentor_action + risk
7. Notifications with deduplication and fatigue prevention
8. Store to DB for learning (news_analysis_history)
"""

import hashlib
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple, Any
from functools import lru_cache
import os

_COMPANY_SYMBOL_MAP = {
    "nvidia": "NVDA", "nvda": "NVDA",
    "apple": "AAPL", "aapl": "AAPL",
    "microsoft": "MSFT", "msft": "MSFT",
    "tesla": "TSLA", "tsla": "TSLA",
    "alphabet": "GOOGL", "google": "GOOGL", "googl": "GOOGL", "goog": "GOOGL",
    "amazon": "AMZN", "amzn": "AMZN",
    "meta": "META", "facebook": "META",
    "palantir": "PLTR", "pltr": "PLTR",
    "amd": "AMD", "advanced micro devices": "AMD",
    "intel": "INTC", "intc": "INTC",
    "qualcomm": "QCOM", "qcom": "QCOM",
    "broadcom": "AVGO", "avgo": "AVGO",
    "arm": "ARM",
    "netflix": "NFLX", "nflx": "NFLX",
    "spotify": "SPOT", "spot": "SPOT",
    "uber": "UBER",
    "airbnb": "ABNB",
    "coinbase": "COIN",
    "robinhood": "HOOD",
    "paypal": "PYPL", "pypl": "PYPL",
    "visa": "V",
    "mastercard": "MA",
    "jpmorgan": "JPM", "jp morgan": "JPM",
    "goldman sachs": "GS", "goldman": "GS",
    "berkshire": "BRK-B",
    "exxon": "XOM", "exxonmobil": "XOM",
    "chevron": "CVX",
    "johnson & johnson": "JNJ", "johnson and johnson": "JNJ",
    "pfizer": "PFE",
    "moderna": "MRNA",
    "walmart": "WMT",
    "target": "TGT",
    "boeing": "BA",
    "lockheed": "LMT",
    "bitcoin": "BTC-USD", "btc": "BTC-USD",
    "ethereum": "ETH-USD", "eth": "ETH-USD",
    "solana": "SOL-USD", "sol": "SOL-USD",
    "ripple": "XRP-USD", "xrp": "XRP-USD",
    "dogecoin": "DOGE-USD", "doge": "DOGE-USD",
    "openai": "MSFT",
    "anthropic": "AMZN",
    "arm holdings": "ARM",
    "super micro": "SMCI", "supermicro": "SMCI",
    "crowdstrike": "CRWD",
    "snowflake": "SNOW",
    "datadog": "DDOG",
    "servicenow": "NOW",
    "salesforce": "CRM",
    "oracle": "ORCL",
    "ibm": "IBM",
    "dell": "DELL",
    "hp": "HPQ", "hewlett": "HPQ",
}


def detect_symbol_from_text(text: str) -> Optional[str]:
    text_lower = text.lower()
    for keyword, sym in _COMPANY_SYMBOL_MAP.items():
        if keyword in text_lower:
            return sym
    import re
    ticker_match = re.search(r'\b([A-Z]{1,5})\b', text)
    if ticker_match:
        candidate = ticker_match.group(1)
        if candidate not in ("THE", "AND", "FOR", "WITH", "FROM", "THIS", "THAT", "WILL", "HAVE", "BEEN", "THEY", "THEIR"):
            return candidate
    return None

from .database import (
    get_connection, get_relevant_symbols_for_news, get_watched_symbols_only,
    should_send_notification, log_notification, generate_event_key
)
from .news_analyzer import analyze_news_item as local_analyze_news
from .notification_service import send_and_save_notification
import json


# TTL cache for symbol set (refresh every 30 minutes)
_SYMBOL_SET_CACHE: Optional[Tuple[Set[str], float]] = None
_SYMBOL_SET_TTL_SECONDS = 30 * 60  # 30 minutes


def get_relevant_symbols_cached() -> Set[str]:
    """
    Get relevant symbols with TTL cache.
    
    Returns:
        Set of normalized symbol strings (uppercase)
    """
    global _SYMBOL_SET_CACHE
    
    now = time.time()
    
    # Check cache
    if _SYMBOL_SET_CACHE is not None:
        symbols, cached_at = _SYMBOL_SET_CACHE
        if now - cached_at < _SYMBOL_SET_TTL_SECONDS:
            return symbols
    
    # Cache miss or expired - fetch fresh
    symbols = get_relevant_symbols_for_news()
    
    # Update cache
    _SYMBOL_SET_CACHE = (symbols, now)
    
    return symbols


def compute_news_hash(symbol: str, title: str, published_date: str) -> str:
    """
    Compute deduplication hash for news item.
    
    Args:
        symbol: Stock/crypto symbol
        title: News title (normalized)
        published_date: Publication date (YYYY-MM-DD format preferred)
    
    Returns:
        SHA256 hash (hex, first 16 chars)
    """
    # Normalize inputs
    symbol_norm = symbol.upper().strip()
    title_norm = " ".join(title.lower().strip().split())
    date_norm = published_date.strip()[:10]  # Take first 10 chars (YYYY-MM-DD)
    
    # Compute hash
    hash_input = f"{symbol_norm}|{title_norm}|{date_norm}"
    return hashlib.sha256(hash_input.encode('utf-8')).hexdigest()[:16]


def normalize_news_item(entry) -> Optional[Dict[str, Any]]:
    """
    Normalize a feedparser entry to standard format.
    
    Args:
        entry: feedparser entry object
    
    Returns:
        Normalized dict or None if invalid
    """
    if not entry or not hasattr(entry, 'title'):
        return None
    
    title = entry.title.strip() if entry.title else ""
    if not title:
        return None
    
    snippet = ""
    if hasattr(entry, 'summary') and entry.summary:
        snippet = entry.summary.strip()[:500]
    elif hasattr(entry, 'description') and entry.description:
        snippet = entry.description.strip()[:500]
    
    source = None
    if hasattr(entry, 'source') and entry.source:
        source = getattr(entry.source, 'title', None) or str(entry.source)
    
    # Parse published date
    published_date = ""
    timestamp = "Recent"
    if hasattr(entry, 'published_parsed') and entry.published_parsed:
        try:
            dt = datetime(*entry.published_parsed[:6])
            published_date = dt.strftime("%Y-%m-%d")
            timestamp = dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            pass
    elif hasattr(entry, 'published'):
        try:
            # Try to parse common formats
            dt = datetime.strptime(entry.published[:10], "%Y-%m-%d")
            published_date = dt.strftime("%Y-%m-%d")
            timestamp = entry.published
        except Exception:
            published_date = datetime.now().strftime("%Y-%m-%d")
            timestamp = entry.published
    
    return {
        "title": title,
        "snippet": snippet,
        "source": source,
        "published_date": published_date,
        "timestamp": timestamp,
    }


def fetch_and_dedupe_news(symbols: Set[str]) -> List[Dict[str, Any]]:
    """
    Fetch news for symbols and deduplicate.
    
    Deduplication key: symbol + headline hash + date
    
    Args:
        symbols: Set of symbols to fetch news for
    
    Returns:
        List of deduplicated news items with hash
    """
    import feedparser
    from .logic import normalize_symbol
    
    all_news_items = []
    seen_hashes = set()  # Deduplication by hash
    
    for symbol in symbols:
        try:
            normalized_symbol = normalize_symbol(symbol)
            feed_url = f'https://finance.yahoo.com/rss/headline?s={normalized_symbol}'
            feed = feedparser.parse(feed_url)
            
            if not feed.entries:
                continue
            
            # Process top 5 news articles per symbol
            for entry in feed.entries[:5]:
                normalized = normalize_news_item(entry)
                if not normalized:
                    continue
                
                # Compute deduplication hash
                news_hash = compute_news_hash(
                    symbol=normalized_symbol,
                    title=normalized["title"],
                    published_date=normalized["published_date"]
                )
                
                # Skip if we've seen this hash before
                if news_hash in seen_hashes:
                    continue
                seen_hashes.add(news_hash)
                
                # Add symbol and hash to normalized item
                normalized["symbol"] = normalized_symbol
                normalized["news_hash"] = news_hash
                
                all_news_items.append(normalized)
            
            # Small delay to avoid rate limiting
            time.sleep(0.5)
            
        except Exception as e:
            print(f"[news_pipeline] Error fetching news for {symbol}: {e}")
            continue
    
    return all_news_items


def score_news_local(news_item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fast local scoring of news item (no LLM).
    
    Args:
        news_item: News item dict with title, snippet, source, symbol
    
    Returns:
        Analysis dict with: importance_score, impact, time_horizon, reasons
    """
    title = news_item.get("title", "")
    source = news_item.get("source")
    
    # Use existing local analyzer
    analysis = local_analyze_news(title, source)
    
    return analysis


def enrich_news_with_llm(
    news_item: Dict[str, Any],
    local_analysis: Dict[str, Any],
    symbol_context: str = ""
) -> Dict[str, Any]:
    try:
        symbol = news_item.get("symbol", "UNKNOWN")
        title = news_item.get("title", "")
        snippet = news_item.get("snippet", "")
        source = news_item.get("source", "Unknown")
        local_score = local_analysis.get("importance_score", 0)

        from .logic import safe_gemini_call, get_technical_data_for_news

        tech = get_technical_data_for_news(symbol)
        price = tech.get("price", "N/A")
        rsi = tech.get("rsi", "N/A")
        bb_upper = tech.get("bb_upper", "N/A")
        bb_lower = tech.get("bb_lower", "N/A")

        prompt = f"""Sen üst düzey bir kantitatif analistsin. Aşağıdaki haberi ve teknik verileri harmanlayarak yalnızca geçerli bir JSON nesnesi döndür.

KURAL: Yalnızca JSON döndür. Açıklama, markdown veya ek metin kesinlikle yasak.

HABER:
Sembol: {symbol}
Başlık: {title}
Detay: {snippet[:300]}
Kaynak: {source}
{symbol_context}

TEKNİK VERİLER (Anlık):
Fiyat: {price}
RSI (14 gün): {rsi}
Bollinger Üst Band (Direnç): {bb_upper}
Bollinger Alt Band (Destek): {bb_lower}

ÇIKTI ŞEMASI (tüm alanlar zorunludur):
{{
  "symbol": "{symbol}",
  "impact": "Bullish veya Bearish veya Neutral",
  "reason": "Haberin ve teknik verilerin (RSI={rsi}, Direnç={bb_upper}, Destek={bb_lower}) birleşimiyle oluşturulmuş, rakamlar içeren detaylı analist yorumu. 2-3 cümle.",
  "risk_level": "High veya Medium veya Low",
  "risk_detail": "RSI ve Bollinger bantlarına dayalı risk analizi. 1-2 cümle.",
  "action_plan": "Stratejik hamle. Örn: Alt band {bb_lower} seviyesini test ederse alım değerlendirilebilir. 1-2 cümle.",
  "mentor_scenario": "Yükselişte X planı, düşüşte Y planı. 1-2 cümle.",
  "technical_rsi": "{rsi}",
  "technical_resistance": "{bb_upper}",
  "market_impact": "POSITIVE veya NEGATIVE veya NEUTRAL",
  "importance_score": 75,
  "impact_reason": "Haberin bu sembolü etkileme nedeni. 2 cümle.",
  "strategic_advice": "Somut strateji adımı. Bu içerik yatırım tavsiyesi değildir.",
  "comment": "Sektör trendleri ve makroekonomik bağlamla 2-3 cümlelik yorum.",
  "what_happened": "Ne oldu? Tek cümle.",
  "why_it_matters": "Neden önemli? Tek cümle.",
  "mentor_action": "Yatırımcı ne yapmalı? Tek cümle.",
  "risk": "En önemli risk. Tek cümle.",
  "title_tr": "Haber başlığının Türkçe çevirisi (max 120 karakter)."
}}"""

        print(f"🤖 [NEWS LLM] Enriching: {symbol} — price={price} rsi={rsi} — '{title[:50]}'")

        llm_result = safe_gemini_call(
            prompt,
            response_mode="json",
            max_retries=0,
            purpose="news_llm_enrich",
            max_output_tokens=1000,
            symbol=symbol,
            temperature=0.1,
        )

        if not llm_result:
            print(f"⚠️ [NEWS LLM] LLM returned None for {symbol}")
            return {}

        def _coerce_int(val, fallback: int) -> int:
            try:
                result = int(float(str(val)))
                return result if 0 <= result <= 100 else fallback
            except (ValueError, TypeError):
                return fallback

        def _first_str(d: dict, *keys) -> str:
            for k in keys:
                v = d.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
            return ""

        raw_score = None
        for k in ("importance_score", "score", "confidence"):
            if k in llm_result:
                raw_score = llm_result[k]
                break
        importance_score_final = _coerce_int(raw_score, local_score) if raw_score is not None else local_score

        raw_impact = _first_str(llm_result, "market_impact", "impact", "piyasa_etkisi").upper()
        if raw_impact not in ("POSITIVE", "NEGATIVE", "NEUTRAL"):
            raw_impact = "NEUTRAL"

        impact_reason_final = _first_str(llm_result, "impact_reason", "reason")
        if not impact_reason_final:
            impact_reason_final = _first_str(llm_result, "why_it_matters", "what_happened")
        if not impact_reason_final:
            impact_reason_final = f"{symbol} haberinin piyasa etkisi: {raw_impact}"

        llm_result["market_impact"] = raw_impact
        llm_result["impact_reason"] = impact_reason_final
        llm_result["importance_score"] = importance_score_final
        llm_result["technical_rsi"] = str(rsi)
        llm_result["technical_resistance"] = str(bb_upper)

        strategic_advice = _first_str(llm_result, "strategic_advice", "action_plan")
        if not strategic_advice:
            strategic_advice = f"{symbol} için piyasa gelişmelerini takip edin. Bu içerik yatırım tavsiyesi değildir."
        llm_result["strategic_advice"] = strategic_advice

        comment = _first_str(llm_result, "comment", "mentor_scenario")
        if not comment:
            comment = _first_str(llm_result, "why_it_matters", "reason")
        llm_result["comment"] = comment

        for f in ("what_happened", "why_it_matters", "mentor_action", "risk"):
            if not isinstance(llm_result.get(f), str) or not llm_result[f].strip():
                llm_result[f] = ""

        print(f"✅ [NEWS LLM] {symbol} impact={raw_impact} score={importance_score_final} rsi={rsi}")
        return llm_result

    except Exception as e:
        print(f"❌ [NEWS LLM] Error: {e}")
        import traceback
        traceback.print_exc()
        return {}


def save_news_analysis_to_db(news_item: Dict[str, Any], analysis: Dict[str, Any]) -> Optional[int]:
    """
    Save news analysis to database for learning.
    
    Args:
        news_item: News item dict
        analysis: Complete analysis dict
    
    Returns:
        Database ID or None if save failed
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        symbol = news_item.get("symbol", "UNKNOWN")
        news_hash = news_item.get("news_hash", "")
        title = news_item.get("title", "")
        source = news_item.get("source")
        published_date = news_item.get("published_date", "")
        
        local_score = analysis.get("importance_score", 0)
        llm_enriched = 1 if analysis.get("llm_enriched", False) else 0
        
        mentor_summary = analysis.get("mentor_summary", "")
        what_happened = analysis.get("what_happened", "")
        why_it_matters = analysis.get("why_it_matters", "")
        mentor_action = analysis.get("mentor_action", "")
        risk_note = analysis.get("risk", "")
        
        expected_impact = analysis.get("expected_impact", "NEUTRAL")
        action_hint = analysis.get("action_hint", "HOLD")
        confidence = analysis.get("confidence", 0)
        time_horizon = analysis.get("time_horizon", "short")
        
        advice = analysis.get("strategic_advice", "")
        comment = analysis.get("comment", "")
        title_tr = analysis.get("title_tr", "") or ""
        full_analysis_json = json.dumps(analysis, ensure_ascii=False)

        cursor.execute("""
            INSERT OR REPLACE INTO news_analysis_history (
                symbol, news_hash, title, title_tr, source, published_date,
                local_score, llm_enriched, mentor_summary,
                what_happened, why_it_matters, mentor_action, risk_note,
                expected_impact, action_hint, confidence, time_horizon,
                full_analysis_json, advice, comment
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            symbol, news_hash, title, title_tr, source, published_date,
            local_score, llm_enriched, mentor_summary,
            what_happened, why_it_matters, mentor_action, risk_note,
            expected_impact, action_hint, confidence, time_horizon,
            full_analysis_json, advice, comment
        ))
        
        analysis_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return analysis_id
        
    except Exception as e:
        print(f"❌ [NEWS DB] Error saving news analysis: {e}")
        import traceback
        traceback.print_exc()
        return None


def process_news_pipeline(
    mode: str = "QUICK",
    confidence_threshold: int = 50,
    llm_threshold: int = 60,
    use_watchlist: bool = True  # Hermes: Use watchlist mechanism
) -> List[Dict[str, Any]]:
    """
    Complete news pipeline: fetch → normalize → dedupe → score → enrich → notify → store.
    
    HERMES MODE: If use_watchlist=True, only processes watched symbols (resource-efficient).
    
    Args:
        mode: "QUICK" (local only) or "DEEP" (LLM enrichment above threshold)
        confidence_threshold: Minimum confidence for inclusion (0-100)
        llm_threshold: Minimum local score to trigger LLM enrichment (0-100)
        use_watchlist: If True, only process watched symbols (Hermes mode)
    
    Returns:
        List of MentorNewsCard dicts
    """
    import json
    
    try:
        print(f"[HERMES] Starting pipeline: mode={mode}, confidence_threshold={confidence_threshold}, llm_threshold={llm_threshold}, use_watchlist={use_watchlist}")
        
        # Step 1: Get symbols (Hermes: use watchlist if enabled)
        if use_watchlist:
            symbols = get_watched_symbols_only()
            print(f"[HERMES] Using watchlist: {len(symbols)} watched symbols")
        else:
            symbols = get_relevant_symbols_cached()
            print(f"[HERMES] Using full symbol set: {len(symbols)} symbols")
        
        if not symbols:
            print("[HERMES] No symbols found (watchlist may be empty)")
            return []
        
        print(f"[HERMES] Processing {len(symbols)} symbols")
        
        # Step 2: Fetch and deduplicate news
        news_items = fetch_and_dedupe_news(symbols)
        if not news_items:
            print("[news_pipeline] No news items found after deduplication")
            return []
        
        print(f"[news_pipeline] Fetched {len(news_items)} deduplicated news items")
        
        # Step 3: Local scoring first (fast)
        scored_items = []
        for item in news_items:
            local_analysis = score_news_local(item)
            local_score = local_analysis.get("importance_score", 0)
            
            # Only process if score >= confidence_threshold
            if local_score < confidence_threshold:
                continue
            
            item["local_analysis"] = local_analysis
            scored_items.append(item)
        
        print(f"[news_pipeline] {len(scored_items)} items passed local scoring threshold")
        
        # Step 4: LLM enrichment ONLY above threshold (if mode is DEEP)
        mentor_cards = []
        for item in scored_items:
            local_analysis = item["local_analysis"]
            local_score = local_analysis.get("importance_score", 0)
            
            # Build symbol context
            symbol = item.get("symbol", "UNKNOWN")
            symbol_context = f"Symbol: {symbol}"
            
            # LLM enrichment only if:
            # - Mode is DEEP OR use_watchlist is True (Hermes always uses LLM for impact analysis)
            # - Local score >= llm_threshold
            llm_enriched = False
            should_enrich = (mode.upper() == "DEEP" or use_watchlist) and local_score >= llm_threshold
            if should_enrich:
                llm_enrichment = enrich_news_with_llm(item, local_analysis, symbol_context)
                if llm_enrichment:
                    local_analysis.update(llm_enrichment)
                    llm_enriched = True
                    # Hermes: Extract market impact for notifications
                    market_impact = llm_enrichment.get("market_impact", "NEUTRAL")
                    impact_reason = llm_enrichment.get("impact_reason", "")
                    llm_importance_score = llm_enrichment.get("importance_score", local_score)
                    local_analysis["market_impact"] = market_impact
                    local_analysis["impact_reason"] = impact_reason
                    # Update importance_score with LLM's assessment (if provided and valid)
                    if isinstance(llm_importance_score, int) and 0 <= llm_importance_score <= 100:
                        local_analysis["importance_score"] = llm_importance_score
            
            # Map to MentorNewsCard format
            card = _build_mentor_card(item, local_analysis, llm_enriched)
            mentor_cards.append(card)
            
            # Step 5: Save to DB for learning
            analysis = {
                **local_analysis,
                "llm_enriched": llm_enriched,
                "mentor_summary": card.get("mentor_summary", ""),
                "what_happened": card.get("what_happened", ""),
                "why_it_matters": card.get("why_it_matters", ""),
                "mentor_action": card.get("mentor_action", ""),
                "risk": card.get("risk", ""),
                "expected_impact": card.get("expected_impact", "NEUTRAL"),
                "action_hint": card.get("action_hint", "HOLD"),
                "confidence": card.get("confidence", 0),
                "time_horizon": card.get("time_horizon", "short"),
            }
            save_news_analysis_to_db(item, analysis)
        
        # Step 6: Sort by confidence
        mentor_cards.sort(key=lambda x: x.get("confidence", 0), reverse=True)
        
        # Step 7: Notifications (with deduplication and fatigue prevention + Hermes Telegram integration)
        _process_notifications(mentor_cards, confidence_threshold, use_watchlist=use_watchlist)
        
        print(f"[HERMES] Returning {len(mentor_cards)} mentor cards")
        return mentor_cards
        
    except Exception as e:
        print(f"❌ [news_pipeline] Error in pipeline: {e}")
        import traceback
        traceback.print_exc()
        return []


def _build_mentor_card(
    news_item: Dict[str, Any],
    analysis: Dict[str, Any],
    llm_enriched: bool
) -> Dict[str, Any]:
    """
    Build MentorNewsCard from news item and analysis.
    
    Args:
        news_item: News item dict
        analysis: Analysis dict (local + optional LLM)
        llm_enriched: Whether LLM enrichment was applied
    
    Returns:
        MentorNewsCard dict
    """
    symbol = news_item.get("symbol", "UNKNOWN")
    title = news_item.get("title", "")
    source = news_item.get("source")
    timestamp = news_item.get("timestamp", "Recent")
    
    importance_score = analysis.get("importance_score", 0)
    impact = analysis.get("impact", "neutral")
    time_horizon = analysis.get("time_horizon", "short")
    reasons = analysis.get("reasons", [])
    
    # Map impact
    impact_map = {
        "bullish": "POSITIVE",
        "bearish": "NEGATIVE",
        "neutral": "NEUTRAL"
    }
    expected_impact = impact_map.get(impact, "NEUTRAL")
    
    # Build mentor_summary (prefer LLM fields, fallback to local)
    if llm_enriched:
        what_happened = analysis.get("what_happened", "")
        why_it_matters = analysis.get("why_it_matters", "")
        mentor_summary = f"{what_happened}. {why_it_matters}"[:300]
    else:
        mentor_summary = ". ".join(reasons[:3])[:300]
    
    if not mentor_summary:
        mentor_summary = "Haber analiz edildi, önemli sinyal tespit edilmedi."
    
    # Determine action_hint
    if importance_score >= 70:
        if expected_impact == "POSITIVE":
            action_hint = "CONSIDER_BUY"
        elif expected_impact == "NEGATIVE":
            action_hint = "SET_STOP_LOSS"
        else:
            action_hint = "MONITOR"
    elif importance_score >= 50:
        if expected_impact == "POSITIVE":
            action_hint = "HOLD_STRONG"
        elif expected_impact == "NEGATIVE":
            action_hint = "CONSIDER_SELL"
        else:
            action_hint = "HOLD"
    else:
        action_hint = "MONITOR"
    
    # Build card
    card = {
        "symbol": symbol,
        "mentor_summary": mentor_summary,
        "expected_impact": expected_impact,
        "action_hint": action_hint,
        "confidence": importance_score,
        "time_horizon": time_horizon,
        "timestamp": timestamp,
        "source": source,
    }
    
    # Add LLM-enriched fields if available (including Hermes impact analysis)
    if llm_enriched:
        card["what_happened"] = analysis.get("what_happened", "")
        card["why_it_matters"] = analysis.get("why_it_matters", "")
        card["mentor_action"] = analysis.get("mentor_action", "")
        card["risk"] = analysis.get("risk", "")
        card["market_impact"] = analysis.get("market_impact", "NEUTRAL")
        card["impact_reason"] = analysis.get("impact_reason", "")
        card["strategic_advice"] = analysis.get("strategic_advice", "")
        card["comment"] = analysis.get("comment", "")
        card["risk_detail"] = analysis.get("risk_detail", "")
    
    # Add title from news_item for notifications
    card["title"] = news_item.get("title", "")
    
    return card


def _process_notifications(
    mentor_cards: List[Dict[str, Any]],
    confidence_threshold: int,
    use_watchlist: bool = True
) -> None:
    """
    Process notifications for mentor cards with deduplication, fatigue prevention, and Hermes Telegram integration.
    
    Args:
        mentor_cards: List of MentorNewsCard dicts
        confidence_threshold: Minimum confidence for notification
        use_watchlist: If True, send Telegram notifications (Hermes mode)
    """
    NOTIF_COOLDOWN_MINUTES = int(os.getenv("NOTIF_COOLDOWN_MINUTES", "30"))
    NOTIF_MAX_PER_DAY_PER_SYMBOL = os.getenv("NOTIF_MAX_PER_DAY_PER_SYMBOL")
    max_per_day = int(NOTIF_MAX_PER_DAY_PER_SYMBOL) if NOTIF_MAX_PER_DAY_PER_SYMBOL else None
    
    for card in mentor_cards:
        symbol = card.get("symbol", "")
        confidence = card.get("confidence", 0)
        mentor_summary = card.get("mentor_summary", "")
        title = card.get("title", "") or mentor_summary[:100]
        
        # Hermes: Extract impact analysis (from LLM enrichment)
        market_impact = card.get("market_impact", "NEUTRAL")
        impact_reason = card.get("impact_reason", "")
        
        # Generate event_key
        event_key = generate_event_key(
            mentor_summary,
            card.get("source"),
            mentor_summary[:80]
        )
        
        # Check if should send notification
        should_send, reason = should_send_notification(
            symbol,
            event_key,
            confidence,
            cooldown_minutes=NOTIF_COOLDOWN_MINUTES,
            min_score=confidence_threshold,
            max_per_day_per_symbol=max_per_day
        )
        
        if should_send:
            log_notification(symbol, event_key, confidence, title=title)
            print(f"[HERMES] Notification logged: symbol={symbol} confidence={confidence}")

            # Hermes: Send Telegram notification if using watchlist
            if use_watchlist:
                try:
                    from .notification_service import send_telegram_message, save_notification_to_db

                    notification_type = "CRITICAL" if confidence >= 80 else "ALERT"

                    # --- Zengin Telegram mesajı oluştur ---
                    impact_emoji = {"POSITIVE": "🟢", "NEGATIVE": "🔴"}.get(market_impact, "🟡")
                    impact_tr = {"POSITIVE": "Pozitif 📈", "NEGATIVE": "Negatif 📉"}.get(market_impact, "Nötr ➡️")
                    urgency = "🚨 " if confidence >= 80 else "📊 "

                    # Başlık satırı
                    title_short = title[:100] if title else mentor_summary[:80]
                    lines = [
                        f"{urgency}*{symbol}* — {title_short}",
                        "",
                    ]

                    # Ne oldu
                    what = card.get("what_happened", "")
                    if what:
                        lines += [f"❓ *Ne oldu?*", what, ""]

                    # Neden önemli
                    why = card.get("why_it_matters", "")
                    if not why:
                        why = impact_reason or mentor_summary
                    if why:
                        lines += [f"🔍 *Neden önemli?*", why[:300], ""]

                    # Etki + Güven skoru
                    lines.append(f"{impact_emoji} *Etki:* {impact_tr} | 📊 *Güven:* {confidence}/100")
                    lines.append("")

                    # Yatırımcı stratejisi
                    strategy = card.get("strategic_advice", "") or card.get("mentor_action", "")
                    if strategy:
                        lines += [f"🎯 *Strateji:*", strategy[:300], ""]

                    # Risk
                    risk_txt = card.get("risk", "") or card.get("risk_detail", "")
                    if risk_txt:
                        lines += [f"⚠️ *Risk:*", risk_txt[:200], ""]

                    # Analist yorumu
                    comment_txt = card.get("comment", "")
                    if comment_txt:
                        lines += [f"💬 *Analist Yorumu:*", comment_txt[:300], ""]

                    lines.append("_Borsa Ajanı Mentor_")

                    rich_message = "\n".join(lines)

                    # Telegram'a gönder
                    telegram_sent = send_telegram_message(rich_message, parse_mode="Markdown")

                    # DB'ye kaydet
                    save_notification_to_db(
                        symbol=symbol,
                        title=title_short,
                        message=rich_message.replace("*", "").replace("_", ""),
                        notification_type=notification_type,
                        impact=market_impact,
                        reason=impact_reason or mentor_summary[:100],
                    )

                    if telegram_sent:
                        criticality_msg = "CRITICAL" if confidence >= 80 else "ALERT"
                        print(f"[HERMES] ✅ Telegram {criticality_msg} sent: {symbol} (Impact: {market_impact}, Score: {confidence})")
                    else:
                        print(f"[HERMES] ⚠️ Telegram notification failed: {symbol}")
                except Exception as telegram_err:
                    print(f"[HERMES] ❌ Error sending Telegram notification: {telegram_err}")
                    import traceback
                    traceback.print_exc()
        else:
            print(f"[HERMES] Notification suppressed: symbol={symbol} reason={reason}")
