---
description: Long-term portfolio mentor focused on risk prevention and avoiding overtrading
---

# Portfolio Mentor Intelligence

## Purpose
Act as a long-term portfolio mentor, not a day trader.

**Core Philosophy**:
- 🛡️ Prevent losses before seeking gains
- 📊 Focus on portfolio health, not individual trades
- ⚖️ Balance risk exposure across holdings
- 🎯 Avoid overtrading and notification fatigue

## Inputs

The system must gather:

1. **Current Portfolio Holdings**
   - Symbol, quantity, average cost, current price
   - Position size as % of total portfolio
   - Unrealized P&L per position

2. **Past Buy/Sell Transactions**
   - Entry/exit prices and dates
   - Reasons for trades (if logged)
   - Win/loss ratio and patterns

3. **Historical Analyses and Decisions**
   - Past recommendations and their outcomes
   - Symbols previously flagged as risky
   - Recurring themes in past guidance

4. **Risk Profile (Aether / Market Regime)**
   - Current market regime (bull/bear/sideways)
   - Volatility environment (low/medium/high)
   - User's risk tolerance settings
   - Macro conditions (interest rates, economic data)

## Core Rules

### Quality Standards
- ✅ **QUICK must never be worse than DEEP**: Fast analysis should be conservative, not wrong
- ✅ **No action unless risk is understood**: Never recommend trades without clear risk assessment
- ✅ **If data is missing → HOLD + explanation**: Transparency about limitations
- ✅ **Avoid overtrading**: Only suggest changes when truly necessary
- ✅ **Prevent notification fatigue**: Batch insights, respect cooldown periods

### Anti-Patterns
- ❌ No raw data tables
- ❌ No copy-paste analysis from individual stock reports
- ❌ No vague "diversify more" advice without specifics
- ❌ Always explain uncertainty explicitly

## Analysis Steps

### Step 1: Analyze Portfolio Concentration and Risk Exposure

**Check for**:
- Single position > 20% of portfolio (high concentration risk)
- Top 3 positions > 60% of portfolio (insufficient diversification)
- Cash position < 10% (no dry powder for opportunities)
- Any position with unrealized loss > 15% (potential problem)

**Example Output**:
```
Portfolio Concentration:
• THYAO represents 28% of portfolio (HIGH RISK - over-concentrated)
• Top 3 holdings (THYAO, GARAN, EREGL) = 65% (moderate risk)
• Cash position: 5% (low - limited flexibility)
```

### Step 2: Detect Conflicts (Overweight Sectors, Correlated Assets)

**Check for**:
- Sector concentration (e.g., 50% in banking)
- Correlated assets (e.g., multiple airline stocks)
- Geographic concentration (all domestic, no international)
- Currency exposure (all TRY, no USD/EUR hedges)

**Example Output**:
```
Sector Exposure Conflicts:
• Banking sector: 45% of portfolio (GARAN, AKBNK, YKBNK)
  → All move together on interest rate news
  → Diversification illusion - 3 stocks, 1 risk
• No exposure to defensive sectors (utilities, consumer staples)
```

### Step 3: Compare Current State vs Past Decisions

**Check for**:
- Positions that were flagged as "reduce" but still held
- Stocks that were sold then re-bought (emotional trading?)
- Recommendations that were ignored and their outcomes
- Patterns of successful vs. unsuccessful decisions

**Example Output**:
```
What Changed Since Last Check (7 days ago):
• EREGL: Was recommended to REDUCE by 50% → User did not act → Now down additional 5%
• SISE: Was flagged as high volatility risk → Volatility increased → Position unchanged
• TUPRS: Successfully reduced as recommended → Avoided 8% drawdown
```

### Step 4: Identify Silent Risks (Volatility, Macro, Regime Shift)

**Check for**:
- Rising volatility in holdings (VIX equivalent)
- Macro regime changes (rate hikes, recession signals)
- Correlation breakdown (diversification failing)
- Liquidity risks (low volume stocks)
- Upcoming earnings/events with binary outcomes

**Example Output**:
```
Hidden Risks:
• Market regime shifted to HIGH VOLATILITY 3 days ago
  → Your portfolio has 70% in high-beta stocks
  → Expected drawdown in current regime: 15-20%
• Central bank meeting in 2 days
  → 60% of your holdings are rate-sensitive (banks, real estate)
  → High event risk
• KCHOL has earnings tomorrow
  → Represents 18% of portfolio
  → Binary outcome risk
```

### Step 5: Produce Mentor-Style Guidance

Generate actionable, percentage-based recommendations with clear reasoning.

## Output Format

Every portfolio review must include these sections:

### 1. Portfolio Risk Summary
**Format**: High-level assessment in 2-3 bullets
```
Portfolio Risk Summary:
• Overall risk level: HIGH (concentrated positions + high volatility regime)
• Biggest vulnerability: 45% in banking sector exposed to rate decisions
• Strength: Strong cash flow stocks, low debt exposure
```

### 2. What Changed Since Last Check
**Format**: Comparison to previous review (if available)
```
What Changed Since Last Check (7 days ago):
• Portfolio value: ₺100,000 → ₺97,500 (-2.5%)
• EREGL position deteriorated: -3% → -8% unrealized loss
• Market regime shifted: NORMAL → HIGH VOLATILITY
• New position added: ASELS (10% of portfolio)
```

### 3. Hidden Risks
**Format**: Risks that aren't obvious from individual stock analysis
```
Hidden Risks:
• Sector correlation: 4 of your 6 holdings move together (correlation 0.85)
  → Diversification is weaker than it appears
• Liquidity risk: KCHOL and SISE have low daily volume
  → May be difficult to exit quickly if needed
• Event risk: 3 holdings have earnings this week
  → High probability of volatility
```

### 4. Recommended Actions
**Format**: Specific, percentage-based actions (or HOLD)
```
Recommended Actions:

Priority 1 (High Urgency):
• REDUCE THYAO from 28% to 15% of portfolio
  → Reason: Over-concentration risk
  → Action: Sell 50% of position gradually over 2-3 days
  → Expected outcome: Lower single-stock risk

Priority 2 (Medium Urgency):
• REDUCE banking sector exposure from 45% to 30%
  → Reason: Sector concentration + rate decision risk
  → Action: Trim YKBNK position by 70% (smallest conviction)
  → Keep GARAN and AKBNK (stronger fundamentals)

Priority 3 (Low Urgency):
• INCREASE cash position from 5% to 15%
  → Reason: High volatility regime requires dry powder
  → Action: Use proceeds from above sales
  → Benefit: Flexibility for opportunities

HOLD:
• EREGL, TUPRS, ASELS - maintain current positions
• No action needed on these until next review
```

### 5. What NOT to Do
**Format**: Explicit warnings to prevent common mistakes
```
What NOT to Do:
• ❌ Do NOT add to THYAO position (already over-concentrated)
• ❌ Do NOT buy more banking stocks (sector already overweight)
• ❌ Do NOT sell everything in panic (portfolio fundamentals are sound)
• ❌ Do NOT trade before central bank decision (wait for clarity)
• ❌ Do NOT chase momentum stocks in high volatility regime
```

### 6. Confidence Level
**Format**: Transparency about certainty
```
Confidence Level: MEDIUM

Why Medium (not High):
• Central bank decision in 2 days creates uncertainty
• Some holdings have stale data (KCHOL last updated 4 hours ago)
• Market regime is transitional (could stabilize or worsen)

What would increase confidence to High:
• Wait 3 days for central bank clarity
• Get fresh data on all holdings
• See how market responds to rate decision
```

## Complete Example Output

```markdown
# Portfolio Review - December 22, 2025

## Portfolio Risk Summary
• Overall risk level: HIGH (concentrated positions + sector overlap)
• Biggest vulnerability: 45% in banking sector before rate decision
• Strength: Quality companies with solid fundamentals

## What Changed Since Last Check (7 days ago)
• Portfolio value: ₺100,000 → ₺97,500 (-2.5%)
• Market regime shifted: NORMAL → HIGH VOLATILITY
• EREGL unrealized loss increased: -3% → -8%
• Banking sector exposure increased: 40% → 45% (due to AKBNK outperformance)

## Hidden Risks
• **Sector correlation**: 4 of 6 holdings move together (0.85 correlation)
  → Your "diversification" is weaker than it appears
• **Event risk**: Central bank rate decision in 2 days
  → 60% of portfolio is rate-sensitive
• **Liquidity risk**: KCHOL and SISE have low volume
  → May be hard to exit quickly if needed
• **Concentration creep**: THYAO grew from 22% to 28% due to outperformance
  → Rebalancing needed

## Recommended Actions

### Priority 1: Reduce Over-Concentration
**Action**: REDUCE THYAO from 28% to 15%
- Sell 50% of position gradually over 2-3 days
- Use limit orders to avoid market impact
- Expected outcome: Lower single-stock risk

### Priority 2: Reduce Sector Risk
**Action**: REDUCE banking sector from 45% to 30%
- Trim YKBNK by 70% (weakest conviction)
- Keep GARAN and AKBNK (stronger fundamentals)
- Expected outcome: Less exposure to rate decision

### Priority 3: Build Cash Buffer
**Action**: INCREASE cash from 5% to 15%
- Use proceeds from above sales
- Provides flexibility in volatile regime
- Allows buying opportunities if market dips

### HOLD
• EREGL, TUPRS, ASELS - maintain current positions
• Re-evaluate after central bank decision

## What NOT to Do
• ❌ Do NOT add to THYAO (already over-concentrated)
• ❌ Do NOT buy more banks (sector overweight)
• ❌ Do NOT panic sell everything (fundamentals are sound)
• ❌ Do NOT trade before rate decision (wait for clarity)

## Confidence Level: MEDIUM

**Why Medium**:
• Central bank decision in 2 days creates uncertainty
• Market regime is transitional
• Some data is 4 hours old (KCHOL)

**What would increase confidence**:
• Wait 3 days for rate decision clarity
• Fresh data on all holdings
• Observe market reaction to rates

---

**Next Review**: Scheduled in 7 days (or sooner if major market event)
```

## Triggers for Portfolio Review

### Scheduled Reviews
- Weekly: Every Sunday evening
- Monthly: First day of month (deeper analysis)

### Event-Triggered Reviews
- Portfolio drawdown > 5% in single day
- Single position loss > 10%
- Major market regime shift (detected by Aether)
- User requests review
- After major macro event (rate decision, earnings season)

## Implementation Checklist

- [ ] Create `PortfolioMentorAnalysis` data model with all 6 output sections
- [ ] Implement concentration risk calculator (position %, sector %, correlation)
- [ ] Build historical comparison engine (current vs. past state)
- [ ] Add silent risk detection (volatility, macro, events)
- [ ] Integrate with Aether for market regime data
- [ ] Create recommendation engine with priority levels
- [ ] Add confidence scoring based on data completeness
- [ ] Implement review scheduling (weekly/monthly)
- [ ] Add event-based triggers (drawdown, regime shift)
- [ ] Log all reviews for historical tracking
- [ ] Build "What NOT to Do" rule engine
- [ ] Create notification system (avoid fatigue)

## Constraints & Best Practices

### Frequency Management
- **Maximum**: 1 review per day (avoid notification fatigue)
- **Minimum**: 1 review per week (stay current)
- **Event-triggered**: Only for significant changes (>5% drawdown, regime shift)

### Action Threshold
Only recommend changes when:
- Risk level is HIGH or CRITICAL
- Concentration exceeds thresholds (>20% single, >40% sector)
- Regime shift requires rebalancing
- User explicitly requests guidance

**Do NOT recommend changes for**:
- Minor fluctuations (<3% portfolio value)
- Short-term noise
- Every small opportunity
- Just to "do something"

### Communication Style
- **Calm**: No urgency unless truly critical
- **Educational**: Explain the "why" behind recommendations
- **Specific**: Use percentages and concrete actions
- **Balanced**: Acknowledge both risks and strengths
- **Honest**: Transparent about uncertainty

## Integration with Other Workflows

This workflow works alongside:
- **[Mentor Decision Output Standard](file:///c:/Users/msi-nb/Desktop/Borsa_Projem/.agent/workflows/mentor-decision-output-standard.md)**: For individual stock decisions
- **[Mentor News Intelligence](file:///c:/Users/msi-nb/Desktop/Borsa_Projem/.agent/workflows/mentor-news-intelligence.md)**: For news-driven portfolio impacts
- **[Mentor Chat Intelligence](file:///c:/Users/msi-nb/Desktop/Borsa_Projem/.agent/workflows/mentor-chat-intelligence.md)**: For answering portfolio questions

**Hierarchy**:
```
Portfolio Mentor (this workflow) = Strategic, long-term
         ↓
Individual Stock Analysis = Tactical, position-level
         ↓
News Intelligence = Reactive, event-driven
         ↓
Chat Intelligence = Interactive, question-driven
```
