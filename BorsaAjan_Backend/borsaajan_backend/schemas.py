"""
JSON Schema definitions for Gemini structured output.

These schemas ensure UI contract compliance and prevent invalid JSON responses.
Gemini-compatible: Only type, properties, required, items. No validation rules (maxLength, enum, min/max, etc.).
Validation is handled in backend logic.
"""

from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

# ============================================================================
# MASTER ANALYSIS SCHEMA - Minimal Gemini Compatible (type + properties + required + items only)
# ============================================================================

# ============================================================================
# NEW COMPACT ANALYSIS SCHEMA - Optimized for token efficiency
# ============================================================================

NEW_ANALYSIS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline_tr": {"type": "string"},
        "verdict": {"type": "string"},
        "confidence": {"type": "integer"},
        "thesis_bullets": {
            "type": "array",
            "items": {"type": "string"}
        },
        "risk_bullets": {
            "type": "array",
            "items": {"type": "string"}
        },
        "levels": {
            "type": "object",
            "properties": {
                "entry_zone": {"type": "string"},
                "stop_loss": {"type": "string"},
                "take_profit_1": {"type": "string"},
                "take_profit_2": {"type": "string"}
            },
            "required": ["entry_zone", "stop_loss", "take_profit_1", "take_profit_2"]
        },
        "scenarios": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "trigger": {"type": "string"},
                    "expected_move": {"type": "string"},
                    "timeframe": {"type": "string"}
                },
                "required": ["type", "trigger", "expected_move", "timeframe"]
            }
        },
        "news_summary": {"type": "string"},
        "what_to_watch": {
            "type": "array",
            "items": {"type": "string"}
        }
    },
    "required": [
        "headline_tr", "verdict", "confidence", "thesis_bullets", "risk_bullets",
        "levels", "scenarios", "news_summary", "what_to_watch"
    ]
}

MASTER_ANALYSIS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "symbol": {
            "type": "string"
        },
        "mode": {
            "type": "string"
        },
        "as_of": {
            "type": "string"
        },
        "price_at_analysis": {
            "type": "number"
        },
        "summary": {
            "type": "object",
            "properties": {
                "headline_tr": {
                    "type": "string"
                },
                "one_liner_tr": {
                    "type": "string"
                },
                "key_points_tr": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    }
                }
            },
            "required": ["headline_tr", "one_liner_tr", "key_points_tr"]
        },
        "technical_analysis": {
            "type": "object",
            "properties": {
                "trend": {
                    "type": "string"
                },
                "support_levels": {
                    "type": "array",
                    "items": {"type": "number"}
                },
                "resistance_levels": {
                    "type": "array",
                    "items": {"type": "number"}
                },
                "indicators": {
                    "type": "object",
                    "properties": {
                        "rsi": {
                            "type": "object",
                            "properties": {
                                "value": {"type": "number"},
                                "interpretation_tr": {"type": "string"}
                            },
                            "required": ["value", "interpretation_tr"]
                        },
                        "macd": {
                            "type": "object",
                            "properties": {
                                "signal": {
                                    "type": "string"
                                },
                                "interpretation_tr": {"type": "string"}
                            },
                            "required": ["signal", "interpretation_tr"]
                        },
                        "bbands": {
                            "type": "object",
                            "properties": {
                                "position": {
                                    "type": "string"
                                },
                                "interpretation_tr": {"type": "string"}
                            },
                            "required": ["position", "interpretation_tr"]
                        }
                    },
                    "required": ["rsi", "macd", "bbands"]
                },
                "notes_tr": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            },
            "required": ["trend", "support_levels", "resistance_levels", "indicators", "notes_tr"]
        },
        "fundamental_analysis": {
            "type": "object",
            "properties": {
                "valuation": {
                    "type": "object",
                    "properties": {
                        "view": {
                            "type": "string"
                        },
                        "reason_tr": {
                            "type": "string"
                        }
                    },
                    "required": ["view", "reason_tr"]
                },
                "growth": {
                    "type": "object",
                    "properties": {
                        "view": {
                            "type": "string"
                        },
                        "reason_tr": {
                            "type": "string"
                        }
                    },
                    "required": ["view", "reason_tr"]
                },
                "profitability": {
                    "type": "object",
                    "properties": {
                        "view": {
                            "type": "string"
                        },
                        "reason_tr": {
                            "type": "string"
                        }
                    },
                    "required": ["view", "reason_tr"]
                },
                "risks_tr": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            },
            "required": ["valuation", "growth", "profitability", "risks_tr"]
        },
        "sentiment_and_catalysts": {
            "type": "object",
            "properties": {
                "sentiment": {
                    "type": "string"
                },
                "drivers_tr": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "catalysts_tr": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "news_impact_tr": {
                    "type": "string"
                }
            },
            "required": ["sentiment", "drivers_tr", "catalysts_tr", "news_impact_tr"]
        },
        "scenarios": {
            "type": "object",
            "properties": {
                "bull_case_tr": {
                    "type": "object",
                    "properties": {
                        "thesis": {"type": "string"},
                        "triggers": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "price_path": {"type": "string"}
                    },
                    "required": ["thesis", "triggers", "price_path"]
                },
                "bear_case_tr": {
                    "type": "object",
                    "properties": {
                        "thesis": {"type": "string"},
                        "triggers": {
                            "type": "array",
                            "items": {"type": "string"}
                        },
                        "price_path": {"type": "string"}
                    },
                    "required": ["thesis", "triggers", "price_path"]
                }
            },
            "required": ["bull_case_tr", "bear_case_tr"]
        },
        "strategy": {
            "type": "object",
            "properties": {
                "stance": {
                    "type": "string"
                },
                "entry_plan_tr": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "risk_management_tr": {
                    "type": "object",
                    "properties": {
                        "stop_loss": {"type": "number"},
                        "take_profit": {
                            "type": "array",
                            "items": {"type": "number"}
                        },
                        "position_sizing_tr": {
                            "type": "string"
                        }
                    },
                    "required": ["stop_loss", "take_profit", "position_sizing_tr"]
                },
                "time_horizon": {
                    "type": "string"
                }
            },
            "required": ["stance", "entry_plan_tr", "risk_management_tr", "time_horizon"]
        },
        "risk_score": {
            "type": "object",
            "properties": {
                "value": {
                    "type": "integer"
                },
                "label": {
                    "type": "string"
                },
                "reasons_tr": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            },
            "required": ["value", "label", "reasons_tr"]
        },
        "confidence_score": {
            "type": "object",
            "properties": {
                "value": {
                    "type": "integer"
                },
                "reasons_tr": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            },
            "required": ["value", "reasons_tr"]
        },
        "data_quality_flags": {
            "type": "array",
            "items": {
                "type": "string"
            }
        }
    },
    "required": [
        "symbol",
        "mode",
        "as_of",
        "price_at_analysis",
        "summary",
        "technical_analysis",
        "fundamental_analysis",
        "sentiment_and_catalysts",
        "scenarios",
        "strategy",
        "risk_score",
        "confidence_score",
        "data_quality_flags"
    ]
}

# ============================================================================
# PORTFOLIO DEEP ANALYSIS SCHEMA - Gemini Compatible (type + properties + required + items only)
# ============================================================================

PORTFOLIO_DEEP_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "success": {"type": "boolean"},
        "mode": {"type": "string"},
        "as_of": {"type": "string"},
        "portfolio_summary_tr": {"type": "string"},
        "top_actions_tr": {
            "type": "array",
            "items": {"type": "string"}
        },
        "risk_reduction_plan_tr": {
            "type": "array",
            "items": {"type": "string"}
        },
        "catalyst_summary_tr": {
            "type": "array",
            "items": {"type": "string"}
        },
        "watchlist_tr": {
            "type": "array",
            "items": {"type": "string"}
        },
        "risk_score": {"type": "integer"},
        "confidence_score": {"type": "integer"},
        "data_quality_flags": {
            "type": "array",
            "items": {"type": "string"}
        },
        "llm_used": {"type": "integer"},
        "cache_hit": {"type": "integer"}
    },
    "required": [
        "success",
        "mode",
        "as_of",
        "portfolio_summary_tr",
        "top_actions_tr",
        "risk_reduction_plan_tr",
        "catalyst_summary_tr",
        "watchlist_tr",
        "risk_score",
        "confidence_score",
        "data_quality_flags",
        "llm_used",
        "cache_hit"
    ]
}

# ============================================================================
# CANONICAL DECISION SCHEMA (QUICK + DEEP) - Gemini Compatible
# Only type/properties/required/items (no enum/min/max/maxItems)
# ============================================================================

CANONICAL_DECISION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "symbol": {"type": "string"},
        "mode": {"type": "string"},
        "as_of": {
            "type": "object",
            "properties": {
                "analysis": {"type": "string"},
                "quote": {"type": "string"},
                "fundamentals": {"type": "string"},
                "news": {"type": "string"},
                "ohlc": {"type": "string"},
            },
            "required": ["analysis", "quote", "fundamentals", "news"],
        },
        "decision": {"type": "string"},
        "confidence": {"type": "integer"},
        "horizon_days": {"type": "integer"},
        "why_bullets": {"type": "array", "items": {"type": "string"}},
        "action_plan": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "amount_percent_of_position_value": {"type": "integer"},
                    "price_level": {"type": "number"},
                    "timeframe": {"type": "string"},
                    "rationale_short": {"type": "string"},
                },
                "required": ["type", "rationale_short"],
            },
        },
        "news_impact": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "event_summary": {"type": "string"},
                    "impact": {"type": "string"},
                    "why_it_matters": {"type": "string"},
                    "confidence": {"type": "integer"},
                },
                "required": ["event_summary", "impact", "why_it_matters", "confidence"],
            },
        },
        "glossary_terms": {
            "type": "object",
            "properties": {},
        },
        "mentor_scenario": {"type": "string"},
        "evidence": {"type": "object", "properties": {}},
        "quick_features_hash": {"type": "string"},
        "deep_failed_reason": {"type": "string"},
        "override": {
            "type": "object",
            "properties": {
                "override_applied": {"type": "boolean"},
                "override_reason": {"type": "string"},
                "override_confidence": {"type": "integer"},
                "data_change_hash": {"type": "string"},
                "data_change_timestamp": {"type": "string"},
            },
            "required": [
                "override_applied",
                "override_reason",
                "override_confidence",
                "data_change_hash",
                "data_change_timestamp",
            ],
        },
    },
    "required": [
        "symbol",
        "mode",
        "as_of",
        "decision",
        "confidence",
        "horizon_days",
        "why_bullets",
        "action_plan",
        "news_impact",
        "glossary_terms",
    ],
}

# ============================================================================
# DEEP NARRATIVE PATCH SCHEMA - Gemini Compatible
# Restrict LLM output to wording/narrative fields (+ rare override suggestion)
# ============================================================================

DEEP_NARRATIVE_PATCH_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "why_bullets": {"type": "array", "items": {"type": "string"}},
        "action_plan_rationales": {"type": "array", "items": {"type": "string"}},
        "mentor_scenario": {"type": "string"},
        "override": {
            "type": "object",
            "properties": {
                "override_applied": {"type": "boolean"},
                "decision": {"type": "string"},
                "override_reason": {"type": "string"},
                "override_confidence": {"type": "integer"},
                "data_change_timestamp": {"type": "string"},
            },
            "required": [
                "override_applied",
                "decision",
                "override_reason",
                "override_confidence",
                "data_change_timestamp",
            ],
        },
    },
    "required": ["why_bullets", "action_plan_rationales", "mentor_scenario"],
}

# ============================================================================
# PYDANTIC MODELS FOR API VALIDATION
# ============================================================================

class MentorNewsCard(BaseModel):
    """Pydantic model for MentorNewsCard API response."""
    symbol: str = Field(..., description="Stock/crypto symbol (normalized)")
    mentor_summary: str = Field(..., max_length=300, description="Backend-generated interpretation (Turkish)")
    expected_impact: str = Field(..., description="POSITIVE, NEGATIVE, or NEUTRAL")
    action_hint: str = Field(..., description="BUY, SELL, HOLD, MONITOR, CONSIDER_BUY, CONSIDER_SELL, SET_STOP_LOSS, or HOLD_STRONG")
    confidence: int = Field(..., ge=0, le=100, description="Confidence score 0-100")
    time_horizon: str = Field(..., description="intraday, short, or long")
    timestamp: str = Field(..., description="ISO 8601 UTC timestamp")
    source: Optional[str] = Field(None, description="News source name (optional)")

    class Config:
        json_schema_extra = {
            "example": {
                "symbol": "AAPL",
                "mentor_summary": "Kazanç beklentileri aşıldı. Servis segmentinde güçlü büyüme.",
                "expected_impact": "POSITIVE",
                "action_hint": "CONSIDER_BUY",
                "confidence": 75,
                "time_horizon": "short",
                "timestamp": "2025-01-15T10:30:00Z",
                "source": "Reuters"
            }
        }
