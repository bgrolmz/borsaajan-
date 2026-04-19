---
description: Single, mentor-style decision format for all AI outputs in Borsa Ajanı
---

# Mentor Decision Output Standard

## Purpose
Ensure every AI output (analysis, chat, news, notification) follows a clear mentor decision structure.

**Core Principles**:
- ❌ No raw data dumps
- ❌ No duplicate tables
- ❌ No ambiguity
- ✅ Clear, actionable decisions only

## Decision Structure (MANDATORY)

Every output must include these sections **in this exact order**:

### 1. Decision
**Format**: Single word + optional confidence
```
BUY (High Confidence)
HOLD (Medium Confidence)
REDUCE (Low Confidence)
AVOID
```

**Rules**:
- Only use: BUY / HOLD / REDUCE / AVOID
- Confidence levels: Low / Medium / High (optional)
- One decision per asset (for portfolio, one per holding)

### 2. Why (Short Reasoning)
**Format**: Maximum 3 bullet points
```
• Strong earnings beat with 15% revenue growth
• Technical breakout above resistance at ₺45
• Sector rotation favoring tech stocks this week
```

**Rules**:
- Focus on: risk, timing, and context
- No technical jargon without inline explanation
- Each bullet = one clear reason
- Avoid vague statements like "good fundamentals"

### 3. Action Plan
**Format**: Explicit, executable actions only
```
✓ Buy with 25% of position size at current price
✓ Set stop-loss at ₺42 (-8%)
✓ Target price: ₺52 (+15%)
```

**Good Examples**:
- "Buy with 25% of position size"
- "Reduce exposure by 30%"
- "Set stop-loss at -8%"
- "No action – wait for earnings on Jan 15"

**Bad Examples**:
- ❌ "Consider buying" (not explicit)
- ❌ "Monitor the situation" (not actionable)
- ❌ "Good entry point" (no specific action)

### 4. Mentor Scenario
**Format**: Forward-looking if-then statement
```
If price breaks ₺48 → expect momentum to ₺52 → add another 15% to position.
If earnings disappoint → expect drop to ₺40 → exit immediately.
```

**Rules**:
- Structure: "If X happens → expect Y → do Z"
- Focus on likely scenarios (bullish/bearish)
- Keep it short (1-2 sentences)

### 5. News Impact (if applicable)
**Format**: One-sentence interpretation
```
Central bank rate cut signals cheaper borrowing → positive for real estate stocks.
CEO resignation raises governance concerns → short-term uncertainty expected.
```

**Rules**:
- Explain direction (positive/negative/neutral)
- Explain relevance to this specific asset
- **Never show raw news text**
- Skip this section if no relevant news

### 6. Risk Note
**Format**: Single sentence worst-case awareness
```
⚠️ High volatility expected due to upcoming elections – position size accordingly.
⚠️ Illiquid stock – may be difficult to exit quickly if needed.
⚠️ Sector-wide downturn could override individual fundamentals.
```

**Rules**:
- One sentence only
- Focus on the biggest risk
- Be specific, not generic

## Output Examples

### Example 1: Single Asset Analysis
```
Decision: BUY (High Confidence)

Why:
• Strong Q4 earnings beat expectations by 12%
• Technical breakout above ₺45 resistance with high volume
• Sector rotation favoring tech stocks this month

Action Plan:
• Buy with 30% of intended position size at ₺46-47
• Set stop-loss at ₺42 (-8%)
• Target price: ₺55 (+20%)

Mentor Scenario:
If price consolidates above ₺48 → expect momentum continuation to ₺55 → add remaining 70% of position.

News Impact:
New government contract worth ₺500M announced → revenue visibility improved for next 2 years.

Risk Note:
⚠️ General market volatility could trigger stop-loss despite strong fundamentals.
```

### Example 2: Missing Data Scenario
```
Decision: HOLD

Why:
• Insufficient recent price data (last update 3 days ago)
• Earnings report pending (scheduled for Jan 20)
• Unable to assess current risk/reward

Action Plan:
• No action until data is updated
• Re-evaluate after earnings report

Mentor Scenario:
If data becomes available → reassess with fresh analysis → provide updated decision.

Risk Note:
⚠️ Stale data may hide recent negative developments – avoid trading until updated.
```

### Example 3: News-Driven Alert
```
Decision: REDUCE (Medium Confidence)

Why:
• CEO sudden resignation raises governance concerns
• Stock down 8% on the news with high selling volume
• No clear succession plan announced

Action Plan:
• Reduce position by 50% at current levels
• Keep remaining 50% with tight stop-loss at -12%
• Wait for management clarity before re-entering

Mentor Scenario:
If company announces credible replacement within 1 week → expect recovery to -3% → consider re-buying sold portion.

News Impact:
CEO resignation after 15 years → short-term uncertainty expected until succession plan clarified.

Risk Note:
⚠️ Further negative news could emerge – governance issues often come in clusters.
```

## Constraints & Rules

### Quality Standards
- **QUICK output must never be worse than DEEP**: Fast analysis should be conservative, not wrong
- **If data is missing → default to HOLD + explanation**: Never guess or hallucinate
- **No duplicated indicators across sections**: Each section serves a unique purpose
- **Technical terms must include short inline meaning**: Example: "RSI (momentum indicator) shows oversold"

### UI Integration
**Default View** (always visible):
- Decision
- Action Plan

**Collapsible** (expandable on demand):
- Why
- Mentor Scenario
- News Impact
- Risk Note

This structure is the **single source of truth** for UI rendering.

## Applies To
This standard applies to **all** AI outputs:
- ✅ Single asset analysis
- ✅ Portfolio analysis
- ✅ AI Chat responses
- ✅ News-driven alerts
- ✅ Push notifications
- ✅ Hermes tab insights

## Implementation Checklist

When implementing this standard in code:

- [ ] Create a `MentorDecision` data model with all 6 fields
- [ ] Validate that Decision field only accepts: BUY/HOLD/REDUCE/AVOID
- [ ] Enforce max 3 bullets in "Why" section
- [ ] Ensure Action Plan contains executable verbs (Buy/Reduce/Set/Wait)
- [ ] Format Mentor Scenario as if-then-do structure
- [ ] Make News Impact optional (null if no relevant news)
- [ ] Always include Risk Note (never null)
- [ ] Add UI flags for default vs. collapsible sections
- [ ] Log all outputs for quality review

## Anti-Patterns to Avoid

❌ **Data Dump**:
```
Price: ₺45.30
Volume: 1.2M
RSI: 67
MACD: 0.45
P/E: 12.3
...
```

❌ **Vague Decision**:
```
Decision: Maybe consider buying if conditions improve
```

❌ **No Action Plan**:
```
Action Plan: Monitor the situation and decide later
```

❌ **Raw News Copy-Paste**:
```
News: "Company X announced today that they will be expanding operations..."
```

✅ **Correct Format**: See examples above
