from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

from app.news import DEFAULT_NEWS_FEEDS


load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _decimal(name: str, default: str) -> Decimal:
    return Decimal(os.getenv(name, default))


def _products() -> set[str]:
    raw = os.getenv("ALLOWED_PRODUCTS", "BTC-USD,ETH-USD,AAPL,NVDA,TSLA,SPY,QQQ")
    return {item.strip().upper() for item in raw.split(",") if item.strip()}


def _csv(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _news_feeds() -> list[str]:
    seen: set[str] = set()
    feeds: list[str] = []
    for feed in [*_csv("NEWS_FEEDS", ""), *DEFAULT_NEWS_FEEDS]:
        if feed and feed not in seen:
            seen.add(feed)
            feeds.append(feed)
    return feeds


@dataclass(frozen=True)
class Settings:
    robinhood_api_key: str | None
    robinhood_api_secret: str | None
    broker_mode: str
    live_trading_enabled: bool
    allowed_products: set[str]
    max_order_quote_usd: Decimal
    daily_quote_limit_usd: Decimal
    require_confirmation: bool
    audit_db_path: Path
    news_feeds: list[str]
    news_timeout_seconds: int
    scan_quote_currency: str
    scan_max_products: int
    scan_stock_symbols: list[str]
    scan_asset_classes: set[str]
    auto_execute_enabled: bool
    auto_execute_min_score: int
    autopilot_enabled: bool
    autopilot_interval_seconds: int
    autopilot_bankroll_usd: Decimal
    autopilot_days_remaining: int
    autopilot_max_products: int

    @property
    def has_credentials(self) -> bool:
        return bool(self.robinhood_api_key and self.robinhood_api_secret)


def get_settings() -> Settings:
    mode = os.getenv("ROBINHOOD_MODE", "paper").strip().lower()
    if mode not in {"paper", "live"}:
        mode = "paper"
    return Settings(
        robinhood_api_key=os.getenv("ROBINHOOD_API_KEY") or None,
        robinhood_api_secret=os.getenv("ROBINHOOD_API_SECRET") or None,
        broker_mode=mode,
        live_trading_enabled=_bool("ROBINHOOD_ENABLE_LIVE_TRADING", False),
        allowed_products=_products(),
        max_order_quote_usd=_decimal("MAX_ORDER_QUOTE_USD", "25"),
        daily_quote_limit_usd=_decimal("DAILY_QUOTE_LIMIT_USD", "100"),
        require_confirmation=_bool("REQUIRE_CONFIRMATION", True),
        audit_db_path=Path(os.getenv("AUDIT_DB_PATH", "trade_audit.sqlite3")),
        news_feeds=_news_feeds(),
        news_timeout_seconds=int(os.getenv("NEWS_TIMEOUT_SECONDS", "8")),
        scan_quote_currency=os.getenv("SCAN_QUOTE_CURRENCY", "USD").strip().upper(),
        scan_max_products=max(1, int(os.getenv("SCAN_MAX_PRODUCTS", "12"))),
        scan_stock_symbols=_csv(
            "SCAN_STOCK_SYMBOLS",
            "AAPL,NVDA,TSLA,MSFT,AMZN,META,GOOGL,AMD,SPY,QQQ,IWM,COIN,MSTR,HOOD",
        ),
        scan_asset_classes={
            item.lower()
            for item in _csv("SCAN_ASSET_CLASSES", "crypto,stocks")
            if item.lower() in {"crypto", "stocks"}
        },
        auto_execute_enabled=_bool("AUTO_EXECUTE_ENABLED", False),
        auto_execute_min_score=max(80, int(os.getenv("AUTO_EXECUTE_MIN_SCORE", "80"))),
        autopilot_enabled=_bool("AUTOPILOT_ENABLED", False),
        autopilot_interval_seconds=max(300, int(os.getenv("AUTOPILOT_INTERVAL_SECONDS", "300"))),
        autopilot_bankroll_usd=_decimal("AUTOPILOT_BANKROLL_USD", "10"),
        autopilot_days_remaining=min(
            365, max(1, int(os.getenv("AUTOPILOT_DAYS_REMAINING", "90")))
        ),
        autopilot_max_products=min(50, max(1, int(os.getenv("AUTOPILOT_MAX_PRODUCTS", "12")))),
    )
