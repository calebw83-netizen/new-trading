from __future__ import annotations

import base64
import json
import time
import uuid
from decimal import Decimal, ROUND_DOWN
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.config import Settings


class RobinhoodBridge:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.base_url = "https://trading.robinhood.com"

    def accounts(self) -> dict[str, Any]:
        if self.settings.broker_mode == "paper":
            return {
                "accounts": [
                    {
                        "currency": "USD",
                        "available_balance": {"value": "1000.00", "currency": "USD"},
                        "paper": True,
                    }
                ]
            }
        return self._signed_request("GET", "/api/v1/crypto/trading/accounts/")

    def holdings(self) -> dict[str, Any]:
        if self.settings.broker_mode == "paper":
            return {"results": []}
        return self._signed_request("GET", "/api/v1/crypto/trading/holdings/")

    def product(self, product_id: str) -> dict[str, Any]:
        if "-" not in product_id:
            return {"symbol": product_id.upper(), "asset_class": "stock"}
        for pair in self.trading_pairs().get("results", []):
            if str(pair.get("symbol", "")).upper() == product_id.upper():
                return pair
        return {"symbol": product_id.upper(), "message": "Pair not found in Robinhood trading pairs."}

    def trading_pairs(self) -> dict[str, Any]:
        if self.settings.broker_mode == "paper":
            return {
                "results": [
                    {"symbol": "BTC-USD", "status": "tradable"},
                    {"symbol": "ETH-USD", "status": "tradable"},
                    {"symbol": "SOL-USD", "status": "tradable"},
                ]
            }
        return self._signed_request("GET", "/api/v1/crypto/trading/trading_pairs/")

    def scan_products(self, quote_currency: str, limit: int) -> list[str]:
        symbols: list[str] = []
        if "crypto" in self.settings.scan_asset_classes:
            symbols.extend(self._scan_crypto_products(quote_currency, limit))
        if "stocks" in self.settings.scan_asset_classes:
            symbols.extend(symbol.upper() for symbol in self.settings.scan_stock_symbols)
        seen: set[str] = set()
        deduped = []
        for symbol in symbols:
            if symbol not in seen:
                seen.add(symbol)
                deduped.append(symbol)
        return deduped[:limit]

    def _scan_crypto_products(self, quote_currency: str, limit: int) -> list[str]:
        try:
            pairs = self.trading_pairs().get("results", [])
            symbols: list[str] = []
            for pair in pairs:
                symbol = str(pair.get("symbol", pair.get("id", ""))).upper()
                if not symbol.endswith(f"-{quote_currency.upper()}"):
                    continue
                if str(pair.get("status", "tradable")).lower() not in {"tradable", "active"}:
                    continue
                symbols.append(symbol)
            if symbols:
                return symbols[:limit]
        except Exception:
            if self.settings.broker_mode != "paper":
                raise
        return [symbol for symbol in sorted(self.settings.allowed_products) if "-" in symbol][:limit]

    def candles(self, product_id: str, granularity: str = "ONE_HOUR", limit: int = 120) -> list[dict[str, Any]]:
        if "-" not in product_id:
            return self._stock_candles(product_id, granularity, limit)
        interval = "hour" if granularity == "ONE_HOUR" else "15minute"
        symbol = product_id.replace("-", "").upper()
        query = urlencode({"bounds": "24_7", "interval": interval, "span": "week"})
        url = f"https://api.robinhood.com/marketdata/forex/historicals/{symbol}/?{query}"
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": "TradingBridge/1.0 (+local personal app)",
                    "Accept": "application/json",
                },
            )
            with urlopen(request, timeout=10) as response:
                body = json.loads(response.read().decode("utf-8"))
            points = body.get("data_points", [])
            candles = [
                {
                    "start": point.get("begins_at"),
                    "open": point.get("open_price"),
                    "high": point.get("high_price"),
                    "low": point.get("low_price"),
                    "close": point.get("close_price"),
                    "volume": point.get("volume") or "1",
                }
                for point in points
                if point.get("close_price")
            ]
            if candles:
                return candles[-limit:]
        except Exception:
            if self.settings.broker_mode != "paper":
                raise
        return self._demo_candles(product_id, limit)

    def _stock_candles(self, symbol: str, granularity: str, limit: int) -> list[dict[str, Any]]:
        interval = "hour" if granularity == "ONE_HOUR" else "15minute"
        query = urlencode({"bounds": "regular", "interval": interval, "span": "week"})
        url = f"https://api.robinhood.com/quotes/historicals/{symbol.upper()}/?{query}"
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": "TradingBridge/1.0 (+local personal app)",
                    "Accept": "application/json",
                },
            )
            with urlopen(request, timeout=10) as response:
                body = json.loads(response.read().decode("utf-8"))
            points = body.get("historicals", [])
            candles = [
                {
                    "start": point.get("begins_at"),
                    "open": point.get("open_price"),
                    "high": point.get("high_price"),
                    "low": point.get("low_price"),
                    "close": point.get("close_price"),
                    "volume": "1",
                }
                for point in points
                if point.get("close_price")
            ]
            if candles:
                return candles[-limit:]
        except Exception:
            pass
        return self._demo_candles(symbol, limit)

    def preview_market_order(self, proposal: dict[str, Any]) -> dict[str, Any]:
        payload = self._order_payload(proposal)
        if "-" not in proposal["product_id"] and self.settings.broker_mode != "paper":
            raise RuntimeError("Live stock execution is not supported by this Robinhood Crypto bridge.")
        if self.settings.broker_mode == "paper":
            return {
                "success": True,
                "paper": True,
                "preview": payload,
                "message": "Paper preview only. No Robinhood order was created.",
            }
        return {
            "success": True,
            "preview": payload,
            "message": "Robinhood Crypto does not expose a separate preview endpoint here.",
        }

    def execute_market_order(self, proposal: dict[str, Any]) -> dict[str, Any]:
        payload = self._order_payload(proposal)
        if "-" not in proposal["product_id"] and self.settings.broker_mode != "paper":
            raise RuntimeError("Live stock execution is not supported by this Robinhood Crypto bridge.")
        if self.settings.broker_mode == "paper":
            return {
                "success": True,
                "paper": True,
                "order_id": f"paper-{uuid.uuid4().hex[:12]}",
                "submitted": payload,
            }
        if not self.settings.live_trading_enabled:
            raise RuntimeError("Live trading is disabled by ROBINHOOD_ENABLE_LIVE_TRADING.")
        return self._signed_request("POST", "/api/v1/crypto/trading/orders/", payload)

    def _order_payload(self, proposal: dict[str, Any]) -> dict[str, Any]:
        side = str(proposal["side"]).lower()
        return {
            "client_order_id": proposal["client_order_id"],
            "side": side,
            "type": "market",
            "symbol": proposal["product_id"],
            "market_order_config": {
                "asset_quantity": str(self._asset_quantity(proposal)),
            },
        }

    def _asset_quantity(self, proposal: dict[str, Any]) -> Decimal:
        if str(proposal["side"]).upper() == "SELL":
            return Decimal(str(proposal["base_size"])).quantize(
                Decimal("0.00000001"), rounding=ROUND_DOWN
            )
        quote_size = Decimal(str(proposal["quote_size"]))
        last_price = Decimal(str(self.candles(proposal["product_id"], limit=1)[-1]["close"]))
        if last_price <= 0:
            raise RuntimeError("Could not estimate Robinhood asset quantity from market price.")
        return (quote_size / last_price).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

    def _signed_request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.settings.has_credentials:
            raise RuntimeError("Robinhood API credentials are not configured.")
        method = method.upper()
        body_text = json.dumps(body or {}, separators=(",", ":")) if body else ""
        timestamp = str(int(time.time()))
        message = f"{self.settings.robinhood_api_key}{timestamp}{path}{method}{body_text}"
        signature = self._private_key().sign(message.encode("utf-8"))
        request = Request(
            f"{self.base_url}{path}",
            data=body_text.encode("utf-8") if body_text else None,
            headers={
                "x-api-key": self.settings.robinhood_api_key or "",
                "x-signature": base64.b64encode(signature).decode("utf-8"),
                "x-timestamp": timestamp,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method=method,
        )
        with urlopen(request, timeout=15) as response:
            text = response.read().decode("utf-8")
        return json.loads(text) if text else {}

    def _private_key(self) -> Ed25519PrivateKey:
        secret = self.settings.robinhood_api_secret or ""
        try:
            return serialization.load_pem_private_key(secret.encode("utf-8"), password=None)
        except ValueError:
            raw = base64.b64decode(secret)
            return Ed25519PrivateKey.from_private_bytes(raw)

    def _demo_candles(self, product_id: str, limit: int) -> list[dict[str, Any]]:
        base = Decimal("65000") if product_id.upper().startswith("BTC") else Decimal("3200")
        candles: list[dict[str, Any]] = []
        for index in range(limit):
            trend = Decimal(index) * (base * Decimal("0.0005"))
            cycle = Decimal((index % 17) - 8) * (base * Decimal("0.0008"))
            close = base + trend + cycle
            open_price = close - (base * Decimal("0.0007"))
            high = max(open_price, close) + (base * Decimal("0.0015"))
            low = min(open_price, close) - (base * Decimal("0.0013"))
            candles.append(
                {
                    "start": str(index),
                    "low": str(low),
                    "high": str(high),
                    "open": str(open_price),
                    "close": str(close),
                    "volume": "1",
                }
            )
        return candles
