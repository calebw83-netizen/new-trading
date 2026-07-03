from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.audit import AuditLog
from app.config import get_settings
from app.models import (
    ApiResult,
    ExecuteOrderRequest,
    NewsRequest,
    StrategyRequest,
    StrategyScanRequest,
    TradeProposal,
    TradeProposalRequest,
)
from app.news import fetch_market_news, headlines_text, infer_news_state
from app.robinhood_client import RobinhoodBridge
from app.strategy import StrategyContext, analyze_setup
from app.trading_policy import Policy, evaluate_order


ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"

app = FastAPI(title="Robinhood Trading Bridge")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

_AUTOPILOT_TASK: asyncio.Task[None] | None = None
_AUTOPILOT_STATE: dict[str, Any] = {
    "enabled": False,
    "running": False,
    "cycle_count": 0,
    "last_started_at": None,
    "last_finished_at": None,
    "next_run_at": None,
    "last_result": None,
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _autopilot_config() -> dict[str, Any]:
    settings = get_settings()
    return {
        "enabled": settings.autopilot_enabled,
        "interval_seconds": settings.autopilot_interval_seconds,
        "bankroll_usd": str(settings.autopilot_bankroll_usd),
        "days_remaining": settings.autopilot_days_remaining,
        "max_products": settings.autopilot_max_products,
        "auto_execute_enabled": settings.auto_execute_enabled,
        "auto_execute_min_score": settings.auto_execute_min_score,
        "live_trading_enabled": settings.live_trading_enabled,
        "mode": settings.broker_mode,
    }


def _summarize_autopilot_result(result: ApiResult, action: str) -> dict[str, Any]:
    data = result.data if isinstance(result.data, dict) else {}
    scan = data.get("scan") if isinstance(data.get("scan"), dict) else data
    best = scan.get("best", {}) if isinstance(scan, dict) else {}
    proposal = data.get("proposal") if isinstance(data.get("proposal"), dict) else best.get("proposal")
    return {
        "ok": result.ok,
        "action": action,
        "mode": result.mode,
        "product_id": best.get("product_id") or (proposal or {}).get("product_id"),
        "side": best.get("decision") or (proposal or {}).get("side"),
        "score": best.get("score"),
        "message": result.message,
    }


async def _run_autopilot_cycle() -> None:
    settings = get_settings()
    audit = AuditLog(settings.audit_db_path)
    request = StrategyScanRequest(
        bankroll_usd=settings.autopilot_bankroll_usd,
        days_remaining=settings.autopilot_days_remaining,
        max_products=settings.autopilot_max_products,
    )
    _AUTOPILOT_STATE["running"] = True
    _AUTOPILOT_STATE["cycle_count"] = int(_AUTOPILOT_STATE["cycle_count"]) + 1
    _AUTOPILOT_STATE["last_started_at"] = _utc_now()
    _AUTOPILOT_STATE["next_run_at"] = None
    try:
        if settings.auto_execute_enabled:
            result = await asyncio.to_thread(strategy_auto_execute, request)
            summary = _summarize_autopilot_result(result, "auto_execute")
        else:
            result = await asyncio.to_thread(strategy_scan, request)
            summary = _summarize_autopilot_result(result, "scan_only")
        _AUTOPILOT_STATE["last_result"] = summary
        audit.record("autopilot_cycle", summary)
    except HTTPException as exc:
        blocked = {
            "ok": False,
            "action": "blocked",
            "status_code": exc.status_code,
            "detail": str(exc.detail),
        }
        _AUTOPILOT_STATE["last_result"] = blocked
        audit.record("autopilot_blocked", blocked)
    except Exception as exc:
        error = {"ok": False, "action": "error", "detail": str(exc)}
        _AUTOPILOT_STATE["last_result"] = error
        audit.record("autopilot_error", error)
    finally:
        refreshed = get_settings()
        _AUTOPILOT_STATE["running"] = False
        _AUTOPILOT_STATE["last_finished_at"] = _utc_now()
        _AUTOPILOT_STATE["next_run_at"] = (
            datetime.now(UTC) + timedelta(seconds=refreshed.autopilot_interval_seconds)
        ).isoformat()


async def _autopilot_loop() -> None:
    while True:
        settings = get_settings()
        _AUTOPILOT_STATE["enabled"] = settings.autopilot_enabled
        if not settings.autopilot_enabled:
            _AUTOPILOT_STATE["next_run_at"] = None
            return
        await _run_autopilot_cycle()
        await asyncio.sleep(settings.autopilot_interval_seconds)


@app.on_event("startup")
async def start_autopilot() -> None:
    global _AUTOPILOT_TASK
    settings = get_settings()
    _AUTOPILOT_STATE["enabled"] = settings.autopilot_enabled
    if settings.autopilot_enabled and _AUTOPILOT_TASK is None:
        _AUTOPILOT_TASK = asyncio.create_task(_autopilot_loop())


@app.on_event("shutdown")
async def stop_autopilot() -> None:
    global _AUTOPILOT_TASK
    if _AUTOPILOT_TASK is None:
        return
    _AUTOPILOT_TASK.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await _AUTOPILOT_TASK
    _AUTOPILOT_TASK = None


def _services() -> tuple[RobinhoodBridge, AuditLog, Policy]:
    settings = get_settings()
    policy = Policy(
        allowed_products=settings.allowed_products,
        max_order_quote_usd=settings.max_order_quote_usd,
        daily_quote_limit_usd=settings.daily_quote_limit_usd,
    )
    return RobinhoodBridge(settings), AuditLog(settings.audit_db_path), policy


def _account_inventory(bridge: RobinhoodBridge) -> dict[str, Decimal]:
    inventory: dict[str, Decimal] = {}
    try:
        holdings = bridge.holdings()
        for item in holdings.get("results", []):
            currency = str(
                item.get("asset_code")
                or item.get("currency")
                or item.get("symbol", "").split("-")[0]
            ).upper()
            value = (
                item.get("available_quantity")
                or item.get("quantity")
                or item.get("total_quantity")
                or item.get("amount")
            )
            if currency and value is not None:
                inventory[currency] = Decimal(str(value))
    except Exception:
        pass
    try:
        data = bridge.accounts()
    except Exception:
        return inventory
    for account in data.get("accounts", []):
        currency = str(account.get("currency", "")).upper()
        balance = account.get("available_balance", {})
        value = balance.get("value") if isinstance(balance, dict) else None
        if currency and value is not None:
            try:
                inventory[currency] = Decimal(str(value))
            except Exception:
                continue
    return inventory


def _build_proposal(
    bridge: RobinhoodBridge,
    audit: AuditLog,
    policy: Policy,
    request: TradeProposalRequest,
    *,
    event_type: str = "proposal",
) -> TradeProposal:
    spent_today = audit.spent_today()
    ok, checks = evaluate_order(
        product_id=request.product_id,
        side=request.side,
        quote_size=request.quote_size,
        policy=policy,
        spent_today=spent_today,
    )
    proposal = TradeProposal(
        client_order_id=f"rh-bridge-{uuid.uuid4().hex}",
        product_id=request.product_id,
        side=request.side,
        quote_size=request.quote_size,
        base_size=request.base_size,
        rationale=request.rationale,
        status="approved" if ok else "blocked",
        checks=checks,
    )
    audit.record(event_type, {"proposal": proposal.model_dump(mode="json")})
    return proposal


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/status", response_model=ApiResult)
def status() -> ApiResult:
    settings = get_settings()
    return ApiResult(
        ok=True,
        mode=settings.broker_mode,
        data={
            "has_credentials": settings.has_credentials,
            "live_trading_enabled": settings.live_trading_enabled,
            "allowed_products": sorted(settings.allowed_products),
            "max_order_quote_usd": str(settings.max_order_quote_usd),
            "daily_quote_limit_usd": str(settings.daily_quote_limit_usd),
            "require_confirmation": settings.require_confirmation,
            "news_feeds": settings.news_feeds,
            "scan_quote_currency": settings.scan_quote_currency,
            "scan_max_products": settings.scan_max_products,
            "scan_asset_classes": sorted(settings.scan_asset_classes),
            "scan_stock_symbols": settings.scan_stock_symbols,
            "auto_execute_enabled": settings.auto_execute_enabled,
            "auto_execute_min_score": settings.auto_execute_min_score,
            "autopilot": {
                **_autopilot_config(),
                "running": _AUTOPILOT_STATE["running"],
                "cycle_count": _AUTOPILOT_STATE["cycle_count"],
                "last_started_at": _AUTOPILOT_STATE["last_started_at"],
                "last_finished_at": _AUTOPILOT_STATE["last_finished_at"],
                "next_run_at": _AUTOPILOT_STATE["next_run_at"],
                "last_result": _AUTOPILOT_STATE["last_result"],
            },
        },
    )


@app.get("/api/autopilot", response_model=ApiResult)
def autopilot_status() -> ApiResult:
    settings = get_settings()
    return ApiResult(
        ok=True,
        mode=settings.broker_mode,
        data={
            **_autopilot_config(),
            "running": _AUTOPILOT_STATE["running"],
            "cycle_count": _AUTOPILOT_STATE["cycle_count"],
            "last_started_at": _AUTOPILOT_STATE["last_started_at"],
            "last_finished_at": _AUTOPILOT_STATE["last_finished_at"],
            "next_run_at": _AUTOPILOT_STATE["next_run_at"],
            "last_result": _AUTOPILOT_STATE["last_result"],
        },
    )


@app.get("/api/accounts", response_model=ApiResult)
def accounts() -> ApiResult:
    bridge, _, _ = _services()
    try:
        return ApiResult(ok=True, mode=bridge.settings.broker_mode, data=bridge.accounts())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/products/{product_id}", response_model=ApiResult)
def product(product_id: str) -> ApiResult:
    bridge, _, _ = _services()
    try:
        return ApiResult(
            ok=True,
            mode=bridge.settings.broker_mode,
            data=bridge.product(product_id.upper()),
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/proposals", response_model=ApiResult)
def create_proposal(request: TradeProposalRequest) -> ApiResult:
    bridge, audit, policy = _services()
    proposal = _build_proposal(bridge, audit, policy, request)
    return ApiResult(
        ok=proposal.status == "approved",
        mode=bridge.settings.broker_mode,
        data=proposal.model_dump(mode="json"),
    )


@app.post("/api/strategy/analyze", response_model=ApiResult)
def strategy_analyze(request: StrategyRequest) -> ApiResult:
    bridge, audit, _ = _services()
    try:
        candles = bridge.candles(request.product_id)
        headlines = request.headlines
        news_items = []
        news_errors = []
        sentiment_score = request.sentiment_score
        news_bias = request.news_bias
        event_risk = request.event_risk
        if request.auto_fetch_news and not headlines.strip():
            news_items, news_errors = fetch_market_news(
                request.product_id,
                bridge.settings.news_feeds,
                timeout_seconds=bridge.settings.news_timeout_seconds,
            )
            headlines = headlines_text(news_items)
            if headlines:
                sentiment_score, news_bias, event_risk = infer_news_state(headlines)
        result = analyze_setup(
            candles,
            StrategyContext(
                product_id=request.product_id,
                bankroll_usd=request.bankroll_usd,
                days_remaining=request.days_remaining,
                sentiment_score=sentiment_score,
                news_bias=news_bias,
                event_risk=event_risk,
                headlines=headlines,
                base_inventory=request.base_inventory,
            ),
        )
        result["news"] = {
            "auto_fetched": request.auto_fetch_news and not request.headlines.strip(),
            "items": [item.__dict__ for item in news_items],
            "errors": news_errors,
            "sentiment_score": sentiment_score,
            "news_bias": news_bias,
            "event_risk": event_risk,
        }
        audit.record(
            "strategy_analysis",
            {
                "product_id": request.product_id,
                "side": result["decision"],
                "quote_size": result.get("proposal", {}).get("quote_size") if result.get("proposal") else "",
                "result": result,
            },
        )
        return ApiResult(ok=True, mode=bridge.settings.broker_mode, data=result)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/strategy/scan", response_model=ApiResult)
def strategy_scan(request: StrategyScanRequest) -> ApiResult:
    bridge, audit, policy = _services()
    settings = bridge.settings
    max_products = request.max_products or settings.scan_max_products
    product_ids = bridge.scan_products(settings.scan_quote_currency, max_products)
    if not product_ids:
        raise HTTPException(
            status_code=400,
            detail="No Robinhood products are available for the scanner.",
        )

    results = []
    errors = []
    inventory = _account_inventory(bridge)
    for product_id in product_ids:
        try:
            base_currency = product_id.split("-")[0].upper()
            base_inventory = request.base_inventory
            if base_inventory is None:
                base_inventory = inventory.get(base_currency)
            candles = bridge.candles(product_id)
            news_items, news_errors = fetch_market_news(
                product_id,
                settings.news_feeds,
                max_items=8,
                timeout_seconds=settings.news_timeout_seconds,
            )
            headlines = headlines_text(news_items)
            sentiment_score, news_bias, event_risk = infer_news_state(headlines)
            result = analyze_setup(
                candles,
                StrategyContext(
                    product_id=product_id,
                    bankroll_usd=request.bankroll_usd,
                    days_remaining=request.days_remaining,
                    sentiment_score=sentiment_score,
                    news_bias=news_bias,
                    event_risk=event_risk,
                    headlines=headlines,
                    base_inventory=base_inventory,
                ),
            )
            result["product_id"] = product_id
            result["base_inventory"] = str(base_inventory) if base_inventory is not None else None
            result["news"] = {
                "auto_fetched": True,
                "items": [item.__dict__ for item in news_items],
                "errors": news_errors,
                "sentiment_score": sentiment_score,
                "news_bias": news_bias,
                "event_risk": event_risk,
            }
            results.append(result)
        except Exception as exc:
            errors.append(f"{product_id}: {exc}")

    if not results:
        raise HTTPException(status_code=400, detail="Scan did not return any chart results.")

    ranked = sorted(results, key=lambda item: (item["proposal"] is not None, item["score"]), reverse=True)
    best_overall = ranked[0]
    best_allowed = next(
        (item for item in ranked if item.get("product_id") in policy.allowed_products),
        None,
    )
    best = next(
        (
            item
            for item in ranked
            if item.get("proposal") and item.get("product_id") in policy.allowed_products
        ),
        best_allowed or best_overall,
    )
    if (
        not best.get("proposal")
        and best.get("decision") != "SELL"
        and best.get("product_id") in policy.allowed_products
        and best.get("buy_score", 0) >= 55
        and best.get("news", {}).get("event_risk") != "extreme"
    ):
        quote_size = min(request.bankroll_usd, Decimal("10")).quantize(
            Decimal("0.01"), rounding=ROUND_DOWN
        )
        best["decision"] = "BUY"
        best["proposal"] = {
            "product_id": best["product_id"],
            "side": "BUY",
            "quote_size": str(quote_size),
            "base_size": None,
            "rationale": (
                f"Aggressive challenge proposal: {best['product_id']} scored "
                f"{best['score']}/100. This is below the normal A/B setup threshold, "
                "so it is sized as a tiny-account challenge idea only."
            ),
        }
        best["rationale"] = best["proposal"]["rationale"]
        best["checks"] = [
            "Aggressive challenge floor activated for a watchlist-grade setup.",
            *best.get("checks", []),
        ]
    payload = {
        "scanned_products": product_ids,
        "result_count": len(results),
        "errors": errors,
        "best": best,
        "best_overall": best_overall,
        "allowed_products": sorted(policy.allowed_products),
        "ranked": ranked[: min(8, len(ranked))],
    }
    audit.record(
        "strategy_scan",
        {
            "product_id": best.get("product_id"),
            "side": best.get("decision"),
            "quote_size": best.get("proposal", {}).get("quote_size") if best.get("proposal") else "",
            "result": payload,
        },
    )
    return ApiResult(ok=True, mode=settings.broker_mode, data=payload)


@app.post("/api/strategy/auto-execute", response_model=ApiResult)
def strategy_auto_execute(request: StrategyScanRequest) -> ApiResult:
    bridge, audit, policy = _services()
    settings = bridge.settings
    threshold = settings.auto_execute_min_score
    if not settings.auto_execute_enabled:
        raise HTTPException(
            status_code=400,
            detail="Auto execution is disabled. Set AUTO_EXECUTE_ENABLED=true in .env to opt in.",
        )
    if settings.broker_mode == "live" and not settings.live_trading_enabled:
        raise HTTPException(
            status_code=400,
            detail="Live auto execution requires ROBINHOOD_ENABLE_LIVE_TRADING=true.",
        )

    scan_result = strategy_scan(request)
    scan = scan_result.data
    if not isinstance(scan, dict):
        raise HTTPException(status_code=400, detail="Scan did not return a usable result.")
    best = scan.get("best", {})
    proposal_payload = best.get("proposal")
    if not proposal_payload:
        raise HTTPException(status_code=400, detail="Auto scan found no executable proposal.")
    if int(best.get("score", 0)) < threshold:
        raise HTTPException(
            status_code=400,
            detail=f"Best setup scored {best.get('score', 0)}/100, below auto-execute threshold {threshold}.",
        )

    proposal_request = TradeProposalRequest(**proposal_payload)
    proposal = _build_proposal(
        bridge,
        audit,
        policy,
        proposal_request,
        event_type="auto_execute_proposal",
    )
    if proposal.status != "approved":
        raise HTTPException(status_code=400, detail=" ".join(proposal.checks))

    try:
        preview = bridge.preview_market_order(proposal.model_dump(mode="json"))
        result = bridge.execute_market_order(proposal.model_dump(mode="json"))
        payload = {
            "threshold": threshold,
            "scan": scan,
            "proposal": proposal.model_dump(mode="json"),
            "preview": preview,
            "execution": result,
        }
        audit.record(
            "auto_execute",
            {
                "proposal": proposal.model_dump(mode="json"),
                "threshold": threshold,
                "scan": scan,
                "preview": preview,
                "result": result,
            },
        )
        return ApiResult(ok=True, mode=settings.broker_mode, data=payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/news", response_model=ApiResult)
def news(request: NewsRequest) -> ApiResult:
    bridge, _, _ = _services()
    try:
        items, errors = fetch_market_news(
            request.product_id,
            bridge.settings.news_feeds,
            timeout_seconds=bridge.settings.news_timeout_seconds,
        )
        score, bias, event_risk = infer_news_state(headlines_text(items))
        return ApiResult(
            ok=True,
            mode=bridge.settings.broker_mode,
            data={
                "items": [item.__dict__ for item in items],
                "errors": errors,
                "sentiment_score": score,
                "news_bias": bias,
                "event_risk": event_risk,
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/orders/preview", response_model=ApiResult)
def preview_order(request: ExecuteOrderRequest) -> ApiResult:
    bridge, audit, policy = _services()
    proposal = request.proposal
    ok, checks = evaluate_order(
        product_id=proposal.product_id,
        side=proposal.side,
        quote_size=proposal.quote_size,
        policy=policy,
        spent_today=audit.spent_today(),
    )
    if not ok:
        raise HTTPException(status_code=400, detail=" ".join(checks))
    try:
        result = bridge.preview_market_order(proposal.model_dump(mode="json"))
        audit.record(
            "preview",
            {"proposal": proposal.model_dump(mode="json"), "result": result},
        )
        return ApiResult(ok=True, mode=bridge.settings.broker_mode, data=result)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/orders/execute", response_model=ApiResult)
def execute_order(request: ExecuteOrderRequest) -> ApiResult:
    bridge, audit, policy = _services()
    settings = bridge.settings
    proposal = request.proposal
    ok, checks = evaluate_order(
        product_id=proposal.product_id,
        side=proposal.side,
        quote_size=proposal.quote_size,
        policy=policy,
        spent_today=audit.spent_today(),
    )
    if not ok:
        raise HTTPException(status_code=400, detail=" ".join(checks))
    expected = f"CONFIRM {proposal.client_order_id}"
    if settings.require_confirmation and request.confirmation.strip() != expected:
        raise HTTPException(
            status_code=400,
            detail=f'Type "{expected}" to execute this order.',
        )
    if settings.broker_mode == "live" and not settings.live_trading_enabled:
        raise HTTPException(
            status_code=400,
            detail="Live mode is selected, but live trading is disabled.",
        )
    try:
        result = bridge.execute_market_order(proposal.model_dump(mode="json"))
        audit.record(
            "live_execute" if settings.broker_mode == "live" else "paper_execute",
            {"proposal": proposal.model_dump(mode="json"), "result": result},
        )
        return ApiResult(ok=True, mode=settings.broker_mode, data=result)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/audit", response_model=ApiResult)
def audit_events() -> ApiResult:
    bridge, audit, _ = _services()
    return ApiResult(ok=True, mode=bridge.settings.broker_mode, data=audit.latest())
