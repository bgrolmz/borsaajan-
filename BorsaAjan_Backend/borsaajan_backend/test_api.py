import sys
import os
from google import genai
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

print("=== DEBUG GEMINI ENV (test_api.py) ===")
print("sys.executable:", sys.executable)
print("Using NEW google-genai SDK (not legacy google.generativeai)")
print("GOOGLE_API_KEY set?", bool(os.environ.get("GOOGLE_API_KEY")))
print("=========================")

# Get API key from environment variable
api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    print("❌ ERROR: GOOGLE_API_KEY environment variable is not set!")
    print("Please set GOOGLE_API_KEY in your environment or .env file.")
    exit(1)

# NEW SDK: Create client with API key (no global configure)
client = genai.Client(api_key=api_key)

print(f"🐍 Python Yolu: {sys.executable}")
print(f"✅ google-genai Client created successfully")

print("\n--- Erişilebilir Modeller (Dynamic Discovery) ---")
try:
    for m in client.models.list():
        if 'generateContent' in m.supported_actions:
            print(f"- {m.name}")
except Exception as e:
    print(f"HATA: Modeller listelenemedi. Sebep: {e}")

# ========== POLICY GUARDRAILS TEST ==========
def test_policy_guardrails_bearish():
    """
    Test policy guardrails with bearish high-importance news.
    Verifies that BUY recommendations are blocked and confidence is capped at 40.
    """
    print("\n=== Testing Policy Guardrails (Bearish Scenario) ===")
    
    try:
        # Import after path setup
        from borsaajan_backend.logic import apply_policy_guardrails
        
        # Create fake analysis with BUY recommendation
        fake_analysis = {
            "symbol": "TEST",
            "price_at_analysis": 100.0,
            "strategy": {
                "stance": "BUY",
                "risk_management_tr": {}
            },
            "confidence_score": {
                "value": 85,
                "reasons_tr": []
            }
        }
        
        # Create fake bearish news with high importance_score
        fake_news_items = [
            {
                "title": "Test Bearish News - Major Lawsuit",
                "importance_score": 85,
                "impact": "bearish"  # or "Negatif" in Turkish
            }
        ]
        
        # Apply policy guardrails
        result = apply_policy_guardrails(fake_analysis, fake_news_items)
        
        # Verify results
        stance = result["strategy"].get("stance", "").upper()
        confidence = result["confidence_score"].get("value", 0) if isinstance(result["confidence_score"], dict) else result.get("confidence_score", 0)
        stop_loss = result["strategy"].get("risk_management_tr", {}).get("stop_loss")
        
        print(f"✅ Original stance: BUY")
        print(f"✅ After policy: {stance}")
        print(f"✅ Confidence (should be <= 40): {confidence}")
        print(f"✅ Stop loss (should be set): {stop_loss}")
        
        # Assertions
        assert stance == "HOLD", f"Expected HOLD, got {stance}"
        assert confidence <= 40, f"Expected confidence <= 40, got {confidence}"
        assert stop_loss is not None and stop_loss > 0, f"Expected stop_loss to be set, got {stop_loss}"
        assert "policy_guardrails_applied" in result.get("data_quality_flags", []), "Expected policy_guardrails_applied flag"
        
        print("✅ All assertions passed!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # Run test
    test_policy_guardrails_bearish()
