from decimal import Decimal
import unittest

from app.strategy import StrategyContext, analyze_setup


def make_candles(count=90, start=Decimal("100"), step=Decimal("1")):
    candles = []
    for index in range(count):
        close = start + (Decimal(index) * step)
        candles.append(
            {
                "open": str(close - Decimal("0.3")),
                "high": str(close + Decimal("1")),
                "low": str(close - Decimal("1")),
                "close": str(close),
                "volume": str(100 + index),
            }
        )
    candles[-1]["close"] = str(Decimal(candles[-1]["close"]) * Decimal("1.03"))
    candles[-1]["high"] = str(Decimal(candles[-1]["close"]) * Decimal("1.01"))
    candles[-1]["volume"] = "240"
    return candles


def make_downtrend_candles(count=90, start=Decimal("200"), step=Decimal("-1")):
    candles = []
    for index in range(count):
        close = start + (Decimal(index) * step)
        candles.append(
            {
                "open": str(close + Decimal("0.3")),
                "high": str(close + Decimal("1")),
                "low": str(close - Decimal("1")),
                "close": str(close),
                "volume": str(100 + index),
            }
        )
    candles[-1]["close"] = str(Decimal(candles[-1]["close"]) * Decimal("0.97"))
    candles[-1]["low"] = str(Decimal(candles[-1]["close"]) * Decimal("0.99"))
    candles[-1]["volume"] = "240"
    return candles


class StrategyTests(unittest.TestCase):
    def test_constructive_chart_can_propose_buy(self):
        context = StrategyContext(
            product_id="BTC-USD",
            bankroll_usd=Decimal("10"),
            days_remaining=90,
            sentiment_score=2,
            news_bias="bullish",
            event_risk="low",
            headlines="ETF inflows and constructive liquidity",
        )

        result = analyze_setup(make_candles(), context)

        self.assertEqual(result["decision"], "BUY")
        self.assertIsNotNone(result["proposal"])
        self.assertEqual(result["proposal"]["quote_size"], "10.00")

    def test_extreme_event_risk_blocks_trade(self):
        context = StrategyContext(
            product_id="BTC-USD",
            bankroll_usd=Decimal("10"),
            days_remaining=90,
            sentiment_score=5,
            news_bias="bullish",
            event_risk="extreme",
            headlines="war hack sec lawsuit",
        )

        result = analyze_setup(make_candles(), context)

        self.assertEqual(result["decision"], "NO_TRADE")
        self.assertIsNone(result["proposal"])

    def test_bearish_chart_with_inventory_can_propose_sell(self):
        context = StrategyContext(
            product_id="BTC-USD",
            bankroll_usd=Decimal("10"),
            days_remaining=90,
            sentiment_score=-3,
            news_bias="bearish",
            event_risk="elevated",
            headlines="hack lawsuit liquidation outflow",
            base_inventory=Decimal("0.003"),
        )

        result = analyze_setup(make_downtrend_candles(), context)

        self.assertEqual(result["decision"], "SELL")
        self.assertIsNotNone(result["proposal"])
        self.assertEqual(result["proposal"]["side"], "SELL")
        self.assertEqual(result["proposal"]["base_size"], "0.00099000")

    def test_sell_signal_without_inventory_has_no_order(self):
        context = StrategyContext(
            product_id="BTC-USD",
            bankroll_usd=Decimal("10"),
            days_remaining=90,
            sentiment_score=-3,
            news_bias="bearish",
            event_risk="elevated",
            headlines="hack lawsuit liquidation outflow",
        )

        result = analyze_setup(make_downtrend_candles(), context)

        self.assertEqual(result["decision"], "SELL")
        self.assertIsNone(result["proposal"])
        self.assertGreater(result["sell_score"], result["buy_score"])


if __name__ == "__main__":
    unittest.main()
