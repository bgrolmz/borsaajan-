"""borsaajan_backend.canonical_decision

Canonical decision schema shared by QUICK and DEEP.

ROOT RULE:
- QUICK is the deterministic decision engine.
- DEEP only enriches wording/narrative and must not contradict QUICK numbers.

This module provides strict typing via Pydantic models.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

import hashlib
from datetime import datetime, timezone

from pydantic import BaseModel, Field, conint, model_validator


Decision = Literal["BUY", "HOLD", "REDUCE", "AVOID"]
ActionType = Literal["BUY", "SELL", "WAIT", "SET_SL", "SET_TP", "NO_ACTION", "RECHECK"]
Impact = Literal["bullish", "bearish", "neutral"]


class DataFreshness(BaseModel):
    analysis: str
    quote: str
    fundamentals: str
    news: str
    # Optional: some callers track chart bars separately
    ohlc: Optional[str] = None


class ActionPlanItem(BaseModel):
    type: ActionType
    amount_percent_of_position_value: Optional[conint(ge=0, le=100)] = None
    price_level: Optional[float] = None
    timeframe: Optional[str] = None
    rationale_short: str


class NewsImpactItem(BaseModel):
    event_summary: str
    impact: Impact
    why_it_matters: str
    confidence: conint(ge=0, le=100)


class OverrideContract(BaseModel):
    override_applied: bool
    override_reason: str
    override_confidence: conint(ge=0, le=100)
    data_change_hash: str
    data_change_timestamp: str


class CanonicalDecisionResponse(BaseModel):
    # Identity / freshness
    symbol: str
    mode: Literal["quick", "deep"]
    as_of: DataFreshness

    # Deterministic decision core
    decision: Decision
    confidence: conint(ge=0, le=100)
    horizon_days: conint(ge=1, le=365)

    # Human-facing fields
    why_bullets: List[str] = Field(default_factory=list)
    action_plan: List[ActionPlanItem] = Field(default_factory=list)
    news_impact: List[NewsImpactItem] = Field(default_factory=list)
    glossary_terms: Dict[str, str] = Field(default_factory=dict)

    # DEEP-only enrichment (still in canonical response shape)
    mentor_scenario: Optional[str] = None

    # Optional: UI drawer payload
    evidence: Optional[Dict[str, Any]] = None

    # Optional: Quick features hash for caching / tracing
    quick_features_hash: Optional[str] = None

    # Optional: Override contract (rare)
    override: Optional[OverrideContract] = None

    # Optional: DEEP guardrails (when /analysis/deep falls back to QUICK)
    deep_failed_reason: Optional[str] = None

    @model_validator(mode="after")
    def _validate_lengths(self) -> "CanonicalDecisionResponse":
        if self.why_bullets and len(self.why_bullets) > 3:
            self.why_bullets = self.why_bullets[:3]
        if self.action_plan and len(self.action_plan) > 4:
            self.action_plan = self.action_plan[:4]
        if self.news_impact and len(self.news_impact) > 3:
            self.news_impact = self.news_impact[:3]
        return self


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def apply_deep_patch_with_guards(quick_json: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    """
    Merge DEEP narrative patch into QUICK canonical output, enforcing:
    - divergence guard (DEEP decision cannot differ from QUICK without a validated override)
    - override contract validation (must reference a concrete critical news event)
    """
    deep = dict(quick_json)
    deep["mode"] = "deep"

    quick_decision = quick_json.get("decision")

    # Wording only
    why_bullets = patch.get("why_bullets") if isinstance(patch, dict) else None
    if isinstance(why_bullets, list) and why_bullets:
        deep["why_bullets"] = [str(x) for x in why_bullets][:3]

    rationales = patch.get("action_plan_rationales") if isinstance(patch, dict) else None
    if isinstance(rationales, list) and isinstance(deep.get("action_plan"), list):
        for i, item in enumerate(deep["action_plan"]):
            if i < len(rationales) and isinstance(item, dict):
                item["rationale_short"] = str(rationales[i])[:220]

    mentor_scenario = patch.get("mentor_scenario") if isinstance(patch, dict) else None
    if isinstance(mentor_scenario, str) and mentor_scenario.strip():
        deep["mentor_scenario"] = mentor_scenario.strip()

    # OVERRIDE contract (rare)
    override = patch.get("override") if isinstance(patch, dict) else None
    if isinstance(override, dict) and override.get("override_applied") is True:
        proposed = str(override.get("decision") or "").upper()
        proposed_reason = str(override.get("override_reason") or "").strip()
        proposed_conf = override.get("override_confidence")
        proposed_ts = str(override.get("data_change_timestamp") or "").strip() or _iso_utc_now()

        news_events = [
            str(n.get("event_summary", ""))
            for n in (quick_json.get("news_impact") or [])
            if isinstance(n, dict)
        ]
        reason_has_event = any(ev and ev.lower() in proposed_reason.lower() for ev in news_events)
        has_critical_news = any(
            isinstance(n, dict)
            and int(n.get("confidence", 0) or 0) >= 80
            and n.get("impact") in ["bullish", "bearish"]
            for n in (quick_json.get("news_impact") or [])
        )
        conf_ok = isinstance(proposed_conf, (int, float)) and int(proposed_conf) >= 60

        if (
            proposed in ["BUY", "HOLD", "REDUCE", "AVOID"]
            and proposed != quick_decision
            and proposed_reason
            and reason_has_event
            and has_critical_news
            and conf_ok
        ):
            deep["decision"] = proposed
            deep["override"] = {
                "override_applied": True,
                "override_reason": proposed_reason,
                "override_confidence": int(proposed_conf),
                "data_change_hash": hashlib.sha256("|".join(news_events).encode("utf-8")).hexdigest(),
                "data_change_timestamp": proposed_ts,
            }

    # Divergence guard
    deep_decision = deep.get("decision")
    override_applied = bool(isinstance(deep.get("override"), dict) and deep["override"].get("override_applied") is True)
    if deep_decision != quick_decision and not override_applied:
        deep["decision"] = quick_decision
        deep.pop("override", None)

    return deep
