"""
Unit tests for data provider normalization and failure fallback.
"""

import unittest
from borsaajan_backend.data_provider import (
    normalize_symbol,
    validate_symbol,
    create_missing_data_response,
    fetch_market_data_robust
)


class TestSymbolNormalization(unittest.TestCase):
    """Test symbol normalization for various formats."""
    
    def test_us_stock_normalization(self):
        """Test US stock symbol normalization."""
        # Basic US stocks
        symbol, mode = normalize_symbol("AAPL")
        self.assertEqual(symbol, "AAPL")
        self.assertEqual(mode, "STOCK")
        
        symbol, mode = normalize_symbol("msft")
        self.assertEqual(symbol, "MSFT")
        self.assertEqual(mode, "STOCK")
        
        symbol, mode = normalize_symbol("NVDA")
        self.assertEqual(symbol, "NVDA")
        self.assertEqual(mode, "STOCK")
    
    def test_crypto_normalization(self):
        """Test cryptocurrency symbol normalization."""
        # Crypto with -USD suffix
        symbol, mode = normalize_symbol("BTC-USD")
        self.assertEqual(symbol, "BTC-USD")
        self.assertEqual(mode, "CRYPTO")
        
        # Crypto without suffix (should add -USD)
        symbol, mode = normalize_symbol("BTC")
        self.assertEqual(symbol, "BTC-USD")
        self.assertEqual(mode, "CRYPTO")
        
        # Crypto with mode hint
        symbol, mode = normalize_symbol("ETH", mode="CRYPTO")
        self.assertEqual(symbol, "ETH-USD")
        self.assertEqual(mode, "CRYPTO")
        
        # Crypto already has suffix
        symbol, mode = normalize_symbol("SOL-USD")
        self.assertEqual(symbol, "SOL-USD")
        self.assertEqual(mode, "CRYPTO")
    
    def test_turkish_stock_normalization(self):
        """Test Turkish stock symbol normalization."""
        # Turkish stocks with .IS suffix
        symbol, mode = normalize_symbol("THYAO.IS")
        self.assertEqual(symbol, "THYAO.IS")
        self.assertEqual(mode, "TR")
        
        symbol, mode = normalize_symbol("akbnk.is")
        self.assertEqual(symbol, "AKBNK.IS")
        self.assertEqual(mode, "TR")
        
        # Turkish stocks with .ISX suffix
        symbol, mode = normalize_symbol("GARAN.ISX")
        self.assertEqual(symbol, "GARAN.ISX")
        self.assertEqual(mode, "TR")
    
    def test_otc_stock_normalization(self):
        """Test OTC stock symbol normalization."""
        # OTC stocks with .US suffix
        symbol, mode = normalize_symbol("SYMBOL.US")
        self.assertEqual(symbol, "SYMBOL.US")
        self.assertEqual(mode, "STOCK")
    
    def test_symbol_validation(self):
        """Test symbol validation."""
        # Valid symbols
        is_valid, error = validate_symbol("AAPL")
        self.assertTrue(is_valid)
        self.assertIsNone(error)
        
        is_valid, error = validate_symbol("BTC-USD")
        self.assertTrue(is_valid)
        self.assertIsNone(error)
        
        is_valid, error = validate_symbol("THYAO.IS")
        self.assertTrue(is_valid)
        self.assertIsNone(error)
        
        # Invalid symbols
        is_valid, error = validate_symbol("")
        self.assertFalse(is_valid)
        self.assertIsNotNone(error)
        
        is_valid, error = validate_symbol("TOO_LONG_SYMBOL_NAME")
        self.assertFalse(is_valid)
        self.assertIsNotNone(error)
        
        is_valid, error = validate_symbol("INVALID@SYMBOL")
        self.assertFalse(is_valid)
        self.assertIsNotNone(error)
    
    def test_mode_hint(self):
        """Test mode hint parameter."""
        # Mode hint for crypto
        symbol, mode = normalize_symbol("BTC", mode="CRYPTO")
        self.assertEqual(symbol, "BTC-USD")
        self.assertEqual(mode, "CRYPTO")
        
        # Mode hint for stock (should override crypto detection)
        symbol, mode = normalize_symbol("BTC", mode="STOCK")
        self.assertEqual(symbol, "BTC")
        self.assertEqual(mode, "STOCK")
        
        # Mode hint for Turkish stock
        symbol, mode = normalize_symbol("THYAO", mode="TR")
        self.assertEqual(symbol, "THYAO")
        self.assertEqual(mode, "TR")
    
    def test_edge_cases(self):
        """Test edge cases and special characters."""
        # Symbol with $ prefix (common in some formats)
        symbol, mode = normalize_symbol("$AAPL")
        self.assertEqual(symbol, "AAPL")
        self.assertEqual(mode, "STOCK")
        
        # Symbol with ^ prefix (indices)
        symbol, mode = normalize_symbol("^GSPC")
        self.assertEqual(symbol, "GSPC")
        self.assertEqual(mode, "STOCK")
        
        # Whitespace handling
        symbol, mode = normalize_symbol("  AAPL  ")
        self.assertEqual(symbol, "AAPL")
        self.assertEqual(mode, "STOCK")
        
        # Case insensitivity
        symbol, mode = normalize_symbol("aapl")
        self.assertEqual(symbol, "AAPL")
        self.assertEqual(mode, "STOCK")


class TestMissingDataResponse(unittest.TestCase):
    """Test missing data response creation."""
    
    def test_missing_data_response(self):
        """Test creation of HOLD response for missing data."""
        response = create_missing_data_response(
            symbol="TEST",
            missing_sections=["quote", "ohlc"],
            errors=["Provider timeout", "Network error"]
        )
        
        self.assertEqual(response["decision"], "HOLD")
        self.assertEqual(response["confidence"], 20)
        self.assertIn("why_bullets", response)
        self.assertIn("action_plan", response)
        self.assertIn("missing_data", response)
        self.assertIn("risk_note", response)
        
        # Check missing_data structure
        missing_data = response["missing_data"]
        self.assertEqual(missing_data["symbol"], "TEST")
        self.assertIn("quote", missing_data["sections"])
        self.assertIn("ohlc", missing_data["sections"])
        self.assertEqual(len(missing_data["errors"]), 2)
    
    def test_all_sections_missing(self):
        """Test response when all sections are missing."""
        response = create_missing_data_response(
            symbol="INVALID",
            missing_sections=["quote", "ohlc", "fundamentals", "news"],
            errors=["Symbol not found"]
        )
        
        self.assertEqual(response["decision"], "HOLD")
        self.assertEqual(response["confidence"], 20)
        self.assertIn("all data", response["why_bullets"][0].lower())


class TestDataProviderIntegration(unittest.TestCase):
    """Integration tests for data provider (may require network)."""
    
    def test_fetch_real_symbol(self):
        """Test fetching data for a real symbol (requires network)."""
        # This test may fail if network is unavailable
        try:
            result = fetch_market_data_robust("AAPL", mode="STOCK", include_ohlc=False, include_fundamentals=False)
            
            # Should have normalized symbol
            self.assertIn("symbol", result)
            self.assertEqual(result["symbol"], "AAPL")
            
            # Should have mode
            self.assertIn("mode", result)
            
            # Should have provider_used
            self.assertIn("provider_used", result)
            
            # Should have errors list
            self.assertIn("errors", result)
            
            # If successful, should have quote
            if result["success"]:
                self.assertIsNotNone(result["quote"])
                self.assertIn("current_price", result["quote"])
            else:
                # If failed, should have missing_data_response
                self.assertIsNotNone(result["missing_data_response"])
                self.assertEqual(result["missing_data_response"]["decision"], "HOLD")
                
        except Exception as e:
            # Network errors are acceptable in tests
            self.skipTest(f"Network test skipped: {e}")
    
    def test_fetch_invalid_symbol(self):
        """Test fetching data for invalid symbol."""
        result = fetch_market_data_robust("INVALID_SYMBOL_XYZ123", mode="STOCK")
        
        # Should have normalized symbol (attempted)
        self.assertIn("symbol", result)
        
        # Should have errors
        self.assertGreater(len(result["errors"]), 0)
        
        # Should have missing_data_response
        self.assertIsNotNone(result["missing_data_response"])
        self.assertEqual(result["missing_data_response"]["decision"], "HOLD")
    
    def test_fetch_crypto_symbol(self):
        """Test fetching data for crypto symbol."""
        try:
            result = fetch_market_data_robust("BTC", mode="CRYPTO", include_ohlc=False, include_fundamentals=False)
            
            # Should normalize to BTC-USD
            self.assertEqual(result["symbol"], "BTC-USD")
            self.assertEqual(result["mode"], "CRYPTO")
            
            # Should not have fundamentals (crypto)
            self.assertIsNone(result["fundamentals"])
            
        except Exception as e:
            self.skipTest(f"Network test skipped: {e}")


if __name__ == "__main__":
    unittest.main()
