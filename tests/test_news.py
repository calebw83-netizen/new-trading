import unittest

from app.news import asset_terms, expanded_news_feeds, infer_news_state


class NewsTests(unittest.TestCase):
    def test_asset_terms_include_base_and_market_terms(self):
        terms = asset_terms("BTC-USD")

        self.assertIn("bitcoin", terms)
        self.assertIn("crypto", terms)

    def test_stock_terms_include_company_and_stock_terms(self):
        terms = asset_terms("AAPL")

        self.assertIn("apple", terms)
        self.assertIn("stock", terms)

    def test_expanded_feeds_add_google_news_searches(self):
        feeds = expanded_news_feeds("NVDA", ["https://example.com/feed"])

        self.assertEqual(feeds[0], "https://example.com/feed")
        self.assertTrue(any("news.google.com/rss/search" in feed for feed in feeds))

    def test_infer_news_state_flags_extreme_risk(self):
        score, bias, event_risk = infer_news_state("exchange hack exploit and lawsuit")

        self.assertLess(score, 0)
        self.assertEqual(bias, "bearish")
        self.assertEqual(event_risk, "extreme")

    def test_infer_news_state_flags_bullish_bias(self):
        score, bias, event_risk = infer_news_state("bitcoin etf inflow rally breakout")

        self.assertGreater(score, 0)
        self.assertEqual(bias, "bullish")
        self.assertEqual(event_risk, "low")


if __name__ == "__main__":
    unittest.main()
