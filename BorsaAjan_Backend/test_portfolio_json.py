"""
Test portfolio analysis JSON serialization.

Ensures analyze_portfolio() returns JSON-safe types that can be serialized
without errors (no numpy.bool_, numpy.int64, numpy.float64, etc.).
"""

import json
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from borsaajan_backend.logic import analyze_portfolio


def test_portfolio_quick_mode_json_serializable():
    """Test that quick mode returns JSON-serializable response."""
    print("=" * 60)
    print("Testing Portfolio Analysis JSON Serialization")
    print("=" * 60)
    
    # Create a minimal test portfolio
    test_portfolio = [
        {"symbol": "AAPL", "avg_cost": 150.0, "quantity": 10},
        {"symbol": "MSFT", "avg_cost": 300.0, "quantity": 5}
    ]
    
    print("\n1. Testing analyze_portfolio() in QUICK mode (use_llm=False)...")
    try:
        result = analyze_portfolio(test_portfolio, use_llm=False, force=False)
        
        print(f"   ✅ Function returned successfully")
        print(f"   ✅ Result keys: {list(result.keys())}")
        print(f"   ✅ Mode: {result.get('mode', 'N/A')}")
        print(f"   ✅ Success: {result.get('success', 'N/A')}")
        
        # Test JSON serialization
        print("\n2. Testing JSON serialization with json.dumps()...")
        try:
            json_str = json.dumps(result, ensure_ascii=False, indent=2)
            print(f"   ✅ json.dumps() succeeded")
            print(f"   ✅ JSON length: {len(json_str)} characters")
            
            # Verify we can parse it back
            parsed = json.loads(json_str)
            print(f"   ✅ json.loads() succeeded - roundtrip OK")
            
            return True
            
        except TypeError as e:
            print(f"   ❌ JSON serialization FAILED: {e}")
            print(f"   ❌ Error type: {type(e).__name__}")
            return False
        except ValueError as e:
            print(f"   ❌ JSON serialization FAILED: {e}")
            print(f"   ❌ Error type: {type(e).__name__}")
            return False
            
    except Exception as e:
        print(f"   ❌ analyze_portfolio() raised exception: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_empty_portfolio():
    """Test empty portfolio handling."""
    print("\n3. Testing empty portfolio handling...")
    try:
        result = analyze_portfolio([], use_llm=False, force=False)
        
        # Should return error response
        assert result.get("success") == False
        assert "message" in result
        
        # Should be JSON-serializable
        json_str = json.dumps(result)
        print(f"   ✅ Empty portfolio handled correctly and is JSON-serializable")
        return True
        
    except Exception as e:
        print(f"   ❌ Empty portfolio test FAILED: {e}")
        return False


def test_portfolio_with_numpy_types():
    """Test that result contains no numpy types."""
    print("\n4. Checking for numpy types in response...")
    
    import numpy as np
    
    test_portfolio = [
        {"symbol": "AAPL", "avg_cost": 150.0, "quantity": 10}
    ]
    
    try:
        result = analyze_portfolio(test_portfolio, use_llm=False, force=False)
        
        # Recursively check for numpy types
        def has_numpy_types(obj, path=""):
            """Recursively check for numpy types."""
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if has_numpy_types(v, f"{path}.{k}"):
                        return True
            elif isinstance(obj, (list, tuple)):
                for i, v in enumerate(obj):
                    if has_numpy_types(v, f"{path}[{i}]"):
                        return True
            elif isinstance(obj, (np.bool_, np.integer, np.floating, np.ndarray)):
                print(f"   ❌ Found numpy type at {path}: {type(obj).__name__}")
                return True
            return False
        
        if has_numpy_types(result):
            print(f"   ❌ Response contains numpy types!")
            return False
        else:
            print(f"   ✅ No numpy types found in response")
            return True
            
    except Exception as e:
        print(f"   ❌ Test FAILED: {e}")
        return False


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("PORTFOLIO JSON SERIALIZATION TEST SUITE")
    print("=" * 60)
    
    results = []
    
    # Test 1: Quick mode JSON serialization
    results.append(("Quick Mode JSON", test_portfolio_quick_mode_json_serializable()))
    
    # Test 2: Empty portfolio
    results.append(("Empty Portfolio", test_empty_portfolio()))
    
    # Test 3: Numpy types check
    results.append(("Numpy Types Check", test_portfolio_with_numpy_types()))
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n✅ ALL TESTS PASSED - Portfolio analysis is JSON-safe!")
        sys.exit(0)
    else:
        print("\n❌ SOME TESTS FAILED - Please review the output above")
        sys.exit(1)
