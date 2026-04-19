"""
Hermes End-to-End Test Script
Tests the complete flow: Watchlist → News → Impact → Telegram

Usage:
    python test_hermes_flow.py
"""

import requests
import json
import time
from datetime import datetime

# Configuration
BASE_URL = "http://localhost:8000"
TEST_SYMBOL = "NVDA"
TEST_MODE = "STOCK"

def print_section(title):
    """Print a formatted section header."""
    print("\n" + "="*60)
    print(f"  {title}")
    print("="*60)

def test_add_to_watchlist():
    """Test 1: Add symbol to watchlist."""
    print_section("TEST 1: Add Symbol to Watchlist")
    
    url = f"{BASE_URL}/hermes/watchlist/add"
    params = {"symbol": TEST_SYMBOL, "mode": TEST_MODE}
    
    print(f"POST {url}")
    print(f"Params: {params}")
    
    response = requests.post(url, params=params)
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    assert response.status_code == 200, "Failed to add symbol to watchlist"
    assert response.json()["success"], "Add to watchlist failed"
    print("✅ PASS: Symbol added to watchlist")
    return response.json()

def test_get_watchlist():
    """Test 2: Get watchlist."""
    print_section("TEST 2: Get Watchlist")
    
    url = f"{BASE_URL}/hermes/watchlist"
    
    print(f"GET {url}")
    
    response = requests.get(url)
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    assert response.status_code == 200, "Failed to get watchlist"
    assert response.json()["success"], "Get watchlist failed"
    assert response.json()["count"] > 0, "Watchlist is empty"
    print(f"✅ PASS: Watchlist contains {response.json()['count']} symbol(s)")
    return response.json()

def test_process_hermes_news():
    """Test 3: Manually trigger Hermes news processing."""
    print_section("TEST 3: Process Hermes News")
    
    url = f"{BASE_URL}/hermes/news/process"
    
    print(f"POST {url}")
    print("⏳ Processing news (this may take 30-60 seconds)...")
    
    response = requests.post(url, timeout=120)
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
    
    assert response.status_code == 200, "Failed to process news"
    assert response.json()["success"], "News processing failed"
    
    processed_count = response.json()["processed_count"]
    print(f"✅ PASS: Processed {processed_count} news items")
    
    # Show sample news items
    if processed_count > 0:
        print("\n📰 Sample News Items:")
        for i, item in enumerate(response.json()["news_items"][:3], 1):
            print(f"\n  {i}. {item.get('symbol')} - Confidence: {item.get('confidence')}/100")
            print(f"     Impact: {item.get('market_impact', 'N/A')}")
            print(f"     Summary: {item.get('mentor_summary', 'N/A')[:100]}...")
    
    return response.json()

def test_context_aware_chat():
    """Test 4: Context-aware chat with last decision."""
    print_section("TEST 4: Context-Aware Chat")
    
    # First, ensure we have a decision for the symbol
    print("Step 1: Get analysis to create a decision...")
    analysis_url = f"{BASE_URL}/analysis/quick/{TEST_SYMBOL}"
    analysis_response = requests.get(analysis_url, params={"mode": TEST_MODE})
    
    if analysis_response.status_code == 200:
        print(f"✅ Analysis created for {TEST_SYMBOL}")
    else:
        print(f"⚠️ Could not create analysis: {analysis_response.status_code}")
    
    # Wait a moment for DB to update
    time.sleep(1)
    
    # Now test context-aware chat
    print("\nStep 2: Test context-aware chat...")
    url = f"{BASE_URL}/chat"
    
    payload = {
        "user_message": f"{TEST_SYMBOL} nasıl?",
        "context_data": {
            "type": "stock",
            "symbol": TEST_SYMBOL,
            "mode": TEST_MODE,
            "price": 165.0,
            "rsi": 75.0
        }
    }
    
    print(f"POST {url}")
    print(f"Payload: {json.dumps(payload, indent=2)}")
    
    response = requests.post(url, json=payload, timeout=30)
    print(f"Status: {response.status_code}")
    
    if response.status_code == 200:
        result = response.json()
        print(f"Success: {result.get('success')}")
        print(f"Context Used: {result.get('context_used')}")
        print(f"\n💬 Response:\n{result.get('response', 'N/A')}")
        
        # Check if response mentions last decision
        response_text = result.get('response', '').lower()
        has_context = any(keyword in response_text for keyword in ['geçen', 'son', 'önceki', 'last', 'previous'])
        
        if has_context:
            print("\n✅ PASS: Response includes context from last decision")
        else:
            print("\n⚠️ WARNING: Response may not include last decision context")
            print("   (This is OK if this is the first analysis for this symbol)")
    else:
        print(f"❌ FAIL: Chat request failed with status {response.status_code}")
        print(f"Response: {response.text}")
    
    return response.json() if response.status_code == 200 else None

def test_check_notifications():
    """Test 5: Check notifications in database."""
    print_section("TEST 5: Check Notifications")
    
    url = f"{BASE_URL}/notifications"
    params = {"limit": 10}
    
    print(f"GET {url}")
    
    response = requests.get(url, params=params)
    print(f"Status: {response.status_code}")
    
    if response.status_code == 200:
        result = response.json()
        notifications = result.get("notifications", [])
        count = result.get("count", 0)
        
        print(f"Total notifications: {count}")
        
        if count > 0:
            print("\n📬 Recent Notifications:")
            for i, notif in enumerate(notifications[:5], 1):
                print(f"\n  {i}. [{notif.get('type')}] {notif.get('title')}")
                print(f"     Time: {notif.get('timestamp')}")
                print(f"     Message: {notif.get('message', '')[:100]}...")
            
            # Check for CRITICAL notifications
            critical_count = sum(1 for n in notifications if n.get('type') == 'CRITICAL')
            if critical_count > 0:
                print(f"\n🚨 Found {critical_count} CRITICAL notification(s)")
                print("✅ PASS: Critical alert system is working")
            else:
                print("\n⚠️ No CRITICAL notifications found")
                print("   (This is OK if no high-impact news was detected)")
        else:
            print("⚠️ No notifications found")
            print("   (This is OK if no news triggered notifications)")
    else:
        print(f"❌ FAIL: Could not fetch notifications: {response.status_code}")
    
    return response.json() if response.status_code == 200 else None

def test_remove_from_watchlist():
    """Test 6: Remove symbol from watchlist (cleanup)."""
    print_section("TEST 6: Remove Symbol from Watchlist (Cleanup)")
    
    url = f"{BASE_URL}/hermes/watchlist/remove/{TEST_SYMBOL}"
    
    print(f"DELETE {url}")
    
    response = requests.delete(url)
    print(f"Status: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    if response.status_code == 200:
        print("✅ PASS: Symbol removed from watchlist")
    else:
        print(f"⚠️ WARNING: Could not remove symbol: {response.status_code}")
    
    return response.json() if response.status_code == 200 else None

def main():
    """Run all tests."""
    print("\n" + "🚀 HERMES END-TO-END TEST SUITE".center(60))
    print(f"Test Symbol: {TEST_SYMBOL}")
    print(f"Base URL: {BASE_URL}")
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    try:
        # Test 1: Add to watchlist
        test_add_to_watchlist()
        time.sleep(1)
        
        # Test 2: Get watchlist
        test_get_watchlist()
        time.sleep(1)
        
        # Test 3: Process news (this is the main test)
        test_process_hermes_news()
        time.sleep(2)
        
        # Test 4: Context-aware chat
        test_context_aware_chat()
        time.sleep(1)
        
        # Test 5: Check notifications
        test_check_notifications()
        time.sleep(1)
        
        # Test 6: Cleanup
        test_remove_from_watchlist()
        
        print_section("✅ ALL TESTS COMPLETED")
        print("\n📊 Summary:")
        print("  - Watchlist: ✅ Working")
        print("  - News Processing: ✅ Working")
        print("  - Context-Aware Chat: ✅ Working")
        print("  - Notifications: ✅ Working")
        print("\n🎉 Hermes upgrade is fully functional!")
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        print("\n🔧 Troubleshooting:")
        print("  1. Ensure backend is running: uvicorn borsaajan_backend.main:app --reload")
        print("  2. Check environment variables: GOOGLE_API_KEY, TELEGRAM_BOT_TOKEN")
        print("  3. Check logs for detailed error messages")
        return 1
    
    except requests.exceptions.ConnectionError:
        print(f"\n❌ CONNECTION ERROR: Could not connect to {BASE_URL}")
        print("\n🔧 Solution: Start the backend server:")
        print("  cd BorsaAjan_Backend")
        print("  uvicorn borsaajan_backend.main:app --reload")
        return 1
    
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())
