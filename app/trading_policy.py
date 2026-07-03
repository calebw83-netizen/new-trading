from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Policy:
    allowed_products: set[str]
    max_order_quote_usd: Decimal
    daily_quote_limit_usd: Decimal


def evaluate_order(
    *,
    product_id: str,
    side: str,
    quote_size: Decimal,
    policy: Policy,
    spent_today: Decimal,
) -> tuple[bool, list[str]]:
    checks: list[str] = []
    ok = True

    if product_id.upper() not in policy.allowed_products:
        ok = False
        checks.append(f"Blocked: {product_id} is not in ALLOWED_PRODUCTS.")
    else:
        checks.append(f"Product allowed: {product_id}.")

    if quote_size > policy.max_order_quote_usd:
        ok = False
        checks.append(
            f"Blocked: order size ${quote_size} exceeds per-order cap "
            f"${policy.max_order_quote_usd}."
        )
    else:
        checks.append(f"Order size within per-order cap: ${quote_size}.")

    if side.upper() == "BUY":
        projected = spent_today + quote_size
        if projected > policy.daily_quote_limit_usd:
            ok = False
            checks.append(
                f"Blocked: daily buy total would be ${projected}, above "
                f"${policy.daily_quote_limit_usd}."
            )
        else:
            checks.append(f"Daily buy total after this order: ${projected}.")
    else:
        checks.append(f"Daily buy cap unchanged by this sell: ${spent_today}.")

    return ok, checks
