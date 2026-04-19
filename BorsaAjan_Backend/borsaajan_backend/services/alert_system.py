"""
Notification & Alert System
Handles Telegram notifications and scheduled alerts
"""
import requests
import sqlite3
from datetime import datetime
from typing import Dict, Any, Optional
import yfinance as yf
import feedparser

# Hardcoded Telegram credentials
TELEGRAM_TOKEN = "8206565247:AAHqvmxrMKh5aqNUPybNSCkZhEFTfQy0QoQ"
TELEGRAM_CHAT_ID = "8382033425"
DB_PATH = "borsa.db"

# Get absolute path for database (works from any directory)
import os
if not os.path.isabs(DB_PATH):
    # If relative path, make it relative to this file's directory
    current_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(current_dir)
    DB_PATH = os.path.join(parent_dir, DB_PATH)

def send_telegram_message(message: str) -> bool:
    """Send a message to Telegram."""
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML"
        }
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Telegram gönderim hatası: {e}")
        return False

def save_notification(title: str, message: str, notification_type: str) -> int:
    """
    Save notification to database.
    notification_type: 'CRITICAL', 'SUMMARY', or 'ALERT'
    Returns notification ID.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute("""
        INSERT INTO notifications (timestamp, title, message, type)
        VALUES (?, ?, ?, ?)
    """, (timestamp, title, message, notification_type.upper()))
    
    notification_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    print(f"💾 Notification saved: {notification_type} - {title}")
    return notification_id

def send_and_save_notification(title: str, message: str, notification_type: str) -> Dict[str, Any]:
    """
    Send notification to Telegram AND save to database.
    Returns dict with success status and notification_id.
    """
    # Format message for Telegram
    telegram_message = f"<b>{title}</b>\n\n{message}"
    
    # Send to Telegram
    telegram_sent = send_telegram_message(telegram_message)
    
    # Save to database
    notification_id = save_notification(title, message, notification_type)
    
    return {
        "success": telegram_sent,
        "notification_id": notification_id,
        "telegram_sent": telegram_sent,
        "saved_to_db": True
    }

def send_market_summary() -> Dict[str, Any]:
    """
    Generate and send personalized daily market summary.
    Scheduled to run at 17:45, 20:30, and 23:45 daily.
    """
    try:
        print("📊 Generating personalized market summary...")
        
        # Step 1: Get user's portfolio from database
        import sys
        import os
        current_dir = os.path.dirname(os.path.abspath(__file__))
        parent_dir = os.path.dirname(current_dir)
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
        
        from ..database import get_portfolio
        portfolio = get_portfolio()
        portfolio_symbols = [item["symbol"] for item in portfolio] if portfolio else []
        
        # Get major indices
        indices = {
            "S&P 500": "^GSPC",
            "NASDAQ": "^IXIC",
            "DOW": "^DJI"
        }
        
        market_data = {}
        for name, symbol in indices.items():
            try:
                ticker = yf.Ticker(symbol)
                data = ticker.history(period="2d")
                if not data.empty:
                    current = data['Close'].iloc[-1]
                    previous = data['Close'].iloc[-2]
                    change = current - previous
                    change_pct = (change / previous) * 100
                    market_data[name] = {
                        "current": current,
                        "change": change,
                        "change_pct": change_pct
                    }
            except Exception as e:
                print(f"⚠️ Error fetching {name}: {e}")
        
        # Get VIX
        vix_value = None
        try:
            vix = yf.Ticker("^VIX")
            vix_data = vix.history(period="1d")
            if not vix_data.empty:
                vix_value = float(vix_data['Close'].iloc[-1])
        except Exception as e:
            print(f"⚠️ Error fetching VIX: {e}")
        
        # Get DXY (Dollar Index)
        dxy_value = None
        try:
            dxy = yf.Ticker("DX-Y.NYB")
            dxy_data = dxy.history(period="1d")
            if not dxy_data.empty:
                dxy_value = float(dxy_data['Close'].iloc[-1])
        except Exception as e:
            print(f"⚠️ Error fetching DXY: {e}")
        
        # Step 2: Get portfolio stock prices
        portfolio_data = []
        if portfolio_symbols:
            for symbol in portfolio_symbols[:10]:  # Limit to 10 stocks
                try:
                    ticker = yf.Ticker(symbol)
                    data = ticker.history(period="2d")
                    if not data.empty:
                        current = data['Close'].iloc[-1]
                        previous = data['Close'].iloc[-2]
                        change_pct = ((current - previous) / previous) * 100
                        portfolio_data.append({
                            "symbol": symbol,
                            "price": current,
                            "change_pct": change_pct
                        })
                except Exception as e:
                    print(f"⚠️ Error fetching {symbol}: {e}")
        
        # Step 3: Generate AI-powered personalized summary
        try:
            import sys
            import os
            # Import gemini_text from logic module (with built-in rate limiting)
            current_dir = os.path.dirname(os.path.abspath(__file__))
            parent_dir = os.path.dirname(current_dir)
            if parent_dir not in sys.path:
                sys.path.insert(0, parent_dir)
            
            from logic import gemini_text
            
            # Build market context
            market_context = f"""
GENEL PİYASA DURUMU:
"""
            for name, data in market_data.items():
                emoji = "🟢" if data["change"] >= 0 else "🔴"
                market_context += f"{emoji} {name}: {data['change_pct']:+.2f}%\n"
            
            if vix_value:
                market_context += f"VIX (Korku Endeksi): {vix_value:.2f}\n"
            if dxy_value:
                market_context += f"DXY (Dolar Endeksi): {dxy_value:.2f}\n"
            
            portfolio_context = ""
            if portfolio_data:
                portfolio_context = "\nKULLANICININ PORTFÖYÜ:\n"
                for stock in portfolio_data:
                    emoji = "🟢" if stock["change_pct"] >= 0 else "🔴"
                    portfolio_context += f"{emoji} {stock['symbol']}: ${stock['price']:.2f} ({stock['change_pct']:+.2f}%)\n"
            else:
                portfolio_context = "\nKullanıcının portföyü boş.\n"
            
            # Build portfolio list for system prompt
            portfolio_list = ", ".join(portfolio_symbols) if portfolio_symbols else "Portföy boş"
            
            ai_prompt = f"""Sen gerçekçi bir hedge fund yöneticisisin. Aşağıdaki piyasa verilerini ve kullanıcının portföyünü analiz et.

GENEL PİYASA VERİLERİ:
{market_context}
VIX (Korku Endeksi): {vix_value:.2f if vix_value else 'N/A'}
DXY (Dolar Endeksi): {dxy_value:.2f if dxy_value else 'N/A'}

KULLANICININ PORTFÖYÜ: {portfolio_list}
{portfolio_context}

SİSTEM PROMPT: Bu özet, kullanıcının portföyündeki hisselere ({portfolio_list}) özel olarak odaklanmalı. Genel piyasa durumunu (VIX, DXY) ve kullanıcının portföyünü birleştirerek, piyasa koşullarının KULLANICININ HİSSELERİNİ nasıl etkilediğini gerçekçi bir şekilde açıkla.

Günlük özet yaz. Özellikle:
1. Genel piyasa durumu (VIX, DXY) - kısa
2. Kullanıcının portföyündeki hisselerin ({portfolio_list}) nasıl etkilendiği - SPESİFİK ve DETAYLI
3. Risk uyarıları (varsa) - portföy odaklı
4. Öneriler (kısa ve net) - portföy bazlı

Gerçekçi ol. Gereksiz pozitiflik yapma. Türkçe yaz. Maksimum 300 kelime."""
            
            # Use unified gemini_text (with built-in rate limiting for scheduled jobs)
            result = gemini_text(ai_prompt)
            ai_summary = result.get("text", "") if not result.get("fallback") else None
            
            if not ai_summary:
                raise Exception("AI summary generation failed (rate limit or quota)")
            
            # Format final message
            summary_parts = ["📈 <b>Kişiselleştirilmiş Günlük Özet</b>\n"]
            
            # Add market data
            for name, data in market_data.items():
                emoji = "🟢" if data["change"] >= 0 else "🔴"
                summary_parts.append(
                    f"{emoji} <b>{name}</b>: {data['change_pct']:+.2f}%"
                )
            
            if vix_value:
                vix_status = "🔴 YÜKSEK" if vix_value > 30 else "🟢 NORMAL"
                summary_parts.append(f"\n📉 <b>VIX</b>: {vix_value:.2f} - {vix_status}")
            
            summary_parts.append(f"\n🤖 <b>AI Yorumu:</b>\n{ai_summary}")
            
            summary_message = "\n".join(summary_parts)
            
        except Exception as ai_error:
            print(f"⚠️ AI summary generation failed: {ai_error}")
            # Fallback to basic summary
            summary_parts = ["📈 <b>Günlük Piyasa Özeti</b>\n"]
            for name, data in market_data.items():
                emoji = "🟢" if data["change"] >= 0 else "🔴"
                summary_parts.append(
                    f"{emoji} <b>{name}</b>: {data['change_pct']:+.2f}%"
                )
            if vix_value:
                vix_status = "🔴 YÜKSEK" if vix_value > 30 else "🟢 NORMAL"
                summary_parts.append(f"\n📉 <b>VIX</b>: {vix_value:.2f} - {vix_status}")
            summary_message = "\n".join(summary_parts)
        
        # Send and save
        result = send_and_save_notification(
            title="Kişiselleştirilmiş Günlük Özet",
            message=summary_message,
            notification_type="SUMMARY"
        )
        
        print(f"✅ Personalized market summary sent: {result['telegram_sent']}")
        return result
        
    except Exception as e:
        print(f"❌ Error in send_market_summary: {e}")
        import traceback
        traceback.print_exc()
        return {
            "success": False,
            "error": str(e)
        }

def check_critical_news() -> Dict[str, Any]:
    """
    Check for breaking/critical financial news.
    Scheduled to run every 15 minutes.
    """
    try:
        print("🔍 Checking for critical news...")
        
        # Fetch financial news from RSS feeds
        news_feeds = [
            "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^GSPC&region=US&lang=en-US",
            "https://feeds.finance.yahoo.com/rss/2.0/headline?s=^IXIC&region=US&lang=en-US"
        ]
        
        critical_keywords = [
            "crash", "plunge", "surge", "alert", "warning", "breaking",
            "emergency", "crisis", "recession", "inflation", "fed",
            "rate cut", "rate hike", "earnings miss", "earnings beat"
        ]
        
        found_news = []
        
        for feed_url in news_feeds:
            try:
                feed = feedparser.parse(feed_url)
                for entry in feed.entries[:5]:  # Check latest 5 entries
                    title_lower = entry.title.lower()
                    if any(keyword in title_lower for keyword in critical_keywords):
                        found_news.append({
                            "title": entry.title,
                            "link": entry.link,
                            "published": entry.get("published", "N/A")
                        })
            except Exception as e:
                print(f"⚠️ Error parsing feed {feed_url}: {e}")
        
        if found_news:
            # Format critical news message
            news_parts = ["🚨 <b>KRİTİK HABER UYARISI</b>\n"]
            for news in found_news[:3]:  # Limit to 3 most critical
                news_parts.append(f"📰 {news['title']}")
                news_parts.append(f"🔗 {news['link']}")
                news_parts.append(f"⏰ {news['published']}\n")
            
            news_message = "\n".join(news_parts)
            
            # Send and save
            result = send_and_save_notification(
                title="Kritik Piyasa Haberi",
                message=news_message,
                notification_type="CRITICAL"
            )
            
            print(f"✅ Critical news alert sent: {result['telegram_sent']}")
            return result
        else:
            print("ℹ️ No critical news found")
            return {
                "success": True,
                "message": "No critical news",
                "found_news": False
            }
            
    except Exception as e:
        print(f"❌ Error in check_critical_news: {e}")
        return {
            "success": False,
            "error": str(e)
        }

def get_notifications(limit: int = 50) -> list:
    """Get notifications from database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, timestamp, title, message, type
        FROM notifications
        ORDER BY timestamp DESC
        LIMIT ?
    """, (limit,))
    
    rows = cursor.fetchall()
    conn.close()
    
    notifications = []
    for row in rows:
        notifications.append({
            "id": row[0],
            "timestamp": row[1],
            "title": row[2],
            "message": row[3],
            "type": row[4]
        })
    
    return notifications
