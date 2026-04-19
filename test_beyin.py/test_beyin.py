import yfinance as yf
from google import genai
import os

# API Key'ini buraya string olarak yapıştır (Normalde env'den çekilir ama test için buraya yaz)
API_KEY = "AIzaSyBYgfvYtCwqPN75X084Eal5Ecy_QPh7BZk" 

def test_sistemi():
    hisse = "NVDA"
    print(f"--- {hisse} Verisi Çekiliyor (Canlı) ---")
    
    try:
        # 1. VERİ ÇEKME (En sade haliyle)
        ticker = yf.Ticker(hisse)
        # Sadece son 5 günü çekelim, 2026 yılına gitmeyelim :)
        df = ticker.history(period="5d", interval="1d")
        
        if df.empty:
            print("❌ HATA: Veri boş geldi! Sorun yfinance veya internet bağlantısında.")
            return

        son_fiyat = df['Close'].iloc[-1]
        print(f"✅ BAŞARILI: Güncel Fiyat: ${son_fiyat:.2f}")
        print("------------------------------------------------")
        
        # 2. YORUMLATMA (Ezber Bozan Kısım)
        print("--- Yapay Zeka Düşünüyor (Google Gemini) ---")
        
        client = genai.Client(api_key=API_KEY)
        
        # Dinamik model keşfi - API'den mevcut modelleri çek
        model_name = None
        for model in client.models.list():
            if "generateContent" in model.supported_actions:
                model_name = model.name
                break
        
        if not model_name:
            print("❌ HATA: generateContent destekleyen model bulunamadı!")
            return
        
        print(f"✅ Bulunan Model: {model_name}")
        
        # Ona ezberleyemeyeceği, anlık bir soru soruyoruz
        prompt = f"""
        Sen agresif bir borsa yatırımcısısın.
        NVDA hissesi şu an ${son_fiyat:.2f} seviyesinde.
        Son 5 günlük hareket: {df['Close'].to_list()}
        
        Bana kısa ve net bir yorum yap. Sakın 'Yatırım tavsiyesi değildir' deme.
        Sence yön yukarı mı aşağı mı? Tek bir paragraf yaz.
        """
        
        response = client.models.generate_content(model=model_name, contents=prompt)
        print("\n🤖 MENTOR YORUMU:")
        print(response.text)
        
    except Exception as e:
        print(f"❌ KRİTİK HATA: {e}")

if __name__ == "__main__":
    test_sistemi()