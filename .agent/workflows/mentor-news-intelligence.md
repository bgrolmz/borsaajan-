---
description: Context-aware, action-oriented news analysis for Borsa Ajanı
---

# Mentor News Intelligence Workflow

## Purpose
Turn raw news into mentor-style decisions, not summaries. This workflow provides actionable insights based on news analysis without overwhelming users with raw data.

## Triggers
- Hourly news fetch (automated)
- Critical news alert (real-time)
- User opens Hermes tab (on-demand)

## Implementation Steps

### 1. Collect Relevant Symbols
Gather context from multiple sources to ensure comprehensive coverage:
- **Portfolio holdings**: Current positions the user owns
- **Past trades**: Historical trading activity for pattern recognition
- **Recently analyzed symbols**: Symbols the user has shown interest in

### 2. Fetch News in Batch
- Query news API for all collected symbols in a single batch request
- Optimize API usage by grouping requests
- Cache results to avoid redundant calls

### 3. Local Scoring (No LLM)
Implement fast, rule-based scoring to filter news before expensive LLM calls:
- **Relevance score**: How closely the news relates to user's symbols
- **Recency score**: Time-decay function (newer = higher score)
- **Source credibility**: Weight by news source reliability
- **Sentiment indicators**: Basic keyword-based sentiment
- **Volume/price movement correlation**: If available from market data

**Scoring formula example**:
```
score = (relevance * 0.4) + (recency * 0.3) + (credibility * 0.2) + (sentiment_strength * 0.1)
```

### 4. Conditional LLM Analysis
**Only if score >= threshold** (e.g., 0.7):
- Run **ONE** LLM call per high-scoring news item
- Use structured prompt to extract:
  - **Impact assessment**: HIGH/MEDIUM/LOW
  - **Affected symbols**: List with confidence scores
  - **Suggested action**: BUY/SELL/HOLD with reasoning
  - **Time sensitivity**: IMMEDIATE/SHORT_TERM/LONG_TERM

**LLM Prompt Template**:
```
Analyze this news for trading impact:
News: {title} - {summary}
User context: Holds {symbols}, recently traded {recent_symbols}

Provide:
1. Impact: [HIGH/MEDIUM/LOW]
2. Affected symbols: [symbol:confidence, ...]
3. Action: [BUY/SELL/HOLD symbol_name]
4. Reasoning: [one sentence]
5. Urgency: [IMMEDIATE/SHORT_TERM/LONG_TERM]
```

### 5. Smart Notifications
**Send notification ONLY if**:
- Suggested action exists (not HOLD)
- Impact is MEDIUM or HIGH
- User hasn't been notified about similar news in last X hours

**Notification format**:
```
🎯 {Symbol}: {Action}
Impact: {impact_level}
Reason: {one_sentence_reasoning}
[View Details]
```

## Constraints & Rules

### ❌ Never Do This
- **No copy-paste news text**: Always synthesize and contextualize
- **No notification spam**: Batch similar alerts, respect cooldown periods
- **No hallucinations**: If data is missing, explicitly state it

### ✅ Always Do This
- **QUICK mode must never be worse than DEEP mode**: Fast analysis should be conservative, not wrong
- **If data missing → HOLD + explanation**: "Insufficient data to recommend action"
- **Log all decisions**: Track why news was filtered or escalated
- **Provide confidence scores**: Let users know certainty level

## Performance Targets
- Local scoring: < 100ms for 50 news items
- LLM call: < 3s per analysis
- End-to-end (hourly batch): < 30s for typical portfolio

## Error Handling
- **API failure**: Use cached news, notify user of stale data
- **LLM timeout**: Fall back to rule-based suggestion with lower confidence
- **Missing symbol data**: Skip that symbol, log for review

## Future Enhancements
- Multi-news correlation (e.g., 3 negative news about sector → stronger signal)
- User feedback loop (learn from ignored vs. acted-upon suggestions)
- Personalized threshold tuning based on user's risk profile
