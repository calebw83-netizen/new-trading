from decimal import Decimal
import unittest

from app.trading_policy import Policy, evaluate_order


class TradingPolicyTests(unittest.TestCase):
    def test_allows_small_order_for_allowed_product(self):
        policy = Policy({"BTC-USD"}, Decimal("25"), Decimal("100"))

        ok, checks = evaluate_order(
            product_id="BTC-USD",
            side="BUY",
            quote_size=Decimal("10"),
            policy=policy,
            spent_today=Decimal("0"),
        )

        self.assertTrue(ok)
        self.assertEqual(len(checks), 3)

    def test_blocks_unlisted_product(self):
        policy = Policy({"BTC-USD"}, Decimal("25"), Decimal("100"))

        ok, checks = evaluate_order(
            product_id="DOGE-USD",
            side="BUY",
            quote_size=Decimal("10"),
            policy=policy,
            spent_today=Decimal("0"),
        )

        self.assertFalse(ok)
        self.assertIn("not in ALLOWED_PRODUCTS", checks[0])

    def test_blocks_order_above_per_order_cap(self):
        policy = Policy({"BTC-USD"}, Decimal("25"), Decimal("100"))

        ok, checks = evaluate_order(
            product_id="BTC-USD",
            side="BUY",
            quote_size=Decimal("26"),
            policy=policy,
            spent_today=Decimal("0"),
        )

        self.assertFalse(ok)
        self.assertIn("exceeds per-order cap", " ".join(checks))

    def test_blocks_order_above_daily_cap(self):
        policy = Policy({"BTC-USD"}, Decimal("25"), Decimal("100"))

        ok, checks = evaluate_order(
            product_id="BTC-USD",
            side="BUY",
            quote_size=Decimal("10"),
            policy=policy,
            spent_today=Decimal("95"),
        )

        self.assertFalse(ok)
        self.assertIn("above $100", " ".join(checks))

    def test_sell_does_not_increment_daily_buy_total(self):
        policy = Policy({"BTC-USD"}, Decimal("25"), Decimal("100"))

        ok, checks = evaluate_order(
            product_id="BTC-USD",
            side="SELL",
            quote_size=Decimal("10"),
            policy=policy,
            spent_today=Decimal("95"),
        )

        self.assertTrue(ok)
        self.assertIn("unchanged by this sell", " ".join(checks))


if __name__ == "__main__":
    unittest.main()
