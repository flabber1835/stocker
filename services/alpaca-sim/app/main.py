"""
Alpaca paper-trading simulator.

Mimics the subset of Alpaca's REST API the rest of the system depends on:
  GET    /v2/account        — account state (equity, buying_power, cash)
  GET    /v2/positions      — current positions
  POST   /v2/orders         — submit an order, fills immediately at last DB price
  GET    /v2/orders         — list submitted orders
  DELETE /v2/orders         — cancel pending orders (no-op: orders fill on submit)

Admin endpoints (not present on real Alpaca, used for test seeding):
  POST /admin/reset                      — wipe state
  POST /admin/seed                       — set cash + initial positions
  POST /admin/set-as-of-date             — pin the "now" date used for prices
  GET  /admin/state                      — dump full internal state

State lives in-process (single instance only — fine for a simulator).
Prices come from the shared Postgres daily_prices table.
"""
from __future__ import annotations

import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

log = logging.getLogger("alpaca-sim")
logging.basicConfig(level=logging.INFO, format="[alpaca-sim] %(message)s")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+asyncpg://stocker:stocker@postgres:5432/stocker",
)

engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


# ── In-memory state ───────────────────────────────────────────────────────────


class _Position:
    __slots__ = ("ticker", "qty", "avg_entry_price", "cost_basis")

    def __init__(self, ticker: str, qty: float, avg_entry_price: float) -> None:
        self.ticker = ticker
        self.qty = qty
        self.avg_entry_price = avg_entry_price
        self.cost_basis = qty * avg_entry_price

    def apply_buy(self, qty: float, price: float) -> None:
        new_qty = self.qty + qty
        self.avg_entry_price = (self.cost_basis + qty * price) / new_qty
        self.qty = new_qty
        self.cost_basis = self.qty * self.avg_entry_price

    def apply_sell(self, qty: float) -> None:
        self.qty -= qty
        self.cost_basis = self.qty * self.avg_entry_price


class _State:
    def __init__(self) -> None:
        self.cash: float = 100_000.0
        self.positions: dict[str, _Position] = {}
        self.orders: list[dict[str, Any]] = []
        self.as_of_date: Optional[date] = None  # if set, prices clamped to this date

    def reset(self) -> None:
        self.cash = 100_000.0
        self.positions.clear()
        self.orders.clear()
        self.as_of_date = None


STATE = _State()


# ── Price lookup ──────────────────────────────────────────────────────────────


async def _last_price(ticker: str) -> Optional[float]:
    """Return the most recent adjusted_close at or before as_of_date (if pinned)."""
    sql = (
        "SELECT adjusted_close FROM daily_prices "
        "WHERE ticker = :t "
        + ("AND date <= :d " if STATE.as_of_date else "")
        + "ORDER BY date DESC LIMIT 1"
    )
    params: dict[str, Any] = {"t": ticker}
    if STATE.as_of_date:
        params["d"] = STATE.as_of_date
    async with SessionLocal() as db:
        row = (await db.execute(text(sql), params)).first()
    return float(row[0]) if row else None


# ── Order math ────────────────────────────────────────────────────────────────


async def _fill_order(order: dict[str, Any]) -> dict[str, Any]:
    """Mutate STATE to reflect a market fill. Returns the updated order dict."""
    ticker = order["symbol"]
    qty = float(order["qty"])
    side = order["side"]

    price = await _last_price(ticker)
    if price is None or price <= 0:
        order["status"] = "rejected"
        order["failed_at"] = datetime.now(timezone.utc).isoformat()
        order["reject_reason"] = f"no price for {ticker}"
        return order

    if side == "buy":
        cost = qty * price
        if cost > STATE.cash + 1e-6:
            order["status"] = "rejected"
            order["reject_reason"] = (
                f"insufficient cash: need ${cost:,.2f}, have ${STATE.cash:,.2f}"
            )
            return order
        STATE.cash -= cost
        pos = STATE.positions.get(ticker)
        if pos is None:
            STATE.positions[ticker] = _Position(ticker, qty, price)
        else:
            pos.apply_buy(qty, price)
    else:  # sell
        pos = STATE.positions.get(ticker)
        if pos is None or pos.qty < qty - 1e-6:
            order["status"] = "rejected"
            order["reject_reason"] = (
                f"insufficient shares: have {pos.qty if pos else 0}, need {qty}"
            )
            return order
        proceeds = qty * price
        STATE.cash += proceeds
        pos.apply_sell(qty)
        if pos.qty <= 1e-6:
            del STATE.positions[ticker]

    now = datetime.now(timezone.utc).isoformat()
    order["status"] = "filled"
    order["filled_at"] = now
    order["filled_qty"] = str(qty)
    order["filled_avg_price"] = f"{price:.4f}"
    order["updated_at"] = now
    return order


# ── App ───────────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(_: FastAPI):
    log.info("starting (database_url=%s)", DATABASE_URL.split("@")[-1])
    yield


app = FastAPI(title="alpaca-sim", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "alpaca-sim",
        "cash": STATE.cash,
        "position_count": len(STATE.positions),
        "order_count": len(STATE.orders),
        "as_of_date": STATE.as_of_date.isoformat() if STATE.as_of_date else None,
    }


# ── Alpaca-shaped endpoints ───────────────────────────────────────────────────


@app.get("/v2/account")
async def get_account() -> dict[str, Any]:
    total_mv = 0.0
    for pos in STATE.positions.values():
        p = await _last_price(pos.ticker)
        if p is not None:
            total_mv += pos.qty * p
    equity = STATE.cash + total_mv
    return {
        "id": "sim-account",
        "account_number": "SIM000001",
        "status": "ACTIVE",
        "currency": "USD",
        "cash": f"{STATE.cash:.2f}",
        "buying_power": f"{STATE.cash:.2f}",
        "equity": f"{equity:.2f}",
        "portfolio_value": f"{equity:.2f}",
        "last_equity": f"{equity:.2f}",
        "long_market_value": f"{total_mv:.2f}",
        "short_market_value": "0.00",
        "trading_blocked": False,
        "transfers_blocked": False,
        "account_blocked": False,
        "pattern_day_trader": False,
        "created_at": "2024-01-01T00:00:00Z",
    }


@app.get("/v2/positions")
async def get_positions() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for pos in STATE.positions.values():
        p = await _last_price(pos.ticker)
        if p is None:
            p = pos.avg_entry_price
        mv = pos.qty * p
        upl = mv - pos.cost_basis
        upl_pct = upl / pos.cost_basis if pos.cost_basis > 0 else 0.0
        out.append({
            "asset_id": f"sim-{pos.ticker}",
            "symbol": pos.ticker,
            "exchange": "SIM",
            "asset_class": "us_equity",
            "qty": f"{pos.qty}",
            "avg_entry_price": f"{pos.avg_entry_price:.4f}",
            "side": "long",
            "market_value": f"{mv:.2f}",
            "cost_basis": f"{pos.cost_basis:.2f}",
            "unrealized_pl": f"{upl:.2f}",
            "unrealized_plpc": f"{upl_pct:.6f}",
            "unrealized_intraday_pl": f"{upl:.2f}",
            "unrealized_intraday_plpc": f"{upl_pct:.6f}",
            "current_price": f"{p:.4f}",
            "lastday_price": f"{p:.4f}",
            "change_today": "0.0",
        })
    return out


class _OrderIn(BaseModel):
    symbol: str
    qty: Optional[float] = None
    notional: Optional[float] = None
    side: str  # 'buy' or 'sell'
    type: str = "market"
    time_in_force: str = "day"
    extended_hours: bool = False
    client_order_id: Optional[str] = None
    order_class: Optional[str] = None


@app.post("/v2/orders", status_code=201)
async def submit_order(req: _OrderIn) -> dict[str, Any]:
    if req.side not in ("buy", "sell"):
        raise HTTPException(status_code=422, detail="side must be buy or sell")
    if req.type != "market":
        raise HTTPException(status_code=422, detail="only market orders supported")

    qty = req.qty
    if qty is None and req.notional is not None:
        price = await _last_price(req.symbol)
        if price is None:
            raise HTTPException(status_code=422, detail=f"no price for {req.symbol}")
        qty = req.notional / price
    if qty is None or qty <= 0:
        raise HTTPException(status_code=422, detail="qty must be > 0")

    now = datetime.now(timezone.utc).isoformat()
    order: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "client_order_id": req.client_order_id or str(uuid.uuid4()),
        "created_at": now,
        "updated_at": now,
        "submitted_at": now,
        "filled_at": None,
        "expired_at": None,
        "canceled_at": None,
        "failed_at": None,
        "asset_id": f"sim-{req.symbol}",
        "symbol": req.symbol,
        "asset_class": "us_equity",
        "qty": str(qty),
        "filled_qty": "0",
        "filled_avg_price": None,
        "order_class": req.order_class or "",
        "order_type": req.type,
        "type": req.type,
        "side": req.side,
        "time_in_force": req.time_in_force,
        "status": "accepted",
        "extended_hours": req.extended_hours,
    }

    # Fill synchronously — MOO semantics are collapsed for simulation simplicity
    await _fill_order(order)
    STATE.orders.append(order)

    if order["status"] == "rejected":
        # Real Alpaca returns 422 with a JSON detail when an order is unfillable;
        # keep the order recorded so /v2/orders reflects the rejection.
        raise HTTPException(
            status_code=422,
            detail={"message": order.get("reject_reason", "rejected"), "order_id": order["id"]},
        )

    return order


@app.get("/v2/orders")
async def list_orders(
    status: str = "open",
    limit: int = 50,
    direction: str = "desc",
) -> list[dict[str, Any]]:
    orders = STATE.orders
    if status == "open":
        orders = [o for o in orders if o["status"] in ("accepted", "new", "pending_new", "partially_filled")]
    elif status == "closed":
        orders = [o for o in orders if o["status"] in ("filled", "canceled", "expired", "rejected")]
    # status='all' returns everything
    sorted_orders = sorted(orders, key=lambda o: o["created_at"], reverse=(direction == "desc"))
    return sorted_orders[:limit]


@app.delete("/v2/orders")
async def cancel_all_orders() -> list[dict[str, Any]]:
    """Cancel pending orders. Since orders fill on submit, there's nothing to cancel."""
    return []


# ── Admin endpoints (not on real Alpaca) ──────────────────────────────────────


class _SeedIn(BaseModel):
    cash: float = Field(..., ge=0)
    positions: dict[str, float] = Field(
        default_factory=dict,
        description="Map of ticker → qty for initial positions",
    )


@app.post("/admin/reset")
async def admin_reset() -> dict[str, str]:
    STATE.reset()
    log.info("state reset")
    return {"status": "reset"}


@app.post("/admin/seed")
async def admin_seed(req: _SeedIn) -> dict[str, Any]:
    """Seed the simulator with starting cash + positions.

    Positions are entered at the most-recent seeded DB price (or the as_of_date
    price if pinned via /admin/set-as-of-date). Replaces any existing state.
    """
    STATE.reset()
    STATE.cash = req.cash
    seeded: list[dict[str, Any]] = []
    for ticker, qty in req.positions.items():
        if qty <= 0:
            continue
        p = await _last_price(ticker)
        if p is None:
            log.warning("seed: no price for %s — skipping", ticker)
            continue
        STATE.positions[ticker] = _Position(ticker, float(qty), float(p))
        seeded.append({"ticker": ticker, "qty": qty, "entry_price": p})
    log.info("seeded cash=$%.2f positions=%d", req.cash, len(seeded))
    return {"cash": STATE.cash, "positions": seeded}


class _AsOfIn(BaseModel):
    as_of_date: Optional[str] = None  # ISO date, or null to clear


@app.post("/admin/set-as-of-date")
async def admin_set_as_of(req: _AsOfIn) -> dict[str, Any]:
    if req.as_of_date is None or req.as_of_date == "":
        STATE.as_of_date = None
    else:
        STATE.as_of_date = date.fromisoformat(req.as_of_date)
    log.info("as_of_date=%s", STATE.as_of_date)
    return {"as_of_date": STATE.as_of_date.isoformat() if STATE.as_of_date else None}


@app.get("/admin/state")
async def admin_state() -> dict[str, Any]:
    return {
        "cash": STATE.cash,
        "as_of_date": STATE.as_of_date.isoformat() if STATE.as_of_date else None,
        "positions": {
            t: {"qty": p.qty, "avg_entry_price": p.avg_entry_price, "cost_basis": p.cost_basis}
            for t, p in STATE.positions.items()
        },
        "orders": STATE.orders,
    }
