"""
Unit tests for news pipeline deduplication and symbol selection.
"""

import unittest
from datetime import datetime
from borsaajan_backend.news_pipeline import (
    compute_news_hash,
    normalize_news_item,
    get_relevant_symbols_cached,
    score_news_local
)
import feedparser


class TestNewsPipeline(unittest.TestCase):
    """Unit tests for news pipeline components."""
    
    def test_compute_news_hash_deduplication(self):
        """Test that news hash correctly deduplicates same news."""
        # Same news item should produce same hash
        hash1 = compute_news_hash("AAPL", "Apple Reports Record Earnings", "2025-01-15")
        hash2 = compute_news_hash("AAPL", "Apple Reports Record Earnings", "2025-01-15")
        self.assertEqual(hash1, hash2, "Same news should produce same hash")
        
        # Different symbol should produce different hash
        hash3 = compute_news_hash("MSFT", "Apple Reports Record Earnings", "2025-01-15")
        self.assertNotEqual(hash1, hash3, "Different symbol should produce different hash")
        
        # Different date should produce different hash
        hash4 = compute_news_hash("AAPL", "Apple Reports Record Earnings", "2025-01-16")
        self.assertNotEqual(hash1, hash4, "Different date should produce different hash")
        
        # Different title should produce different hash
        hash5 = compute_news_hash("AAPL", "Apple Reports Strong Earnings", "2025-01-15")
        self.assertNotEqual(hash1, hash5, "Different title should produce different hash")
        
        # Normalization should work (case insensitive, whitespace normalized)
        hash6 = compute_news_hash("aapl", "  Apple   Reports   Record   Earnings  ", "2025-01-15")
        self.assertEqual(hash1, hash6, "Normalized inputs should produce same hash")
    
    def test_compute_news_hash_format(self):
        """Test that hash is in correct format."""
        hash_val = compute_news_hash("AAPL", "Test News", "2025-01-15")
        self.assertIsInstance(hash_val, str, "Hash should be string")
        self.assertEqual(len(hash_val), 16, "Hash should be 16 characters")
        self.assertTrue(all(c in '0123456789abcdef' for c in hash_val), "Hash should be hex")
    
    def test_normalize_news_item(self):
        """Test news item normalization."""
        # Create a mock feedparser entry
        class MockEntry:
            def __init__(self):
                self.title = "Test News Title"
                self.summary = "Test summary text"
                self.source = type('obj', (object,), {'title': 'Reuters'})()
                self.published_parsed = (2025, 1, 15, 10, 30, 0, 0, 0, 0)
        
        entry = MockEntry()
        normalized = normalize_news_item(entry)
        
        self.assertIsNotNone(normalized, "Normalized item should not be None")
        self.assertEqual(normalized["title"], "Test News Title")
        self.assertEqual(normalized["snippet"], "Test summary text")
        self.assertEqual(normalized["source"], "Reuters")
        self.assertEqual(normalized["published_date"], "2025-01-15")
    
    def test_normalize_news_item_invalid(self):
        """Test normalization handles invalid entries."""
        # None entry
        result = normalize_news_item(None)
        self.assertIsNone(result, "None entry should return None")
        
        # Entry without title
        class MockEntryNoTitle:
            pass
        
        entry = MockEntryNoTitle()
        result = normalize_news_item(entry)
        self.assertIsNone(result, "Entry without title should return None")
    
    def test_score_news_local(self):
        """Test local news scoring."""
        news_item = {
            "title": "Apple Reports Record Earnings, Beats Expectations",
            "snippet": "Apple Inc. reported record quarterly earnings...",
            "source": "Reuters",
            "symbol": "AAPL"
        }
        
        analysis = score_news_local(news_item)
        
        self.assertIsInstance(analysis, dict, "Analysis should be dict")
        self.assertIn("importance_score", analysis, "Should have importance_score")
        self.assertIn("impact", analysis, "Should have impact")
        self.assertIn("time_horizon", analysis, "Should have time_horizon")
        self.assertIn("reasons", analysis, "Should have reasons")
        
        self.assertIsInstance(analysis["importance_score"], int, "importance_score should be int")
        self.assertGreaterEqual(analysis["importance_score"], 0, "importance_score should be >= 0")
        self.assertLessEqual(analysis["importance_score"], 100, "importance_score should be <= 100")
        
        self.assertIn(analysis["impact"], ["bullish", "bearish", "neutral"], "impact should be valid")
        self.assertIn(analysis["time_horizon"], ["intraday", "short", "long"], "time_horizon should be valid")
        self.assertIsInstance(analysis["reasons"], list, "reasons should be list")
    
    def test_get_relevant_symbols_cached(self):
        """Test symbol selection with caching."""
        # First call should fetch from DB
        symbols1 = get_relevant_symbols_cached()
        self.assertIsInstance(symbols1, set, "Should return set")
        
        # Second call should use cache (if within TTL)
        symbols2 = get_relevant_symbols_cached()
        self.assertEqual(symbols1, symbols2, "Cached result should match")
        
        # All symbols should be uppercase
        for symbol in symbols1:
            self.assertEqual(symbol, symbol.upper(), "Symbols should be uppercase")


class TestNewsDeduplication(unittest.TestCase):
    """Test deduplication logic."""
    
    def test_deduplication_by_hash(self):
        """Test that deduplication works correctly."""
        seen_hashes = set()
        
        # Add first news item
        hash1 = compute_news_hash("AAPL", "Test News", "2025-01-15")
        seen_hashes.add(hash1)
        
        # Try to add same news (should be skipped)
        hash2 = compute_news_hash("AAPL", "Test News", "2025-01-15")
        self.assertIn(hash2, seen_hashes, "Duplicate hash should be detected")
        
        # Add different news (should be added)
        hash3 = compute_news_hash("AAPL", "Different News", "2025-01-15")
        self.assertNotIn(hash3, seen_hashes, "Different hash should not be in set")
        seen_hashes.add(hash3)
        self.assertEqual(len(seen_hashes), 2, "Should have 2 unique hashes")


if __name__ == "__main__":
    unittest.main()
