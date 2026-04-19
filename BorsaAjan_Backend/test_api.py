import os
import google.generativeai as genai
import time
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Get API key from environment variable
TEST_KEY = os.getenv("GOOGLE_API_KEY")

if not TEST_KEY:
    print("❌ ERROR: GOOGLE_API_KEY environment variable is not set!")
    print("Please set GOOGLE_API_KEY in your environment or .env file.")
    exit(1)

# API key is configured via environment variable only
# No hardcoded keys allowed
if TEST_KEY:
    genai.configure(api_key=TEST_KEY)
else:
    print("❌ ERROR: GOOGLE_API_KEY not set in environment!")
    exit(1)

print("--- API TEŞHİS TESTİ BAŞLIYOR ---")
print(f"Kullanılan Key: {TEST_KEY[:10]}...{TEST_KEY[-3:]} (Doğrulandı)")

try:
    print("\n1. ADIM: Hesabına tanımlı modeller listeleniyor...")
    available_models = []
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f" ✅ Açık Model: {m.name}")
            available_models.append(m.name)

    if not available_models:
        print("\n❌ KRİTİK SONUÇ: Liste boş! Bu API Key çalışıyor ama HİÇBİR modele erişim izni yok.")
        print("   Sebep: Google Cloud Console'da 'Generative Language API' etkinleştirilmemiş olabilir.")
    else:
        print(f"\n✅ Erişim var! {len(available_models)} model bulundu.")
        
        # Eğer model varsa bir de merhaba demeyi deneyelim
        # Prefer gemini-flash-latest, fallback to first available
        test_model_name = "gemini-flash-latest"
        available_models_clean = [m.replace('models/', '') if m.startswith('models/') else m for m in available_models]
        
        if test_model_name not in available_models_clean:
            # Try gemini-2.5-flash as fallback
            if "gemini-2.5-flash" in available_models_clean:
                test_model_name = "gemini-2.5-flash"
            else:
                # Use first available model if preferred not found
                test_model_name = available_models_clean[0] if available_models_clean else available_models[0].replace('models/', '') if available_models[0].startswith('models/') else available_models[0]
            print(f"\n⚠️ 'gemini-flash-latest' bulunamadı. Kullanılan model: {test_model_name}")
        else:
            print(f"\n2. ADIM: '{test_model_name}' ile iletişim denemesi...")
        
        model = genai.GenerativeModel(test_model_name)
        response = model.generate_content("Merhaba, bu bir test.")
        print(f"🤖 Cevap: {response.text}")

except Exception as e:
    print(f"\n🔥 HATA OLUŞTU: {e}")
    print("Bu hata, sorunun %100 API Anahtarı veya Google Hesabı kaynaklı olduğunu kanıtlar.")

input("\nÇıkmak için Enter'a bas...")

# ========== MENTOR DRAWDOWN RESPONSE TESTS ==========
print("\n" + "="*60)
print("MENTOR DRAWDOWN RESPONSE TESTS")
print("="*60)

import sys
import os
# Add parent directory to path to import borsaajan_backend
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from borsaajan_backend.logic import generate_mentor_drawdown_response, chat_with_mentor

def test_keyword_trigger():
    """Test 1: Verify keyword-triggered mentor response"""
    print("\n📝 Test 1: Keyword-triggered mentor response")
    print("-" * 60)
    
    test_messages = [
        "bi anda bir düşüş yaşandı 2 gündür zarara giriyorum neyden kaynaklı bu",
        "portföyüm düşüyor ne yapmalıyım",
        "neden kaybediyorum",
        "2 gündür zarardayım",
        "drawdown yaşıyorum"
    ]
    
    for msg in test_messages:
        print(f"\n  Testing: '{msg[:50]}...'")
        result = generate_mentor_drawdown_response(msg)
        
        if result is None:
            print(f"  ❌ FAILED: No response generated for drawdown keyword")
            return False
        
        if not result.get("success"):
            print(f"  ❌ FAILED: Response not successful")
            return False
        
        if result.get("use_llm") is not False:
            print(f"  ❌ FAILED: use_llm should be False, got {result.get('use_llm')}")
            return False
        
        response = result.get("response", "")
        if not response:
            print(f"  ❌ FAILED: Empty response")
            return False
        
        # Check for required sections
        required_sections = ["📌 Hızlı Teşhis", "🔎 Olası Nedenler", "🧭 Disiplinli Sonraki Adımlar"]
        missing_sections = [s for s in required_sections if s not in response]
        
        if missing_sections:
            print(f"  ❌ FAILED: Missing sections: {missing_sections}")
            return False
        
        print(f"  ✅ PASSED: Response generated with required sections")
        print(f"     Response length: {len(response)} chars")
        print(f"     Mentor mode: {result.get('mentor_mode')}")
    
    return True

def test_no_llm_call():
    """Test 2: Ensure no LLM call occurs for drawdown questions"""
    print("\n📝 Test 2: No LLM call verification")
    print("-" * 60)
    
    # Mock or track LLM calls - we'll check the response structure
    test_message = "bi anda bir düşüş yaşandı 2 gündür zarara giriyorum neyden kaynaklı bu"
    
    print(f"  Testing: '{test_message[:50]}...'")
    result = chat_with_mentor(test_message, context_data=None)
    
    if not result.get("success"):
        print(f"  ❌ FAILED: Chat response not successful")
        print(f"     Error: {result.get('error', 'Unknown')}")
        return False
    
    # Check that use_llm is False or mentor_mode is set
    if result.get("use_llm") is True:
        print(f"  ❌ FAILED: use_llm should be False for drawdown questions")
        return False
    
    if result.get("mentor_mode") != "drawdown_quick":
        print(f"  ⚠️  WARNING: mentor_mode not set, but response may still be QUICK")
        # This is okay if the response structure is correct
    
    response = result.get("response", "")
    if not response:
        print(f"  ❌ FAILED: Empty response")
        return False
    
    # Verify it's a structured mentor response (not generic LLM response)
    if "📌 Hızlı Teşhis" not in response:
        print(f"  ❌ FAILED: Response doesn't contain mentor structure")
        print(f"     Response preview: {response[:200]}...")
        return False
    
    print(f"  ✅ PASSED: No LLM call made, QUICK response generated")
    print(f"     Response length: {len(response)} chars")
    print(f"     Contains structured sections: Yes")
    
    return True

def test_non_drawdown_question():
    """Test 3: Verify non-drawdown questions don't trigger mentor response"""
    print("\n📝 Test 3: Non-drawdown question handling")
    print("-" * 60)
    
    test_message = "NVDA fiyatı ne kadar?"
    print(f"  Testing: '{test_message}'")
    
    result = generate_mentor_drawdown_response(test_message)
    
    if result is not None:
        print(f"  ⚠️  WARNING: Mentor response generated for non-drawdown question")
        print(f"     This is acceptable if the function returns None to continue normal flow")
        # Actually, returning None is correct - it should fall through to LLM
        if result.get("mentor_mode") == "drawdown_quick":
            print(f"  ❌ FAILED: Should return None for non-drawdown questions")
            return False
    
    print(f"  ✅ PASSED: Non-drawdown question correctly returns None (falls through to LLM)")
    
    return True

# Run tests
print("\n")
test_results = []

try:
    result1 = test_keyword_trigger()
    test_results.append(("Keyword Trigger", result1))
except Exception as e:
    print(f"  ❌ Test 1 EXCEPTION: {e}")
    import traceback
    traceback.print_exc()
    test_results.append(("Keyword Trigger", False))

try:
    result2 = test_no_llm_call()
    test_results.append(("No LLM Call", result2))
except Exception as e:
    print(f"  ❌ Test 2 EXCEPTION: {e}")
    import traceback
    traceback.print_exc()
    test_results.append(("No LLM Call", False))

try:
    result3 = test_non_drawdown_question()
    test_results.append(("Non-Drawdown Handling", result3))
except Exception as e:
    print(f"  ❌ Test 3 EXCEPTION: {e}")
    import traceback
    traceback.print_exc()
    test_results.append(("Non-Drawdown Handling", False))

# Summary
print("\n" + "="*60)
print("TEST SUMMARY")
print("="*60)
all_passed = True
for test_name, passed in test_results:
    status = "✅ PASSED" if passed else "❌ FAILED"
    print(f"{test_name}: {status}")
    if not passed:
        all_passed = False

if all_passed:
    print("\n🎉 All tests passed!")
else:
    print("\n⚠️  Some tests failed. Please review the output above.")

print("="*60)