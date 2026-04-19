"""
Whale Service: Institutional holders and insider transactions monitoring.
Provides comprehensive whale activity data including both BUY and SELL transactions.
"""
import yfinance as yf
import pandas as pd
from typing import Dict, List

def get_whale_activity(symbols: List[str]) -> Dict:
    """
    Get whale activity (institutional holders and insider transactions) for given symbols.
    Returns both BUY and SELL transactions with clear type indicators.
    
    Args:
        symbols: List of stock symbols
    
    Returns:
        Dictionary with whale_activity and insider_transactions (both BUY and SELL)
    """
    whale_funds = ["Vanguard", "BlackRock", "State Street", "Fidelity", "Berkshire", "T. Rowe Price"]
    whale_activity = []
    insider_transactions = []
    
    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            
            # Get institutional holders
            institutional_holders = ticker.institutional_holders
            
            if institutional_holders is not None and len(institutional_holders) > 0:
                for _, holder in institutional_holders.iterrows():
                    holder_name = holder.get("Holder", "")
                    shares = holder.get("Shares", 0)
                    value = holder.get("Value", 0)
                    
                    # Check if it's a whale fund
                    is_whale = any(whale in holder_name for whale in whale_funds)
                    
                    if is_whale:
                        whale_activity.append({
                            "symbol": symbol,
                            "holder": holder_name,
                            "shares": int(shares) if pd.notna(shares) else 0,
                            "value": float(value) if pd.notna(value) else 0,
                            "is_whale": True
                        })
            
            # Get insider transactions - BOTH BUY AND SELL
            try:
                insider_data = ticker.insider_transactions
                if insider_data is not None and len(insider_data) > 0:
                    # Get most recent 20 transactions (increased to show more data)
                    for _, transaction in insider_data.head(20).iterrows():
                        person = transaction.get("Name", "N/A")
                        transaction_type = transaction.get("Transaction", "")
                        transaction_code = transaction.get("TransactionCode", "")
                        shares = transaction.get("Shares", 0)
                        value = transaction.get("Value", 0)
                        date = transaction.get("Date", "")
                        
                        # Determine if it's BUY or SELL - Enhanced logic
                        is_buy = False
                        transaction_lower = str(transaction_type).lower() if transaction_type else ""
                        
                        # Check transaction type string
                        if any(word in transaction_lower for word in ["purchase", "buy", "acquisition", "option", "award", "grant"]):
                            is_buy = True
                        elif any(word in transaction_lower for word in ["sale", "sell", "disposition", "disposal"]):
                            is_buy = False
                        
                        # Transaction code interpretation
                        if transaction_code:
                            code_str = str(transaction_code).upper()
                            if "P" in code_str or "A" in code_str:
                                is_buy = True
                            elif "S" in code_str or "D" in code_str:
                                is_buy = False
                        
                        # Add transaction value if available
                        transaction_value = float(value) if pd.notna(value) and value != 0 else None
                        
                        insider_transactions.append({
                            "symbol": symbol,
                            "person": person,
                            "type": "BUY" if is_buy else "SELL",  # Clear type indicator
                            "shares": int(shares) if pd.notna(shares) else 0,
                            "value": transaction_value,
                            "date": str(date) if pd.notna(date) else "N/A",
                            "transaction_code": str(transaction_code) if pd.notna(transaction_code) else "",
                            "transaction_type": transaction_type if transaction_type else "N/A"
                        })
            except Exception as insider_error:
                print(f"⚠️ Insider transactions not available for {symbol}: {insider_error}")
                continue
                
        except Exception as e:
            print(f"⚠️ Error fetching whale data for {symbol}: {e}")
            continue
    
    # Sort insider transactions by date (most recent first)
    insider_transactions.sort(key=lambda x: x.get("date", ""), reverse=True)
    
    return {
        "success": True,
        "whale_activity": whale_activity,
        "insider_transactions": insider_transactions,
        "whale_count": len(whale_activity),
        "insider_count": len(insider_transactions),
        "buy_count": sum(1 for t in insider_transactions if t.get("type") == "BUY"),
        "sell_count": sum(1 for t in insider_transactions if t.get("type") == "SELL"),
        "message": f"Found {len(whale_activity)} whale positions and {len(insider_transactions)} insider transactions ({sum(1 for t in insider_transactions if t.get('type') == 'BUY')} buys, {sum(1 for t in insider_transactions if t.get('type') == 'SELL')} sells)"
    }

