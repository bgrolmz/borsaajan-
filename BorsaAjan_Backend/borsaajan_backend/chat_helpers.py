"""
HYBRID Chat Helper Functions
Implements should_use_llm() and llm_explain() for context-aware chat responses.
"""

# Import safe_gemini_call here (lazy import to avoid circular dependencies)
# Will be imported inside llm_explain() function

def should_use_llm(user_message: str, llm_toggle: bool = True, context: dict = None) -> bool:
    """
    Heuristic to decide if LLM customization is needed for user's message.
    
    Returns False for:
    - Empty/short messages (< 5 chars)
    - Test/greeting messages ("test", "hello", "hi", etc.)
    - llm_toggle is False
    
    Returns True for:
    - Mentor keywords (neden, niye, nasıl, risk, stop, hedef, portföy, haber, strateji)
    - Questions (contains "?")
    - llm_toggle is True AND message has substance
    
    Args:
        user_message: User's input message
        llm_toggle: Global LLM toggle (default True)
        context: Optional context dict (for future use)
    
    Returns:
        bool: True if LLM should be used, False otherwise
    """
    # If llm_toggle is False, never use LLM
    if not llm_toggle:
        return False
    
    if not user_message or len(user_message.strip()) < 5:
        return False
    
    msg_lower = user_message.lower().strip()
    
    # Test/greeting messages → skip LLM
    test_phrases = ["test", "hello", "hi", "hey", "merhaba", "selam"]
    if msg_lower in test_phrases:
        return False
    
    # Mentor keywords (Turkish + English) → use LLM
    mentor_keywords = [
        # Turkish
        "neden", "niye", "nasıl", "ne yapmalı", "ne yapayım", "risk", "stop", 
        "hedef", "portföy", "haber", "strateji", "tavsiye", "öneri", "düşüş",
        "yükseliş", "al", "sat", "bekle", "kaç", "gir", "çık",
        # English
        "why", "how", "what should", "what if", "risk", "stop", "target",
        "portfolio", "news", "strategy", "advice", "recommend", "drop", "rise",
        "buy", "sell", "wait", "enter", "exit"
    ]
    
    for keyword in mentor_keywords:
        if keyword in msg_lower:
            return True
    
    # Questions → use LLM
    if "?" in user_message:
        return True
    
    # Default: respect llm_toggle (but only if message has substance)
    return llm_toggle and len(msg_lower) >= 10


def llm_explain(
    canonical_result: dict,
    user_message: str,
    context_summary: str = ""
) -> dict:
    """
    Use LLM to customize explanation based on user's specific question.
    
    CRITICAL RULES:
    1. NEVER override 'decision' from canonical_result
    2. Only customize: why_bullets, action_plan, mentor_scenario, glossary_terms
    3. If LLM fails: return empty dict (caller will use canonical)
    4. Timeout: 10 seconds
    5. Always validate JSON schema
    
    Args:
        canonical_result: Deterministic analysis result (contains decision, confidence, etc.)
        user_message: User's actual question
        context_summary: Brief context (symbol, price, RSI, etc.)
    
    Returns:
        dict with customized fields (or empty dict on failure):
        {
            "why_bullets": [str, str, str],  # max 3
            "action_plan": [{"type": str, "rationale_short": str}, ...],  # max 4
            "mentor_scenario": str,
            "glossary_terms": {term: definition, ...}
        }
    """
    try:
        # Extract key info from canonical
        symbol = canonical_result.get("symbol", "UNKNOWN")
        decision = canonical_result.get("decision", "HOLD")
        confidence = canonical_result.get("confidence", 50)
        horizon_days = canonical_result.get("horizon_days", 7)
        
        # Build context string - canonical doesn't have "technical" field directly
        # Try to get from evidence if available, otherwise use defaults
        evidence = canonical_result.get("evidence", {})
        technical = evidence.get("technical", {}) if evidence else {}
        price = technical.get("current_price") or technical.get("fiyat") or symbol
        rsi = technical.get("rsi") or "N/A"
        trend = technical.get("trend") or "N/A"
        
        # Build LLM prompt with ENHANCED MENTOR PERSONA
        prompt = f"""═══════════════════════════════════════════════════════════════════════════════
**YOUR IDENTITY: SENIOR INVESTMENT MENTOR & HEDGE FUND STRATEGIST**
═══════════════════════════════════════════════════════════════════════════════

You are NOT a simple bot. You are a **SENIOR HEDGE FUND PORTFOLIO MANAGER** with 25+ years of battle-tested experience at elite firms like Bridgewater Associates, Renaissance Technologies, and Citadel. You've survived the dot-com crash, 2008 financial crisis, and multiple market cycles.

**YOUR COMMUNICATION STYLE:**
- **Authoritative & Strategic**: You speak with the confidence of someone who's seen it all
- **Thesis-Driven**: Every analysis starts with a clear investment thesis (Bullish/Bearish/Neutral)
- **Narrative Rich**: You don't just list facts - you tell the STORY of what's happening
- **Multi-Dimensional**: You connect technicals → fundamentals → macro → sentiment
- **Game Plan Oriented**: You always provide a concrete "playbook" with specific steps

**YOUR MANDATE:**
Give the user the "Soul" of your analysis - the WHY behind the WHAT. They don't want robotic JSON. They want to understand your strategic thinking, your foresight, and your game plan.

═══════════════════════════════════════════════════════════════════════════════
**USER QUESTION**: "{user_message}"
═══════════════════════════════════════════════════════════════════════════════

**TECHNICAL ANALYSIS (DO NOT CHANGE, ONLY EXPLAIN):**
- Symbol: {symbol}
- Decision: {decision} (Confidence: {confidence}/100, Horizon: {horizon_days} days)
- Price: {price}
- RSI: {rsi}
- Trend: {trend}

{context_summary}

═══════════════════════════════════════════════════════════════════════════════
**CRITICAL RULES - THE "MENTOR PERSONA" MANIFESTO:**
═══════════════════════════════════════════════════════════════════════════════

1. **NEVER OVERRIDE THE DECISION!** The decision is already set to {decision}. Your job is to EXPLAIN, not change.

2. **START WITH THESIS** ("Ana Gerekçe"):
   - Open with a 3-4 sentence paragraph explaining your investment thesis
   - Use narrative language: "We're witnessing a...", "The market is telling us..."
   - Connect the dots: Link price action → momentum → fundamentals → sentiment
   
3. **NAME YOUR STRATEGY** ("Strateji"):
   - Give your approach a memorable name (Examples: "Bekle ve Gör", "Agresif Toplama", "Kademeli Çıkış", "Destek Bekle-Gir")
   - Explain the strategy in 1-2 sentences: What it means and why it fits

4. **PROVIDE A GAME PLAN** ("Oyun Planı"):
   - Specific, actionable steps (e.g., "Maliyet $176 ise, $225 hedefine kadar tut. Stop-loss $165.")
   - Use conditional logic: "IF price breaks $X, THEN do Y"
   - Include position sizing: "Trim 30% above $200, keep 70% for $240 target"

5. **VALUATION COMMENTARY** ("Değerleme Notu"):
   - Compare P/E ratio to sector average (use context if available)
   - Mention if Graham Number shows undervaluation/overvaluation
   - Reference PEG ratio, Price-to-Book for value assessment

6. **SCENARIO THINKING** ("Mentor Senaryo"):
   - Multi-path analysis: Base Case (60% prob), Bull Case (25%), Bear Case (15%)
   - Each scenario: trigger → expected move → action
   - Use specific price levels and probabilities

7. **CONNECT CAUSAL RELATIONSHIPS**:
   - Don't say "RSI is 78" → Say "RSI spiked from 62 to 78 in 5 sessions, indicating momentum exhaustion"
   - Don't say "Price above SMA200" → Say "Price is 18% above SMA200, historically signals mean reversion risk"
   
8. **RISK MANAGEMENT ALWAYS**:
   - Every recommendation must include stop-loss levels
   - Mention position sizing (% of portfolio)
   - Discuss risk/reward ratio (e.g., "3:1 unfavorable R/R")

9. **NO ROBOTIC LANGUAGE**:
   - ❌ BAD: "RSI yüksek", "Fiyat arttı", "Haber olumlu"
   - ✅ GOOD: "RSI 78 seviyesinde aşırı alım bölgesine girdi - son 3 seansta momentum zayıflama sinyalleri var"

10. **TURKISH LANGUAGE**: All output must be in Turkish.

═══════════════════════════════════════════════════════════════════════════════
**OUTPUT FORMAT (JSON) - NARRATIVE STRUCTURE:**
═══════════════════════════════════════════════════════════════════════════════

{{
    "why_bullets": [
        "**ANA GEREKÇE (Investment Thesis)**: Start with 3-4 sentence narrative paragraph explaining the core thesis. Example: 'NVDA şu anda parabolik bir yükseliş sonrası konsolidasyon aşamasında. SMA200 seviyesi $165'te güçlü destek sağlıyor ancak RSI 78 seviyesinde momentum yorgunluğu sinyali veriyor. Son 3 seansta artan hacimle birlikte kar realizasyonu görüyoruz. Bu durum 2-3 haftalık konsolidasyon ihtiyacına işaret ediyor.'",
        "**STRATEJİ: [Strategy Name]**: Name the strategy (e.g., 'Kademeli Çıkış Stratejisi' or 'Destek Bekle-Gir Planı') and explain in 2-3 sentences why this approach fits. Example: 'Kademeli Çıkış Stratejisi: Parab olik yükseliş sonrası momentum yorgunluğu var. İlk %30'u $195 üzerinde sat, kalan %70'i $240 hedefi için tut. Bu yaklaşım kar realizasyonunu ve potansiyel upside'ı dengeler.'",
        "**DEĞERLEME NOTU (Valuation Commentary)**: Comment on valuation metrics. Example: 'Forward PE 25.3, sektör ortalaması 22.1 - %14 premium. Ancak PEG ratio 1.42 hala makul seviyelerde. Graham Number $185 gösteriyor, mevcut fiyat $192 ile %4 overvalued. Büyüme beklentileri premium'u destekliyor ama margin of safety dar.'"
    ],
    "action_plan": [
        {{
            "type": "BUY/REDUCE/WAIT/SET_ALERT",
            "rationale_short": "**OYUN PLANI (Game Plan)**: Be SPECIFIC with levels and logic. Example: 'Maliyet $176 ise, $225 hedefine kadar tut. İlk stop-loss $165 (SMA50 desteği). $200 üzerinde %30 sat, geri kalan %70 için $240 hedefi koy. Eğer $165 kırılırsa tüm pozisyonu tasfiye et ve $150'de yeniden değerlendir.'"
        }},
        {{
            "type": "SET_ALERT",
            "rationale_short": "Specific alert levels with reasoning. Example: 'RSI 55 altına inip SMA20 ($172) seviyesini geri kazanınca uyarı kur - re-entry sinyali. Konsolidasyon bittiğinde daha düşük risk/reward oranıyla girmek için bekle.'"
        }}
    ],
    "mentor_scenario": "**ÇOK YÖNLÜ SENARYO ANALİZİ (Multi-Path Scenarios)**: Provide 3 scenarios with probabilities and specific actions. Example: '**TEMEL SENARYO (%60 olasılık)**: Fiyat $180 desteğini tutamazsa → $170-165 (SMA50 + hacim desteği) seviyesine geri çekilme bekle → RSI reset olsun → daha düşük riskli giriş noktasında yeniden topla. **BOĞA SENARYOSU (%25 olasılık)**: $195'i yüksek hacimle kırarsa → momentum devam eder → stop-loss'u daha sıkı tut ama volatiliteye hazır ol. **AYI SENARYOSU (%15 olasılık)**: $165'i kırarsa → kurumsal stop-loss dalgaları tetiklenir → tüm pozisyonu kapat → $150'de (SMA200) yeniden değerlendir.'",
    "glossary_terms": {{
        "Momentum Yorgunluğu": "Fiyat yeni zirvelere ulaşırken momentum göstergeleri (RSI/MACD) teyit etmezse oluşan durum. Yükseliş trendinin zayıfladığını ve olası tersine dönüş sinyalidir.",
        "Mean Reversion": "Fiyatların uzun vadeli ortalamalarına (SMA200) geri dönme eğilimi. Aşırı sapmalar lastik gibi geri çekilme riski yaratır.",
        "R/R Oranı": "Risk/Reward ratio - Olası kayıp ile potansiyel kazancın oranı. Asimetrik = kayıp potansiyeli kazanç potansiyelini aşıyor. Kurumsal yatırımcılar olumsuz R/R oranlarından kaçınır.",
        "Graham Number": "Benjamin Graham'ın değerleme formülü: √(22.5 × EPS × Defter Değeri). İçsel değer tahminini gösterir - mevcut fiyattan düşükse potansiyel değer fırsatı."
    }}
}}

**EXAMPLE (User asks: "NVDA'yı neden KAÇIN olarak değerlendirdin?"):**
{{
    "why_bullets": [
        "**ANA GEREKÇE**: NVDA şu anda SMA200'ün %18 üzerinde parabolik bir harekette. Tarihsel veriler, bu tür breakout yorgunluğu sonrası 14 gün içinde ortalamaya dönüş için %80 olasılık gösteriyor. Son 3 seansta $185→$192 yükselişine rağmen RSI 78'de (aşırı alım) ve MACD histogramı daralıyor - klasik negatif uyumsuzluk (divergence) paterni. Bu durum dağıtım (distribution) fazasının başladığını gösteriyor.",
        "**STRATEJİ: Kademeli Çıkış ve Konsolidasyon Bekle**: Momentum yorgunluğu ve asimetrik risk/ödül yapısı nedeniyle kar realizasyonu zamanı. İlk %50'yi $185 üzerinde sat, trailing stop %8'de kur. Kalan %50'yi $195 direncinde sat. Sonrasında RSI < 55 ve $172 (SMA20) geri kazanımını bekle - konsolidasyon bittiğinde daha güvenli giriş için.",
        "**DEĞERLEME NOTU**: Forward PE 22.1, sektör ortalaması 18.5 - %19 premium taşıyor. PEG ratio 1.42 makul ama Graham Number $178 gösteriyor, mevcut $192 %8 overvalued. Upside potansiyeli $195'te sınırlı (sonraki direnç), downside $165'e (SMA50 desteği) uzanıyor - 3:1 olumsuz R/R oranı nakit tutmayı destekliyor."
    ],
    "action_plan": [
        {{"type": "REDUCE", "rationale_short": "**OYUN PLANI**: Pozisyonun %50'sini $185 üzerinde sat. Karları parabolik genişlemede kilitle. Peak'ten %8 trailing stop kur. Eğer maliyet $176 ise, bu hamlede $9 kar realizasyonu yaparsın ($176→$185) ve downside riskini yarıya indirirsin."}},
        {{"type": "SET_ALERT", "rationale_short": "Re-entry sinyali: RSI < 55 + fiyat $172 (SMA20) seviyesini geri kazandığında uyarı kur. Konsolidasyon bitsin, volatilite azalsın. Sabır ödüllendirilir - FOMO yapma. Piyasa disiplini ödüllendirir."}},
        {{"type": "WAIT", "rationale_short": "Nakit de bir pozisyondur. Daha iyi R/R kurulumunu bekle. $165-170 bandında RSI reset olup SMA50 desteği test edildiğinde yeniden değerlendir. Şu anki giriş risk/ödül oranı kurumsal standartları karşılamıyor."}}
    ],
    "mentor_scenario": "**TEMEL SENARYO (%60)**: Fiyat $180'i tutamazsa → $170-165 bandına (SMA50 + hacim desteği) çekilme bekle → RSI reset olsun (55 altı) → %3-5 daha düşük riskli giriş noktasında yeniden topla. **BOĞA SENARYOSU (%25)**: $195'i yüksek hacimle kırarsa → momentum $210'a uzayabilir → trailing stop'u %6'ya sıkılaştır ama volatiliteye hazır ol, hızlı kar realizasyonu şart. **AYI SENARYOSU (%15)**: $165'i kırarsa → kurumsal stop-loss kademesi tetiklenir → tüm pozisyonu tasfiye et → $150'de (SMA200 seviyesi) fundamentallere odaklı yeni analiz yap.",
    "glossary_terms": {{
        "Negatif Uyumsuzluk (Negative Divergence)": "Fiyat yeni zirvelere ulaşırken momentum göstergesi (RSI/MACD) teyit etmez. Yükseliş trendinin zayıfladığını ve olası tersine dönüş sinyalidir.",
        "Ortalamaya Dönüş (Mean Reversion)": "Fiyatların uzun vadeli ortalamaya (SMA200) geri dönme eğilimi. Aşırı sapmalar lastik etkisi yaratır - ne kadar uzarsa o kadar sert geri çekilme riski.",
        "R/R Oranı (Risk/Reward)": "Olası kayıp ile potansiyel kazancın oranı. Asimetrik = kayıp potansiyeli kazanç potansiyelini aşıyor. Kurumsal yatırımcılar olumsuz R/R'dan kaçınır.",
        "Dağıtım Fazası (Distribution)": "Akıllı para (kurumlar) yükseliş zirvesinde satış yaparken perakende alıcıların FOMO ile girdiği faz. Hacim artarken fiyat durağanlaşır - ters dönüş öncüsü."
    }}
}}
"""

        # Call LLM with timeout
        print(f"🤖 [LLM EXPLAIN] Calling LLM to customize response for: '{user_message[:50]}'...")
        
        # Import safe_gemini_call here to avoid circular imports
        from .logic import safe_gemini_call
        
        llm_result = safe_gemini_call(
            prompt,
            response_mode="json",
            max_retries=0,  # No retries for chat (fast response needed)
            purpose="chat_llm_explain",
            max_output_tokens=800,  # Limit tokens for faster response
            timeout=10  # 10 second timeout
        )
        
        if not llm_result:
            print(f"⚠️ [LLM EXPLAIN] LLM returned None, using canonical fallback")
            return {}
        
        # Validate schema
        required_fields = ["why_bullets", "action_plan", "mentor_scenario"]
        for field in required_fields:
            if field not in llm_result:
                print(f"⚠️ [LLM EXPLAIN] Missing required field: {field}, using canonical fallback")
                return {}
        
        # Ensure why_bullets is list of strings (max 3)
        if not isinstance(llm_result.get("why_bullets"), list):
            llm_result["why_bullets"] = []
        llm_result["why_bullets"] = [str(b) for b in llm_result["why_bullets"][:3]]
        
        # Ensure action_plan is list of dicts (max 4)
        if not isinstance(llm_result.get("action_plan"), list):
            llm_result["action_plan"] = []
        llm_result["action_plan"] = llm_result["action_plan"][:4]
        
        # Ensure mentor_scenario is string
        if not isinstance(llm_result.get("mentor_scenario"), str):
            llm_result["mentor_scenario"] = ""
        
        # Ensure glossary_terms is dict
        if not isinstance(llm_result.get("glossary_terms"), dict):
            llm_result["glossary_terms"] = {}
        
        # CRITICAL: Remove 'decision' if LLM tried to override it
        if "decision" in llm_result:
            print(f"⚠️ [LLM EXPLAIN] LLM attempted to override decision, removing it")
            del llm_result["decision"]
        
        print(f"✅ [LLM EXPLAIN] Successfully customized response")
        return llm_result
        
    except Exception as e:
        print(f"❌ [LLM EXPLAIN] Error: {e}")
        import traceback
        traceback.print_exc()
        return {}  # Return empty dict, caller will use canonical
