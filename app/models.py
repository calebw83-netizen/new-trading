from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


Side = Literal["BUY", "SELL"]


class TradeProposalRequest(BaseModel):
    product_id: str = Field(default="BTC-USD", min_length=3, max_length=32)
    side: Side
    quote_size: Decimal = Field(gt=0)
    base_size: Decimal | None = Field(default=None, gt=0)
    rationale: str = Field(default="", max_length=2000)

    @field_validator("product_id")
    @classmethod
    def normalize_product(cls, value: str) -> str:
        return value.strip().upper()

    @model_validator(mode="after")
    def validate_size_for_side(self) -> "TradeProposalRequest":
        if self.side == "SELL" and self.base_size is None:
            raise ValueError("Sell proposals require a base asset size.")
        return self


class TradeProposal(BaseModel):
    client_order_id: str
    product_id: str
    side: Side
    quote_size: Decimal
    base_size: Decimal | None = None
    rationale: str
    status: Literal["approved", "blocked"]
    checks: list[str]


class ExecuteOrderRequest(BaseModel):
    proposal: TradeProposal
    confirmation: str = ""


class StrategyRequest(BaseModel):
    product_id: str = Field(default="BTC-USD", min_length=3, max_length=32)
    bankroll_usd: Decimal = Field(default=Decimal("10"), gt=0)
    days_remaining: int = Field(default=90, ge=1, le=365)
    sentiment_score: int = Field(default=0, ge=-5, le=5)
    news_bias: Literal["bearish", "neutral", "bullish"] = "neutral"
    event_risk: Literal["low", "elevated", "extreme"] = "elevated"
    headlines: str = Field(default="", max_length=3000)
    base_inventory: Decimal | None = Field(default=None, ge=0)
    auto_fetch_news: bool = True

    @field_validator("product_id")
    @classmethod
    def normalize_strategy_product(cls, value: str) -> str:
        return value.strip().upper()


class StrategyScanRequest(BaseModel):
    bankroll_usd: Decimal = Field(default=Decimal("10"), gt=0)
    days_remaining: int = Field(default=90, ge=1, le=365)
    base_inventory: Decimal | None = Field(default=None, ge=0)
    max_products: int | None = Field(default=None, ge=1, le=50)


class NewsRequest(BaseModel):
    product_id: str = Field(default="BTC-USD", min_length=3, max_length=32)

    @field_validator("product_id")
    @classmethod
    def normalize_news_product(cls, value: str) -> str:
        return value.strip().upper()


class ApiResult(BaseModel):
    ok: bool
    mode: str
    data: dict[str, Any] | list[Any] | None = None
    message: str | None = None
