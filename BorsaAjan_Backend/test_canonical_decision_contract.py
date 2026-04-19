"""Contract tests for canonical QUICK/DEEP decision layer.

These tests are designed to be:
- network-free
- deterministic
- focused on the divergence guard + override contract

Run:
  python test_canonical_decision_contract.py
"""

import os


def _build_quick_stub():
    return {
        "symbol": "TEST",
        "mode": "quick",
        "as_of": {
            "analysis": "2025-01-01T00:00:00Z",
            "quote": "2025-01-01T00:00:00Z",
            "fundamentals": "2025-01-01T00:00:00Z",
            "news": "2025-01-01T00:00:00Z",
        },
        "decision": "BUY",
        "confidence": 70,
        "horizon_days": 7,
        "why_bullets": ["RSI düşük", "Trend yukarı"],
        "action_plan": [
            {"type": "BUY", "amount_percent_of_position_value": 10, "timeframe": "1-3 gün", "rationale_short": "Kademeli al."},
            {"type": "RECHECK", "timeframe": "24 saat", "rationale_short": "Yeniden değerlendir."},
        ],
        "news_impact": [
            {
                "event_summary": "Major lawsuit filed against company",
                "impact": "bearish",
                "why_it_matters": "Regülatif/itibar riski.",
                "confidence": 90,
            }
        ],
        "glossary_terms": {"RSI": "..."},
        "mentor_scenario": "...",
        "quick_features_hash": "abc",
    }


def test_override_rejected_if_reason_missing_event():
    from borsaajan_backend.canonical_decision import apply_deep_patch_with_guards

    quick = _build_quick_stub()
    patch = {
        "why_bullets": ["Aynı anlam, daha temiz"],
        "action_plan_rationales": ["R1", "R2"],
        "mentor_scenario": "İki cümle. İkinci cümle.",
        "override": {
            "override_applied": True,
            "decision": "AVOID",
            "override_reason": "Kritik haber var ama başlık referansı yok",
            "override_confidence": 80,
            "data_change_timestamp": "2025-01-01T00:00:00Z",
        },
    }

    deep = apply_deep_patch_with_guards(quick_json=quick, patch=patch)
    assert deep["decision"] == "BUY", "Override must be rejected without concrete event reference"
    assert deep.get("override") is None, "Rejected override must not be attached"


def test_override_applied_if_valid():
    from borsaajan_backend.canonical_decision import apply_deep_patch_with_guards

    quick = _build_quick_stub()
    patch = {
        "why_bullets": ["Aynı anlam, daha temiz"],
        "action_plan_rationales": ["R1", "R2"],
        "mentor_scenario": "İki cümle. İkinci cümle.",
        "override": {
            "override_applied": True,
            "decision": "AVOID",
            "override_reason": "Major lawsuit filed against company nedeniyle risk çok yüksek",
            "override_confidence": 80,
            "data_change_timestamp": "2025-01-01T00:00:00Z",
        },
    }

    deep = apply_deep_patch_with_guards(quick_json=quick, patch=patch)
    assert deep["decision"] == "AVOID", "Valid override should be applied"
    assert deep.get("override", {}).get("override_applied") is True
    assert deep.get("override", {}).get("data_change_hash")


def test_lengths_capped_by_model():
    from borsaajan_backend.canonical_decision import CanonicalDecisionResponse

    quick = _build_quick_stub()
    quick["why_bullets"] = ["1", "2", "3", "4"]
    quick["news_impact"] = quick["news_impact"] * 5
    quick["action_plan"] = quick["action_plan"] * 5

    parsed = CanonicalDecisionResponse.model_validate(quick)
    assert len(parsed.why_bullets) <= 3
    assert len(parsed.news_impact) <= 3
    assert len(parsed.action_plan) <= 4


if __name__ == "__main__":
    tests = [
        ("override_rejected_if_reason_missing_event", test_override_rejected_if_reason_missing_event),
        ("override_applied_if_valid", test_override_applied_if_valid),
        ("lengths_capped_by_model", test_lengths_capped_by_model),
    ]

    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as e:
            failed += 1
            print(f"FAIL {name}: {type(e).__name__}: {e}")

    raise SystemExit(1 if failed else 0)
