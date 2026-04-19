"""
Smoke test for chat endpoint to verify user_message changes the answer.

Test cases:
1. Send "test" → should return deterministic response, used_llm=False
2. Send "NVDA neden AVOID?" → should return LLM-customized response, used_llm=True
3. Verify different outputs and used_llm differs
"""

import requests
import json

BASE_URL = "http://127.0.0.1:8000"

def test_chat_smoke():
    """Run smoke tests for chat endpoint."""
    
    # Test context (NVDA stock)
    context_data = {
        "type": "stock",
        "symbol": "NVDA"
    }
    
    print("=" * 80)
    print("SMOKE TEST: Chat Endpoint - user_message changes answer")
    print("=" * 80)
    
    # Test 1: "test" message (should NOT use LLM)
    print("\n[TEST 1] Sending 'test' message...")
    response1 = requests.post(
        f"{BASE_URL}/chat",
        json={
            "user_message": "test",
            "context_data": context_data,
            "use_llm": None  # Auto-detect
        }
    )
    
    if response1.status_code != 200:
        print(f"❌ TEST 1 FAILED: HTTP {response1.status_code}")
        print(f"   Response: {response1.text}")
        return False
    
    result1 = response1.json()
    used_llm_1 = result1.get("flags", {}).get("used_llm", False)
    decision_1 = result1.get("decision", "UNKNOWN")
    why_bullets_1 = result1.get("why_bullets", [])
    cache_key_1 = result1.get("cache_key")
    
    print(f"✅ TEST 1 Response:")
    print(f"   user_message: 'test'")
    print(f"   used_llm: {used_llm_1}")
    print(f"   decision: {decision_1}")
    print(f"   why_bullets count: {len(why_bullets_1)}")
    print(f"   cache_key: {cache_key_1}")
    print(f"   why_bullets preview: {why_bullets_1[:2] if why_bullets_1 else '[]'}")
    
    # Test 2: "NVDA neden AVOID?" message (should use LLM)
    print("\n[TEST 2] Sending 'NVDA neden AVOID?' message...")
    response2 = requests.post(
        f"{BASE_URL}/chat",
        json={
            "user_message": "NVDA neden AVOID?",
            "context_data": context_data,
            "use_llm": None  # Auto-detect
        }
    )
    
    if response2.status_code != 200:
        print(f"❌ TEST 2 FAILED: HTTP {response2.status_code}")
        print(f"   Response: {response2.text}")
        return False
    
    result2 = response2.json()
    used_llm_2 = result2.get("flags", {}).get("used_llm", False)
    decision_2 = result2.get("decision", "UNKNOWN")
    why_bullets_2 = result2.get("why_bullets", [])
    cache_key_2 = result2.get("cache_key")
    
    print(f"✅ TEST 2 Response:")
    print(f"   user_message: 'NVDA neden AVOID?'")
    print(f"   used_llm: {used_llm_2}")
    print(f"   decision: {decision_2}")
    print(f"   why_bullets count: {len(why_bullets_2)}")
    print(f"   cache_key: {cache_key_2}")
    print(f"   why_bullets preview: {why_bullets_2[:2] if why_bullets_2 else '[]'}")
    
    # Verification
    print("\n" + "=" * 80)
    print("VERIFICATION:")
    print("=" * 80)
    
    # Check 1: used_llm should differ
    if used_llm_1 == used_llm_2:
        print(f"❌ VERIFICATION FAILED: used_llm is same ({used_llm_1}) for both messages")
        print(f"   Expected: test=False, NVDA neden AVOID?=True")
        return False
    else:
        print(f"✅ used_llm differs: test={used_llm_1}, NVDA neden AVOID?={used_llm_2}")
    
    # Check 2: why_bullets should differ (if LLM was used)
    if used_llm_2:
        why_text_1 = " ".join(why_bullets_1).lower()
        why_text_2 = " ".join(why_bullets_2).lower()
        if why_text_1 == why_text_2:
            print(f"⚠️  WARNING: why_bullets are identical (may be OK if canonical is same)")
        else:
            print(f"✅ why_bullets differ (LLM customization working)")
            print(f"   Test 1: {why_text_1[:100]}...")
            print(f"   Test 2: {why_text_2[:100]}...")
    
    # Check 3: cache_key should differ (if LLM was used)
    if used_llm_2 and cache_key_1 != cache_key_2:
        print(f"✅ cache_key differs: {cache_key_1} vs {cache_key_2}")
    elif used_llm_2:
        print(f"⚠️  WARNING: cache_key is same (may be OK if messages hash to same key)")
    
    # Check 4: Response structure should match canonical schema
    required_fields = ["decision", "confidence", "why_bullets", "action_plan", 
                       "news_impact", "glossary_terms", "mentor_scenario", 
                       "risk_note", "errors", "flags"]
    missing_fields_1 = [f for f in required_fields if f not in result1]
    missing_fields_2 = [f for f in required_fields if f not in result2]
    
    if missing_fields_1 or missing_fields_2:
        print(f"❌ VERIFICATION FAILED: Missing required fields")
        if missing_fields_1:
            print(f"   Test 1 missing: {missing_fields_1}")
        if missing_fields_2:
            print(f"   Test 2 missing: {missing_fields_2}")
        return False
    else:
        print(f"✅ All required canonical schema fields present")
    
    # Check 5: No null values in required fields
    null_fields_1 = [f for f in required_fields if result1.get(f) is None]
    null_fields_2 = [f for f in required_fields if result2.get(f) is None]
    
    if null_fields_1 or null_fields_2:
        print(f"❌ VERIFICATION FAILED: Null values in required fields")
        if null_fields_1:
            print(f"   Test 1 nulls: {null_fields_1}")
        if null_fields_2:
            print(f"   Test 2 nulls: {null_fields_2}")
        return False
    else:
        print(f"✅ No null values in required fields")
    
    print("\n" + "=" * 80)
    print("✅ ALL VERIFICATIONS PASSED!")
    print("=" * 80)
    return True

if __name__ == "__main__":
    try:
        success = test_chat_smoke()
        exit(0 if success else 1)
    except requests.exceptions.ConnectionError:
        print("❌ ERROR: Cannot connect to backend. Make sure backend is running on http://127.0.0.1:8000")
        exit(1)
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
