from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from statistics import mean
from typing import Any, Literal


Decision = Literal["BUY", "SELL", "NO_TRADE"]


@dataclass(frozen=True)
class StrategyContext:
    product_id: str
    bankroll_usd: Decimal
    days_remaining: int
    sentiment_score: int
    news_bias: Literal["bearish", "neutral", "bullish"]
    event_risk: Literal["low", "elevated", "extreme"]
    headlines: str
    base_inventory: Decimal | None = None


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value))


def _ema(values: list[Decimal], period: int) -> Decimal:
    if not values:
        return Decimal("0")
    k = Decimal("2") / Decimal(period + 1)
    ema = values[0]
    for value in values[1:]:
        ema = (value * k) + (ema * (Decimal("1") - k))
    return ema


def _rsi(closes: list[Decimal], period: int = 14) -> Decimal:
    if len(closes) <= period:
        return Decimal("50")
    gains: list[Decimal] = []
    losses: list[Decimal] = []
    recent = closes[-(period + 1) :]
    for previous, current in zip(recent, recent[1:]):
        change = current - previous
        if change >= 0:
            gains.append(change)
            losses.append(Decimal("0"))
        else:
            gains.append(Decimal("0"))
            losses.append(abs(change))
    avg_gain = sum(gains) / Decimal(period)
    avg_loss = sum(losses) / Decimal(period)
    if avg_loss == 0:
        return Decimal("100")
    rs = avg_gain / avg_loss
    return Decimal("100") - (Decimal("100") / (Decimal("1") + rs))


def _atr_percent(candles: list[dict[str, Any]], period: int = 14) -> Decimal:
    if len(candles) < period + 1:
        return Decimal("0")
    true_ranges: list[Decimal] = []
    recent = candles[-(period + 1) :]
    previous_close = _decimal(recent[0]["close"])
    for candle in recent[1:]:
        high = _decimal(candle["high"])
        low = _decimal(candle["low"])
        close = _decimal(candle["close"])
        true_ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
        previous_close = close
    atr = sum(true_ranges) / Decimal(len(true_ranges))
    last_close = _decimal(candles[-1]["close"])
    if last_close == 0:
        return Decimal("0")
    return (atr / last_close) * Decimal("100")


def _volume_ratio(candles: list[dict[str, Any]], period: int = 20) -> Decimal:
    if len(candles) < period + 1:
        return Decimal("1")
    volumes = [_decimal(candle["volume"]) for candle in candles[-(period + 1) : -1]]
    baseline = Decimal(str(mean(volumes))) if volumes else Decimal("1")
    if baseline == 0:
        return Decimal("1")
    return _decimal(candles[-1]["volume"]) / baseline


def _headline_penalty(headlines: str) -> int:
    text = headlines.lower()
    risk_terms = {
        "hack",
        "exploit",
        "sec",
        "lawsuit",
        "bankruptcy",
        "halt",
        "war",
        "default",
        "liquidation",
        "investigation",
    }
    hype_terms = {"moon", "guaranteed", "100x", "pump", "insider", "risk-free"}
    penalty = sum(5 for term in risk_terms if term in text)
    penalty += sum(4 for term in hype_terms if term in text)
    return min(penalty, 25)


def _confidence_label(score: int) -> str:
    if score >= 78:
        return "A setup"
    if score >= 66:
        return "B setup"
    if score >= 55:
        return "Watchlist"
    return "No trade"


def analyze_setup(candles: list[dict[str, Any]], context: StrategyContext) -> dict[str, Any]:
    if len(candles) < 30:
        return {
            "decision": "NO_TRADE",
            "score": 0,
            "confidence": "No trade",
            "rationale": "Not enough candle history to judge the chart.",
            "checks": ["Need at least 30 candles before proposing risk."],
            "metrics": {},
            "proposal": None,
        }

    closes = [_decimal(candle["close"]) for candle in candles]
    highs = [_decimal(candle["high"]) for candle in candles]
    lows = [_decimal(candle["low"]) for candle in candles]
    last = closes[-1]
    ema9 = _ema(closes[-30:], 9)
    ema21 = _ema(closes[-45:], 21)
    ema50 = _ema(closes[-70:], 50)
    rsi14 = _rsi(closes)
    atr_pct = _atr_percent(candles)
    volume_ratio = _volume_ratio(candles)
    prior_20_high = max(highs[-21:-1])
    prior_20_low = min(lows[-21:-1])
    momentum_20 = ((last - closes[-21]) / closes[-21]) * Decimal("100")
    drawdown_20 = ((last - prior_20_high) / prior_20_high) * Decimal("100")

    buy_score = 50
    sell_score = 50
    checks: list[str] = []
    sell_checks: list[str] = []

    if ema9 > ema21 > ema50:
        buy_score += 18
        sell_score -= 14
        checks.append("Trend stack is constructive: fast EMA above medium above long.")
    elif ema9 < ema21 < ema50:
        buy_score -= 20
        sell_score += 22
        checks.append("Trend stack is defensive: fast EMA below medium below long.")
        sell_checks.append("Sell pressure: trend stack is bearish across fast, medium, and long EMAs.")
    else:
        buy_score -= 4
        sell_score -= 2
        checks.append("Trend is mixed; veteran mode demands cleaner structure.")

    if last > prior_20_high and volume_ratio >= Decimal("1.3"):
        buy_score += 14
        sell_score -= 10
        checks.append("Breakout has volume confirmation instead of a thin poke above resistance.")
    elif last > prior_20_high:
        buy_score += 5
        sell_score -= 4
        checks.append("Price is above recent resistance, but volume confirmation is weak.")
    elif last < prior_20_low:
        buy_score -= 12
        sell_score += 14
        checks.append("Price is breaking recent support; avoid catching falling knives.")
        sell_checks.append("Sell pressure: price is breaking recent support.")

    if Decimal("42") <= rsi14 <= Decimal("68"):
        buy_score += 8
        checks.append("RSI is in a tradable range, not washed out or euphoric.")
    elif rsi14 > Decimal("76"):
        buy_score -= 16
        sell_score += 12
        checks.append("RSI is hot; late entries often become exit liquidity.")
        sell_checks.append("Sell pressure: RSI is hot enough to favor trimming risk.")
    elif rsi14 < Decimal("30") and ema9 > ema21:
        buy_score += 6
        sell_score -= 6
        checks.append("RSI is washed out inside an improving trend; possible reversal watch.")
    elif rsi14 < Decimal("30"):
        buy_score -= 8
        sell_score += 6
        checks.append("RSI is oversold, but trend has not repaired yet.")

    if atr_pct > Decimal("8"):
        buy_score -= 10
        sell_score += 4
        checks.append("Volatility is wide enough to punish loose sizing.")
    elif Decimal("2") <= atr_pct <= Decimal("6"):
        buy_score += 5
        checks.append("Volatility is active but manageable for a small account.")

    if momentum_20 > Decimal("20"):
        buy_score -= 6
        sell_score += 8
        checks.append("Twenty-candle momentum is stretched; chase risk is elevated.")
        sell_checks.append("Sell pressure: momentum is stretched enough to watch for mean reversion.")
    elif Decimal("3") <= momentum_20 <= Decimal("15"):
        buy_score += 6
        sell_score -= 4
        checks.append("Momentum is positive without looking fully vertical.")
    elif momentum_20 < Decimal("-3"):
        buy_score -= 6
        sell_score += 8
        sell_checks.append("Sell pressure: downside momentum is active.")

    buy_score += context.sentiment_score * 2
    sell_score -= context.sentiment_score * 2
    if context.news_bias == "bullish":
        buy_score += 6
        sell_score -= 6
        checks.append("News-cycle bias is supportive.")
    elif context.news_bias == "bearish":
        buy_score -= 10
        sell_score += 10
        checks.append("News-cycle bias is hostile; reduce or skip risk.")
        sell_checks.append("Sell pressure: news-cycle bias is hostile.")
    else:
        checks.append("News-cycle bias is neutral.")

    if context.event_risk == "extreme":
        buy_score -= 25
        sell_score += 18
        checks.append("Extreme event risk: veteran mode steps back first.")
        sell_checks.append("Sell pressure: extreme event risk favors reducing exposure.")
    elif context.event_risk == "elevated":
        buy_score -= 10
        sell_score += 8
        checks.append("Event risk is elevated; position size must stay small.")
        sell_checks.append("Sell pressure: elevated event risk favors defense.")
    else:
        checks.append("Event risk is low.")

    penalty = _headline_penalty(context.headlines)
    if penalty:
        buy_score -= penalty
        sell_score += min(penalty, 15)
        checks.append("Headline text contains hype or hazard terms; score was penalized.")
        sell_checks.append("Sell pressure: headline hazard terms favor reducing exposure.")

    buy_score = max(0, min(100, buy_score))
    sell_score = max(0, min(100, sell_score))
    decision: Decision = "NO_TRADE"
    score = max(buy_score, sell_score)
    if sell_score >= 62 and sell_score > buy_score + 5:
        decision = "SELL"
        checks = [*sell_checks, *checks]
    elif buy_score >= 68 and context.event_risk != "extreme":
        decision = "BUY"

    quote_size = min(context.bankroll_usd, Decimal("10")).quantize(
        Decimal("0.01"), rounding=ROUND_DOWN
    )
    base_size = None
    if decision == "SELL" and context.base_inventory:
        base_size = min(context.base_inventory, context.base_inventory * Decimal("0.33"))
        base_size = base_size.quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)

    if context.bankroll_usd < Decimal("10"):
        checks.append("Challenge bankroll is below $10; size is constrained to available paper capital.")
        quote_size = context.bankroll_usd.quantize(Decimal("0.01"), rounding=ROUND_DOWN)

    if decision == "SELL" and not base_size:
        proposal = None
        rationale = (
            f"Sell is the stronger signal at {sell_score}/100, but no base inventory "
            "was provided or detected, so no executable Robinhood sell order was created."
        )
        checks.append("Sell recommendation is informational until base inventory is available.")
    elif decision == "NO_TRADE":
        proposal = None
        rationale = "No trade. Neither buy nor sell cleared the directional setup filters."
    else:
        proposal = {
            "product_id": context.product_id,
            "side": decision,
            "quote_size": str(quote_size),
            "base_size": str(base_size) if base_size is not None else None,
            "rationale": (
                f"Challenge radar {decision}: score {score}/100, "
                f"{_confidence_label(score)}. "
                "This is a high-risk small-account challenge idea, not a guarantee."
            ),
        }
        rationale = proposal["rationale"]

    return {
        "decision": decision,
        "score": score,
        "buy_score": buy_score,
        "sell_score": sell_score,
        "confidence": _confidence_label(score),
        "rationale": rationale,
        "checks": checks,
        "metrics": {
            "last_price": str(last),
            "ema9": str(ema9.quantize(Decimal("0.01"), rounding=ROUND_DOWN)),
            "ema21": str(ema21.quantize(Decimal("0.01"), rounding=ROUND_DOWN)),
            "ema50": str(ema50.quantize(Decimal("0.01"), rounding=ROUND_DOWN)),
            "rsi14": str(rsi14.quantize(Decimal("0.1"), rounding=ROUND_DOWN)),
            "atr_percent": str(atr_pct.quantize(Decimal("0.1"), rounding=ROUND_DOWN)),
            "volume_ratio": str(volume_ratio.quantize(Decimal("0.01"), rounding=ROUND_DOWN)),
            "momentum_20": str(momentum_20.quantize(Decimal("0.1"), rounding=ROUND_DOWN)),
            "drawdown_20": str(drawdown_20.quantize(Decimal("0.1"), rounding=ROUND_DOWN)),
        },
        "proposal": proposal,
    }
