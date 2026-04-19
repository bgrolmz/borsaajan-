"""
Test script for HYBRID chat implementation.
Tests both deterministic and LLM-customized responses.
"""

import requests
import json

BASE_URL = "http://localhost:8000"

def test_chat(user_message, symbol="NVDA"):
    """Send a chat request and print the response."""
    payload = {
        "user_message": user_message,
        "context_data": {
            "type": "stock",
            "symbol": symbol
        }
    }
    
    print(f"\n{'='*80}")
    print(f"TEST: user_message = '{user_message}'")
    print(f"{'='*80}")
    
    try:
        response = requests.post(f"{BASE_URL}/chat", json=payload, timeout=15)
        response.raise_for_status()
        
        result = response.json()
        
        # Print key fields
        print(f"\n✅ SUCCESS")
        print(f"Decision: {result.get('decision')}")
        print(f"Confidence: {result.get('confidence')}")
        print(f"Flags:")
        flags = result.get('flags', {})
        print(f"  - used_llm: {flags.get('used_llm')}")
        print(f"  - missing_data: {flags.get('missing_data')}")
        print(f"  - fallback_mode: {flags.get('fallback_mode')}")
        
        print(f"\nWhy Bullets ({len(result.get('why_bullets', []))}):")
        for i, bullet in enumerate(result.get('why_bullets', [])[:3], 1):
            print(f"  {i}. {bullet}")
        
        print(f"\nAction Plan ({len(result.get('action_plan', []))}):")
        for i, action in enumerate(result.get('action_plan', [])[:3], 1):
            print(f"  {i}. {action.get('type')}: {action.get('rationale_short', '')}")
        
        print(f"\nMentor Scenario:")
        print(f"  {result.get('mentor_scenario', '')[:150]}...")
        
        print(f"\nResponse Text (first 300 chars):")
        print(f"  {result.get('response', '')[:300]}...")
        
        return result
        
    except requests.exceptions.Timeout:
        print(f"\n❌ TIMEOUT: Request took longer than 15 seconds")
        return None
    except requests.exceptions.RequestException as e:
        print(f"\n❌ ERROR: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"\n❌ JSON DECODE ERROR: {e}")
        print(f"Response text: {response.text[:500]}")
        return None


def main():
    """Run all tests."""
    print("="*80)
    print("HYBRID CHAT IMPLEMENTATION TEST SUITE")
    print("="*80)
    
    # Test 1: Short/test message → should_use_llm = False
    print("\n\n" + "="*80)
    print("TEST 1: Short/test message (should NOT use LLM)")
    print("="*80)
    test_chat("test", "NVDA")
    
    # Test 2: Mentor keyword question → should_use_llm = True
    print("\n\n" + "="*80)
    print("TEST 2: Mentor keyword question (SHOULD use LLM)")
    print("="*80)
    test_chat("NVDA neden AVOID?", "NVDA")
    
    # Test 3: Question mark → should_use_llm = True
    print("\n\n" + "="*80)
    print("TEST 3: Question with ? (SHOULD use LLM)")
    print("="*80)
    test_chat("Should I buy NVDA?", "NVDA")
    
    # Test 4: Risk keyword → should_use_llm = True
    print("\n\n" + "="*80)
    print("TEST 4: Risk keyword (SHOULD use LLM)")
    print("="*80)
    test_chat("NVDA risk nedir?", "NVDA")
    
    # Test 5: Different symbol
    print("\n\n" + "="*80)
    print("TEST 5: Different symbol (TSLA)")
    print("="*80)
    test_chat("TSLA nasıl?", "TSLA")
    
    print("\n\n" + "="*80)
    print("ALL TESTS COMPLETE")
    print("="*80)
    print("\nExpected Results:")
    print("  - Test 1: used_llm = False (short message)")
    print("  - Test 2-5: used_llm = True (mentor keywords/questions)")
    print("  - All tests: decision should be from canonical (never changed by LLM)")
    print("  - All tests: no null fields (arrays default to [])")


if __name__ == "__main__":
    main()
