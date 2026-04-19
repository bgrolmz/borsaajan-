"""
Hermes Notification Service
Handles intelligent news notifications with Telegram integration and database storage.
"""
import os
import requests
from datetime import datetime
from typing import Dict, Any, Optional
from dotenv import load_dotenv

from .database import get_connection

# Load environment variables
load_dotenv()

# Telegram configuration from environment variables
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send_telegram_message(message: str, parse_mode: str = "Markdown") -> bool:
    """
    Send a message to Telegram using bot API.
    
    Args:
        message: Message text to send
        parse_mode: "Markdown" or "HTML" (default: "Markdown")
    
    Returns:
        True if sent successfully, False otherwise
    """
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ [Telegram] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set in environment")
        return False
    
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": parse_mode
        }
        response = requests.post(url, json=payload, timeout=10)
        
        if response.status_code == 200:
            print(f"✅ [Telegram] Message sent successfully")
            return True
        else:
            print(f"❌ [Telegram] Failed to send message: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ [Telegram] Error sending message: {e}")
        return False


def format_news_notification(
    symbol: str,
    impact: str,
    reason: str,
    title: str = "",
    mentor_summary: str = ""
) -> str:
    """
    Format a news notification message for Telegram.
    
    Args:
        symbol: Stock/crypto symbol (e.g., "NVDA")
        impact: "POSITIVE", "NEGATIVE", or "NEUTRAL"
        reason: Short explanation of impact (1 sentence)
        title: News title (optional)
        mentor_summary: Mentor interpretation (optional)
    
    Returns:
        Formatted message string (Markdown)
    """
    # Determine emoji based on impact
    if impact.upper() == "POSITIVE":
        impact_emoji = "🟢"
        impact_text = "Positive"
    elif impact.upper() == "NEGATIVE":
        impact_emoji = "🔴"
        impact_text = "Negative"
    else:
        impact_emoji = "🟡"
        impact_text = "Neutral"
    
    # Build message
    parts = [
        f"📢 **{symbol}**",
        f"Impact: {impact_emoji} {impact_text}",
        f"Reason: {reason}",
    ]
    
    if title:
        parts.insert(1, f"*{title[:100]}*")
    
    if mentor_summary:
        parts.append(f"\n_Mentor: {mentor_summary[:200]}_")
    
    parts.append("\n_Borsa Ajanı Mentor_")
    
    return "\n".join(parts)


def save_notification_to_db(
    symbol: str,
    title: str,
    message: str,
    notification_type: str = "ALERT",
    impact: Optional[str] = None,
    reason: Optional[str] = None
) -> Optional[int]:
    """
    Save notification to database (notifications table).
    
    Args:
        symbol: Stock/crypto symbol
        title: Notification title
        message: Notification message body
        notification_type: "ALERT", "SUMMARY", "CRITICAL" (default: "ALERT")
        impact: Market impact (optional, for filtering)
        reason: Impact reason (optional)
    
    Returns:
        Notification ID or None if save failed
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Enhanced title with symbol and impact
        if impact and symbol:
            enhanced_title = f"[{symbol}] {impact} - {title[:100]}"
        elif symbol:
            enhanced_title = f"[{symbol}] {title[:100]}"
        else:
            enhanced_title = title[:100]
        
        # Enhanced message with reason if available
        enhanced_message = message
        if reason:
            enhanced_message = f"{message}\n\nImpact Reason: {reason}"
        
        cursor.execute("""
            INSERT INTO notifications (timestamp, title, message, type)
            VALUES (?, ?, ?, ?)
        """, (timestamp, enhanced_title, enhanced_message, notification_type.upper()))
        
        notification_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        print(f"💾 [Notification] Saved to DB: {notification_type} - {enhanced_title}")
        return notification_id
        
    except Exception as e:
        print(f"❌ [Notification] Error saving to DB: {e}")
        import traceback
        traceback.print_exc()
        return None


def send_and_save_notification(
    symbol: str,
    impact: str,
    reason: str,
    title: str = "",
    mentor_summary: str = "",
    notification_type: str = "ALERT"
) -> Dict[str, Any]:
    """
    Send notification to Telegram AND save to database (Hermes unified method).
    
    Args:
        symbol: Stock/crypto symbol
        impact: "POSITIVE", "NEGATIVE", or "NEUTRAL"
        reason: Short explanation of impact (1 sentence)
        title: News title (optional)
        mentor_summary: Mentor interpretation (optional)
        notification_type: "ALERT", "SUMMARY", "CRITICAL" (default: "ALERT")
    
    Returns:
        Dict with success status, notification_id, telegram_sent, saved_to_db
    """
    # Format message for Telegram
    telegram_message = format_news_notification(
        symbol=symbol,
        impact=impact,
        reason=reason,
        title=title,
        mentor_summary=mentor_summary
    )
    
    # Send to Telegram
    telegram_sent = send_telegram_message(telegram_message)
    
    # Format title for DB
    db_title = title if title else f"News Alert: {symbol}"
    
    # Save to database
    notification_id = save_notification_to_db(
        symbol=symbol,
        title=db_title,
        message=telegram_message.replace("**", "").replace("_", ""),  # Remove Markdown for DB
        notification_type=notification_type,
        impact=impact,
        reason=reason
    )
    
    return {
        "success": telegram_sent or notification_id is not None,  # Success if either worked
        "notification_id": notification_id,
        "telegram_sent": telegram_sent,
        "saved_to_db": notification_id is not None,
        "symbol": symbol,
        "impact": impact
    }
