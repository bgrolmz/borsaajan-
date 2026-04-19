"""
Local news analyzer module - NO LLM calls.

Analyzes news items using heuristic rules to determine:
- Importance score (0-100)
- Impact (bullish/bearish/neutral)
- Time horizon (intraday/short/long)
- Reasons (max 3 short explanations)
"""

import re
from typing import Optional, List, Dict, Literal, Any


def analyze_news_item(text: str, source: Optional[str] = None) -> Dict[str, Any]:
    """
    Analyze a single news item using local heuristics (NO LLM).
    
    Args:
        text: News headline or text content
        source: Optional news source name (e.g., "Reuters", "Bloomberg")
    
    Returns:
        dict with keys:
        - importance_score: int (0-100)
        - impact: "bullish" | "bearish" | "neutral"
        - time_horizon: "intraday" | "short" | "long"
        - reasons: list[str] (max 3 short explanations)
    """
    if not text or not isinstance(text, str):
        return {
            "importance_score": 0,
            "impact": "neutral",
            "time_horizon": "short",
            "reasons": ["Geçersiz haber metni"]
        }
    
    text_lower = text.lower()
    base_score = 0
    impact_signals = {"bullish": 0, "bearish": 0, "neutral": 0}
    time_horizon_signals = {"intraday": 0, "short": 0, "long": 0}
    reasons_list = []
    
    # ============================================================================
    # 1. CRITICAL NEGATIVE KEYWORDS (High weight, bearish)
    # ============================================================================
    critical_negative = {
        "bankrupt": 40, "bankruptcy": 40,
        "lawsuit": 40, "sued": 35, "litigation": 35,
        "ban": 40, "banned": 40, "prohibition": 35,
        "fire": 30, "explosion": 35, "accident": 25,
        "fraud": 40, "scandal": 35, "corruption": 35,
        "default": 35, "delinquency": 30,
        "shutdown": 30, "closure": 25
    }
    
    for keyword, weight in critical_negative.items():
        if keyword in text_lower:
            base_score += weight
            impact_signals["bearish"] += weight
            time_horizon_signals["intraday"] += 10  # Critical news is immediate
            if len(reasons_list) < 3:
                reasons_list.append(f"Kritik negatif kelime: {keyword}")
            break  # Only count first match
    
    # ============================================================================
    # 2. EARNINGS & GUIDANCE KEYWORDS (Medium-high weight)
    # ============================================================================
    earnings_keywords = {
        "earnings": 25, "guidance": 25, "outlook": 20,
        "revenue": 25, "profit": 20, "eps": 20,
        "beat": 20, "miss": 20, "exceeded": 15,
        "forecast": 20, "projection": 15
    }
    
    earnings_found = False
    for keyword, weight in earnings_keywords.items():
        if keyword in text_lower:
            base_score += weight
            earnings_found = True
            time_horizon_signals["short"] += 15  # Earnings affect short-term
            if len(reasons_list) < 3 and "earnings" not in " ".join(reasons_list).lower():
                reasons_list.append(f"Kazanç/guidance haberi: {keyword}")
            break
    
    # ============================================================================
    # 3. RATING KEYWORDS (Medium weight)
    # ============================================================================
    rating_keywords = {
        "upgrade": 20, "downgrade": 20,
        "price target": 15, "target price": 15,
        "rating": 15, "analyst": 10
    }
    
    for keyword, weight in rating_keywords.items():
        if keyword in text_lower:
            base_score += weight
            if "upgrade" in keyword:
                impact_signals["bullish"] += 15
            elif "downgrade" in keyword:
                impact_signals["bearish"] += 15
            time_horizon_signals["short"] += 10
            if len(reasons_list) < 3 and "rating" not in " ".join(reasons_list).lower():
                reasons_list.append(f"Analist değerlendirmesi: {keyword}")
            break
    
    # ============================================================================
    # 4. REGULATORY/LEGAL KEYWORDS (High weight)
    # ============================================================================
    regulatory_keywords = {
        "sec": 30, "securities and exchange": 30,
        "regulator": 30, "regulatory": 25,
        "investigation": 30, "probe": 25,
        "fine": 25, "penalty": 25,
        "antitrust": 30, "monopoly": 25
    }
    
    for keyword, weight in regulatory_keywords.items():
        if keyword in text_lower:
            base_score += weight
            impact_signals["bearish"] += 20  # Regulatory issues are usually negative
            time_horizon_signals["long"] += 15  # Regulatory issues take time
            if len(reasons_list) < 3 and "regulator" not in " ".join(reasons_list).lower():
                reasons_list.append(f"Düzenleyici kurum haberi: {keyword}")
            break
    
    # ============================================================================
    # 5. INSIDER ACTIVITY KEYWORDS
    # ============================================================================
    insider_sell_keywords = ["insider sell", "executive sell", "ceo sell", "cfo sell", "director sell"]
    insider_buy_keywords = ["insider buy", "executive buy", "ceo buy", "cfo buy", "director buy"]
    
    for keyword in insider_sell_keywords:
        if keyword in text_lower:
            base_score += 20
            impact_signals["bearish"] += 25  # Insider selling is bearish
            time_horizon_signals["short"] += 10
            if len(reasons_list) < 3:
                reasons_list.append("Insider satış aktivitesi")
            break
    
    for keyword in insider_buy_keywords:
        if keyword in text_lower:
            base_score += 20
            impact_signals["bullish"] += 25  # Insider buying is bullish
            time_horizon_signals["short"] += 10
            if len(reasons_list) < 3:
                reasons_list.append("Insider alım aktivitesi")
            break
    
    # ============================================================================
    # 6. BULLISH/BEARISH SENTIMENT KEYWORDS
    # ============================================================================
    bullish_keywords = [
        "surge", "jump", "beats", "beat", "record", "growth",
        "upgrade", "strong", "rally", "soar", "gain",
        "bullish", "outperform", "buy", "positive", "optimistic",
        "büyüme", "rekor", "artış", "kazanç", "pozitif", "yükseliş"
    ]
    
    bearish_keywords = [
        "slump", "drop", "falls", "miss", "misses",
        "downgrade", "selloff", "risk", "warning",
        "plunge", "crash", "decline",
        "bearish", "underperform", "sell", "negative", "concern",
        "düşüş", "kayıp", "baskı", "negatif", "azalış", "daralma"
    ]
    
    bullish_count = sum(1 for kw in bullish_keywords if kw in text_lower)
    bearish_count = sum(1 for kw in bearish_keywords if kw in text_lower)
    
    if bullish_count > bearish_count:
        impact_signals["bullish"] += bullish_count * 5
        base_score += bullish_count * 3
    elif bearish_count > bullish_count:
        impact_signals["bearish"] += bearish_count * 5
        base_score += bearish_count * 3
    
    # ============================================================================
    # 7. NUMERIC/PERCENTAGE BONUS
    # ============================================================================
    # Check for percentage signs or numbers (indicates specific data)
    if re.search(r'\d+%', text) or re.search(r'\$\d+', text) or re.search(r'\d+\.\d+', text):
        base_score += 10
        if len(reasons_list) < 3 and not any("sayı" in r.lower() or "%" in r for r in reasons_list):
            reasons_list.append("Sayısal veri içeriyor")
    
    # ============================================================================
    # 8. SOURCE CREDIBILITY BONUS
    # ============================================================================
    if source:
        source_lower = source.lower()
        trusted_sources = ["reuters", "bloomberg", "wsj", "wall street journal", "financial times", "ft"]
        if any(trusted in source_lower for trusted in trusted_sources):
            base_score += 15
            if len(reasons_list) < 3 and not any("kaynak" in r.lower() for r in reasons_list):
                reasons_list.append(f"Güvenilir kaynak: {source}")
    
    # ============================================================================
    # 9. DETERMINE IMPACT
    # ============================================================================
    if impact_signals["bearish"] > impact_signals["bullish"] and impact_signals["bearish"] > 10:
        impact: Literal["bullish", "bearish", "neutral"] = "bearish"
    elif impact_signals["bullish"] > impact_signals["bearish"] and impact_signals["bullish"] > 10:
        impact = "bullish"
    else:
        impact = "neutral"
    
    # ============================================================================
    # 10. DETERMINE TIME HORIZON
    # ============================================================================
    if time_horizon_signals["intraday"] > time_horizon_signals["short"] and time_horizon_signals["intraday"] > time_horizon_signals["long"]:
        time_horizon: Literal["intraday", "short", "long"] = "intraday"
    elif time_horizon_signals["long"] > time_horizon_signals["short"]:
        time_horizon = "long"
    else:
        time_horizon = "short"
    
    # ============================================================================
    # 11. CLAMP SCORE TO 0-100
    # ============================================================================
    importance_score = max(0, min(100, base_score))
    
    # ============================================================================
    # 12. ENSURE REASONS LIST (max 3)
    # ============================================================================
    if not reasons_list:
        if impact == "bullish":
            reasons_list.append("Olumlu sinyaller içeriyor")
        elif impact == "bearish":
            reasons_list.append("Olumsuz sinyaller içeriyor")
        else:
            reasons_list.append("Nötr haber içeriği")
    
    reasons_list = reasons_list[:3]  # Max 3 reasons
    
    return {
        "importance_score": importance_score,
        "impact": impact,
        "time_horizon": time_horizon,
        "reasons": reasons_list
    }

