# UI Redesign Summary - Mentor-First Output

## Overview
Redesigned UI components to focus on mentor-first output, removing repetitive proof tables and emphasizing decision, actions, and guidance.

## Changes Made

### 1. Redesigned MentorDecisionCard Component
**File**: `BorsaAjani_Web/Components/MentorDecisionCard.razor`

**New Layout** (in order):
1. **Decision + Confidence** (prominent header)
   - Large decision badge (BUY/HOLD/REDUCE/AVOID)
   - Confidence percentage
   - Time horizon

2. **Why** (2-3 bullets)
   - Clean bullet list
   - Glossary tooltips on technical terms
   - Hover effects

3. **Actions** (max 3-4)
   - Action cards with:
     - Action type badge (BUY/SELL/WAIT/SET_SL/SET_TP)
     - Position percentage (% of portfolio)
     - Price levels (stop-loss, take-profit)
     - Timeframe
     - Rationale

4. **Scenario**
   - Mentor scenario text
   - Glossary tooltips

5. **Risk Note**
   - Risk warning with left border accent
   - Glossary tooltips

### 2. Removed Repetitive Tables
**File**: `BorsaAjani_Web/Components/Pages/Home.razor`

- Removed "Technical Summary Table" section
- Technical information now integrated into mentor decision card via glossary tooltips
- Removed duplicate evidence tables

### 3. Added Loading Skeleton
**File**: `BorsaAjani_Web/Components/MentorDecisionCard.razor`

- Skeleton loading state with shimmer animation
- Shows placeholder structure while data loads
- Smooth fade-in when data arrives

### 4. Added Animations
- **Fade-in**: Cards fade in with slight upward motion
- **Hover effects**: Decision badge scales on hover
- **Section hover**: Sections highlight on hover
- **Skeleton shimmer**: Loading skeleton has shimmer effect

### 5. Glossary Tooltips
- Technical terms automatically detected from `glossary_terms` dictionary
- Hover/click shows tooltip with definition
- Terms highlighted with dotted underline
- Color changes on hover

## Canonical Response Schema Mapping

The component maps to the canonical response schema:

```json
{
  "decision": "BUY|HOLD|REDUCE|AVOID",
  "confidence": 0-100,
  "horizon_days": 7,
  "why_bullets": ["bullet1", "bullet2", "bullet3"],
  "action_plan": [
    {
      "type": "BUY|SELL|WAIT|SET_SL|SET_TP|NO_ACTION",
      "amount_percent_of_position_value": 10,
      "price_level": 150.25,
      "timeframe": "24 saat",
      "rationale_short": "Action explanation"
    }
  ],
  "mentor_scenario": "If X happens → expect Y → do Z",
  "risk_note": "Risk warning text",
  "glossary_terms": {
    "RSI": "Relative Strength Index - momentum indicator",
    "Stop-Loss": "Exit level to cap losses"
  }
}
```

## Component Features

### Decision Badge
- Color-coded by decision type
- Large, prominent display
- Confidence percentage inline
- Responsive design

### Action Cards
- Grid layout (responsive)
- Action type badges with color coding
- Position percentage display
- Price levels for stop-loss/take-profit
- Timeframe information
- Rationale text

### Glossary Tooltips
- Automatic detection of technical terms
- Hover/click to show definition
- Visual indicators (dotted underline)
- Smooth interactions

### Loading State
- Skeleton structure matches final layout
- Shimmer animation
- Smooth transition to content

## Responsive Design

- Mobile-friendly layout
- Stacked sections on small screens
- Full-width decision badge on mobile
- Single-column action cards on mobile

## Accessibility

- Semantic HTML structure
- ARIA labels for interactive elements
- Keyboard navigation support
- High contrast colors
- Tooltip accessibility

## Build Verification

- ✅ Dotnet build passes
- ✅ No duplicate cards
- ✅ No repetitive tables
- ✅ Clean component structure
- ✅ Proper error handling

## Next Steps

1. Test with real API responses
2. Verify glossary tooltip functionality
3. Test loading states
4. Verify responsive design on mobile
5. Add unit tests for component rendering
