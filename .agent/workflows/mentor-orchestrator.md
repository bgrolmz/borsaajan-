---
description: Coordinate and prioritize all mentor workflows for consistent behavior
---

# Mentor Orchestrator

## Purpose
Coordinate and prioritize all mentor workflows to ensure consistent, non-conflicting behavior across the Borsa Ajanı system.

**Core Responsibility**: Act as the central decision-maker that routes requests to the appropriate mentor workflow and resolves conflicts when multiple workflows produce different recommendations.

## Managed Workflows

The orchestrator coordinates these workflows:

1. **[Mentor News Intelligence](file:///c:/Users/msi-nb/Desktop/Borsa_Projem/.agent/workflows/mentor-news-intelligence.md)** - News-driven analysis
2. **[Mentor Chat Intelligence](file:///c:/Users/msi-nb/Desktop/Borsa_Projem/.agent/workflows/mentor-chat-intelligence.md)** - User question handling
3. **[Portfolio Mentor Intelligence](file:///c:/Users/msi-nb/Desktop/Borsa_Projem/.agent/workflows/portfolio-mentor-intelligence.md)** - Portfolio health monitoring
4. **[Mentor Decision Output Standard](file:///c:/Users/msi-nb/Desktop/Borsa_Projem/.agent/workflows/mentor-decision-output-standard.md)** - Output formatting (mandatory for all)

## Trigger Rules

The orchestrator routes requests based on trigger type:

### Rule 1: Critical News → Mentor News Intelligence
```
Trigger: News with score ≥ threshold
Route to: Mentor News Intelligence
Priority: HIGH (if affects portfolio holdings)
Output: News impact + suggested action
```

**Example**:
```
Input: "CEO resignation at EREGL" (user holds EREGL)
Route: Mentor News Intelligence
Reason: Critical news affecting portfolio holding
Priority: HIGH
```

### Rule 2: User Question → Mentor Chat Intelligence
```
Trigger: User sends message in chat
Route to: Mentor Chat Intelligence
Priority: IMMEDIATE (user is waiting)
Output: Contextual answer with decision
```

**Example**:
```
Input: "Should I buy more THYAO?"
Route: Mentor Chat Intelligence
Reason: Direct user question
Priority: IMMEDIATE
Context: Check portfolio for existing THYAO position
```

### Rule 3: Scheduled Check → Portfolio Mentor Intelligence
```
Trigger: Weekly/monthly schedule OR >5% drawdown
Route to: Portfolio Mentor Intelligence
Priority: MEDIUM (unless emergency drawdown)
Output: Portfolio review with rebalancing guidance
```

**Example**:
```
Input: Sunday 8:00 PM (scheduled weekly review)
Route: Portfolio Mentor Intelligence
Reason: Scheduled portfolio health check
Priority: MEDIUM
```

### Rule 4: Any Output → Mentor Decision Output Standard (MANDATORY)
```
Trigger: ANY workflow produces output
Route to: Mentor Decision Output Standard
Priority: MANDATORY (enforced)
Output: Standardized 6-section format
```

**All outputs must pass through this formatting layer before reaching the user.**

## Priority Rules

When multiple triggers occur simultaneously, apply these priority rules:

### Priority 1: Risk Alerts Override Opportunity Alerts
```
Scenario: News suggests BUY opportunity + Portfolio shows concentration risk
Decision: Prioritize portfolio risk warning over buy signal
Rationale: Prevent losses before seeking gains
```

**Example**:
```
News Intelligence: "BUY THYAO (positive earnings)"
Portfolio Mentor: "REDUCE THYAO (28% concentration risk)"

Orchestrator Decision: HOLD
Reason: Portfolio risk overrides individual opportunity
Output: "THYAO shows positive earnings, but you're already over-concentrated at 28%. 
         HOLD current position. Do not add more."
```

### Priority 2: Portfolio-Wide Risk Overrides Single-Asset Signals
```
Scenario: Individual stock looks bullish + Portfolio is over-leveraged
Decision: Portfolio health takes precedence
Rationale: Systemic risk > individual opportunity
```

**Example**:
```
Chat Intelligence: "BUY GARAN (technical breakout)"
Portfolio Mentor: "Banking sector at 45% (overweight)"

Orchestrator Decision: AVOID
Reason: Sector concentration risk
Output: "GARAN setup looks good, but your banking exposure is already 45%. 
         AVOID adding to sector concentration."
```

### Priority 3: HOLD Overrides BUY if Confidence < MEDIUM
```
Scenario: Workflow suggests BUY with LOW confidence
Decision: Default to HOLD
Rationale: Don't act on uncertain signals
```

**Example**:
```
News Intelligence: "BUY TUPRS (Low Confidence - data incomplete)"

Orchestrator Decision: HOLD
Reason: Confidence below threshold
Output: "TUPRS news is positive but data is incomplete. 
         HOLD until confidence improves."
```

### Priority 4: No Notification Unless Confidence ≥ Threshold
```
Scenario: Workflow produces output with confidence < threshold
Decision: Suppress notification, log internally
Rationale: Avoid notification fatigue
```

**Example**:
```
News Intelligence: "HOLD ASELS (Low Confidence)"

Orchestrator Decision: Suppress notification
Reason: Low confidence + no actionable change
Action: Log internally, do not notify user
```

## Conflict Resolution

When workflows disagree, apply these resolution rules:

### Rule 1: If Workflows Disagree → Default to HOLD
```
Scenario: Two workflows produce conflicting decisions
Resolution: HOLD + explain both perspectives
Rationale: Uncertainty requires caution
```

**Example**:
```
News Intelligence: "BUY SISE (positive sector news)"
Portfolio Mentor: "REDUCE SISE (low liquidity risk)"

Orchestrator Decision: HOLD
Reason: Conflicting signals indicate uncertainty
Output:
  Decision: HOLD
  
  Why:
  • Positive sector news suggests upside (News Intelligence)
  • Low liquidity creates exit risk (Portfolio Mentor)
  • Conflicting signals → wait for clarity
  
  Action Plan:
  • Maintain current position
  • Monitor liquidity and news developments
  • Re-evaluate in 3 days
  
  Risk Note:
  ⚠️ Conflicting analysis indicates uncertain environment - avoid action until clarity improves.
```

### Rule 2: Log Disagreement Reason Internally
```
For each conflict:
- Log both workflow outputs
- Log orchestrator decision
- Log reason for override
- Track conflict patterns for system improvement
```

**Log Format**:
```json
{
  "timestamp": "2025-12-22T13:59:20Z",
  "symbol": "SISE",
  "conflict": {
    "news_intelligence": "BUY",
    "portfolio_mentor": "REDUCE"
  },
  "orchestrator_decision": "HOLD",
  "reason": "Conflicting signals - news positive but liquidity risk",
  "confidence": "LOW"
}
```

### Rule 3: Explain Uncertainty to User
```
Never hide conflicts from user
Be transparent about disagreement
Explain both perspectives
Let user make informed decision
```

## Notification Policy

Manage notification frequency to avoid fatigue:

### Rule 1: Avoid Repeated Alerts
```
Check: Has user been notified about this symbol in last X hours?
If yes: Suppress unless risk level increased
If no: Allow notification
```

**Example**:
```
8:00 AM: "EREGL - HOLD (news pending)"
10:00 AM: "EREGL - HOLD (still pending)" → SUPPRESSED (duplicate)
2:00 PM: "EREGL - REDUCE (negative earnings)" → ALLOWED (risk escalated)
```

### Rule 2: Escalate Only if Risk Increases
```
Previous notification: HOLD (Medium Risk)
New analysis: HOLD (Medium Risk) → SUPPRESS
New analysis: REDUCE (High Risk) → NOTIFY (escalation)
```

**Escalation Triggers**:
- Risk level increases (Medium → High)
- Decision changes (HOLD → REDUCE)
- New critical information emerges
- Portfolio drawdown threshold exceeded

### Rule 3: Respect User Risk Profile (Aether State)
```
Aether State: HIGH VOLATILITY
User Profile: Conservative
Notification Threshold: Higher (only critical alerts)

Aether State: NORMAL
User Profile: Aggressive
Notification Threshold: Lower (more opportunities)
```

**Example**:
```
Market Regime: HIGH VOLATILITY
User Profile: Conservative
News: "Moderate positive news on AKBNK"

Orchestrator Decision: Suppress notification
Reason: Conservative user in volatile regime should avoid new positions
Action: Log opportunity, do not notify
```

## Output Format

Every orchestrator decision must include:

### 1. Selected Workflow
```
Selected Workflow: Portfolio Mentor Intelligence
Trigger: Scheduled weekly review
Timestamp: 2025-12-22 20:00:00
```

### 2. Reason for Selection
```
Reason: Sunday evening scheduled portfolio health check
Context: No critical news or user questions pending
Priority: MEDIUM
```

### 3. Suppressed Workflows (if any)
```
Suppressed Workflows:
- News Intelligence: No high-scoring news in last 24 hours
- Chat Intelligence: No user questions pending

Active Workflows:
- Portfolio Mentor Intelligence: Running scheduled review
- Decision Output Standard: Formatting output (mandatory)
```

### 4. Final Mentor Decision (Standardized)
```
[Full output following Mentor Decision Output Standard]

Decision: REDUCE (High Confidence)

Why:
• THYAO concentration increased to 28% (threshold: 20%)
• Banking sector at 45% (threshold: 30%)
• Market regime shifted to HIGH VOLATILITY

Action Plan:
• Reduce THYAO from 28% to 15% over 2-3 days
• Trim YKBNK by 70% to reduce banking exposure
• Increase cash position to 15%

Mentor Scenario:
If market stabilizes → re-evaluate trimmed positions → consider re-entry.
If volatility increases → further reduce high-beta positions.

Risk Note:
⚠️ Over-concentration in volatile regime amplifies downside risk.
```

## Decision Flow Diagram

```
User Action / System Trigger
         ↓
    Orchestrator
         ↓
   ┌─────┴─────┐
   ↓           ↓
Check Priority  Check Conflicts
   ↓           ↓
   └─────┬─────┘
         ↓
  Select Workflow(s)
         ↓
   ┌─────┼─────┬─────┐
   ↓     ↓     ↓     ↓
 News  Chat  Portfolio  (all use Decision Standard)
   ↓     ↓     ↓
   └─────┼─────┘
         ↓
  Conflict Resolution
         ↓
  Apply Priority Rules
         ↓
  Check Notification Policy
         ↓
  Format via Decision Standard
         ↓
  Output to User (or suppress)
```

## Implementation Checklist

- [ ] Create `OrchestratorDecision` data model
- [ ] Implement trigger detection (news, chat, schedule, drawdown)
- [ ] Build priority rule engine
- [ ] Add conflict resolution logic
- [ ] Implement notification deduplication (time-based)
- [ ] Add risk escalation detection
- [ ] Integrate Aether state for regime-aware decisions
- [ ] Create workflow selection router
- [ ] Build suppression logic (low confidence, duplicates)
- [ ] Add comprehensive logging (all decisions, conflicts, suppressions)
- [ ] Implement notification cooldown periods
- [ ] Create dashboard for orchestrator decisions (admin view)
- [ ] Add A/B testing framework for rule tuning

## Example Scenarios

### Scenario 1: Conflicting News and Portfolio Signals
```
Input:
- News: "THYAO announces major contract win" (score: 0.85)
- Portfolio: THYAO at 28% concentration

Orchestrator Process:
1. Trigger: Critical news (score ≥ 0.7)
2. Route to: News Intelligence → outputs "BUY (High Confidence)"
3. Check portfolio: Portfolio Mentor flags concentration risk
4. Conflict detected: BUY vs. over-concentration
5. Apply Priority Rule 2: Portfolio risk overrides opportunity
6. Resolution: HOLD

Output:
Decision: HOLD

Why:
• Major contract win is positive for THYAO fundamentals
• However, you already hold 28% in THYAO (threshold: 20%)
• Adding more increases concentration risk

Action Plan:
• Do NOT add to THYAO position
• Maintain current holding to benefit from contract news
• Consider trimming if position grows beyond 30%

Mentor Scenario:
If THYAO rises on contract news → your existing position benefits → no need to add.
If you want more exposure → trim another holding first to make room.

Risk Note:
⚠️ Over-concentration means THYAO problems would severely impact your portfolio.
```

### Scenario 2: Low Confidence Suppression
```
Input:
- News: "Minor positive mention of ASELS" (score: 0.65)
- Confidence: LOW (incomplete data)

Orchestrator Process:
1. Trigger: News below critical threshold (0.65 < 0.7)
2. Route to: News Intelligence → outputs "HOLD (Low Confidence)"
3. Check confidence: Below MEDIUM threshold
4. Apply Priority Rule 4: Suppress notification
5. Resolution: Log internally, do not notify user

Output: [Suppressed]

Internal Log:
{
  "symbol": "ASELS",
  "news_score": 0.65,
  "decision": "HOLD",
  "confidence": "LOW",
  "action": "suppressed",
  "reason": "Below confidence threshold for notification"
}
```

### Scenario 3: User Question During High Volatility
```
Input:
- User: "Should I buy GARAN?"
- Market Regime: HIGH VOLATILITY (Aether)
- Portfolio: Banking sector at 45%

Orchestrator Process:
1. Trigger: User question (immediate priority)
2. Route to: Chat Intelligence
3. Context: Check portfolio → banking overweight
4. Context: Check Aether → high volatility regime
5. Apply Priority Rule 2: Portfolio risk overrides
6. Resolution: AVOID with explanation

Output:
Decision: AVOID (High Confidence)

Why:
• Your banking sector exposure is already 45% (threshold: 30%)
• Market is in HIGH VOLATILITY regime (risky for new positions)
• Adding GARAN increases both sector and volatility risk

Action Plan:
• Do NOT buy GARAN at this time
• Wait for market regime to stabilize
• If you want banking exposure, trim YKBNK and buy GARAN instead (swap, don't add)

Mentor Scenario:
If volatility decreases AND you reduce banking exposure → GARAN could be considered.
If volatility persists → avoid adding any new positions.

Risk Note:
⚠️ Adding to overweight sector in volatile regime is high-risk behavior.
```

## Best Practices

### 1. Always Explain Orchestrator Decisions
Users should understand why they're seeing (or not seeing) certain recommendations.

### 2. Log Everything
Every decision, conflict, and suppression should be logged for:
- System debugging
- Rule optimization
- User behavior analysis
- Compliance/audit trail

### 3. Tune Thresholds Based on User Feedback
- Track notification acceptance rate
- Adjust confidence thresholds
- Refine priority rules
- A/B test conflict resolution strategies

### 4. Respect User Preferences
- Allow users to set notification frequency
- Provide "aggressive" vs. "conservative" modes
- Let users override orchestrator decisions (with warning)

### 5. Fail Gracefully
If orchestrator logic fails:
- Default to HOLD
- Explain the failure transparently
- Log error for debugging
- Never fail silently

## Integration Points

The orchestrator integrates with:
- **Aether**: Market regime detection
- **Portfolio DB**: Current holdings and history
- **News API**: Real-time news scoring
- **User Profile**: Risk tolerance settings
- **Notification Service**: Push notifications
- **Analytics**: Decision tracking and optimization
