"""
Alpaca paper-trading simulator.

Mimics the subset of Alpaca's REST API the rest of the system depends on:
  GET    /v2/account        — account state (equity, buying_power, cash)
  GET    /v2/positions      — current positions
  POST   /v2/orders         — submit an order. market orders fill immediately at
                              the last DB price; trailing_stop sells rest open and
                              fill when price falls trail_percent below their HWM
                              (evaluated each time the clock advances)
  GET    /v2/orders         — list submitted orders
  DELETE /v2/orders         — cancel pending orders (no-op: market orders fill on submit)

Admin endpoints (not present on real Alpaca, used for test seeding):
  POST /admin/reset                      — wipe state
  POST /admin/seed                       — set cash + initial positions
  POST /admin/set-as-of-date             — pin the "now" date used for prices
  GET  /admin/state                      — dump full internal state
  POST /admin/restore-state              — restore state from a prior snapshot

State lives in-process (single instance only — fine for a simulator).
Prices come from the shared Postgres daily_prices table.
"""
from __future__ import annotations

import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.trailing import TrailingStopState, arm

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


class _TrailingStop:
    """An open sell trailing stop tied to an order. `state` is the pure tracker."""
    __slots__ = ("order_id", "ticker", "qty", "state")

    def __init__(self, order_id: str, ticker: str, qty: float, state: TrailingStopState) -> None:
        self.order_id = order_id
        self.ticker = ticker
        self.qty = qty
        self.state = state


class _State:
    def __init__(self) -> None:
        self.cash: float = 100_000.0
        self.positions: dict[str, _Position] = {}
        self.orders: list[dict[str, Any]] = []
        self.as_of_date: Optional[date] = None  # if set, prices clamped to this date
        self.trailing_stops: list[_TrailingStop] = []  # open sell trailing stops

    def reset(self) -> None:
        self.cash = 100_000.0
        self.positions.clear()
        self.orders.clear()
        self.as_of_date = None
        self.trailing_stops.clear()


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
    trail_percent: Optional[float] = None  # required for type='trailing_stop'


@app.post("/v2/orders", status_code=201)
async def submit_order(req: _OrderIn) -> dict[str, Any]:
    if req.side not in ("buy", "sell"):
        raise HTTPException(status_code=422, detail="side must be buy or sell")
    if req.type not in ("market", "trailing_stop"):
        raise HTTPException(
            status_code=422, detail="only market and trailing_stop orders supported"
        )

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
        "trail_percent": req.trail_percent,
        "hwm": None,
    }

    if req.type == "trailing_stop":
        # A trailing stop is a *resting* order: it does NOT fill on submit. It is
        # armed at the current price and only fills later when the price falls
        # trail_percent below its high-water mark. The HWM is advanced (and the
        # trigger checked) every time the simulation clock moves forward via
        # POST /admin/set-as-of-date.
        if req.side != "sell":
            raise HTTPException(status_code=422, detail="trailing_stop must be a sell")
        if not req.trail_percent or req.trail_percent <= 0:
            raise HTTPException(status_code=422, detail="trailing_stop needs trail_percent > 0")
        price = await _last_price(req.symbol)
        if price is None:
            raise HTTPException(status_code=422, detail=f"no price for {req.symbol}")
        order["status"] = "new"  # open / resting
        order["hwm"] = price
        STATE.orders.append(order)
        STATE.trailing_stops.append(
            _TrailingStop(order["id"], req.symbol, float(qty), arm(req.trail_percent, price))
        )
        log.info("armed trailing stop %s %s qty=%.4g trail=%.2f%% @ $%.4f",
                 order["id"][:8], req.symbol, qty, req.trail_percent, price)
        return order

    # Market order: fill synchronously — MOO semantics collapsed for simulation.
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


async def _evaluate_trailing_stops() -> list[dict[str, Any]]:
    """Advance every open trailing stop to the current as-of price and fill any
    that have triggered (or cancel any whose position has since been closed).

    Called whenever the simulation clock moves (set-as-of-date) so resting stops
    react to each new day's close. Returns the list of orders that filled.
    """
    if not STATE.trailing_stops:
        return []
    filled: list[dict[str, Any]] = []
    still_open: list[_TrailingStop] = []
    for ts in STATE.trailing_stops:
        order = next((o for o in STATE.orders if o["id"] == ts.order_id), None)
        pos = STATE.positions.get(ts.ticker)
        # Cancel if the underlying position is gone (system already exited it).
        if pos is None or pos.qty <= 1e-6:
            if order is not None:
                order["status"] = "canceled"
                order["canceled_at"] = datetime.now(timezone.utc).isoformat()
            continue
        price = await _last_price(ts.ticker)
        if price is None:
            still_open.append(ts)
            continue
        sell_qty = min(ts.qty, pos.qty)
        if ts.state.update(price):
            # Triggered → market sell at the current price.
            proceeds = sell_qty * price
            STATE.cash += proceeds
            pos.apply_sell(sell_qty)
            if pos.qty <= 1e-6:
                STATE.positions.pop(ts.ticker, None)
            now = datetime.now(timezone.utc).isoformat()
            if order is not None:
                order.update({
                    "status": "filled", "filled_at": now, "updated_at": now,
                    "filled_qty": str(sell_qty), "filled_avg_price": f"{price:.4f}",
                    "hwm": ts.state.hwm,
                })
                filled.append(order)
            log.info("trailing stop FILLED %s qty=%.4g @ $%.4f (hwm=$%.4f stop=$%.4f)",
                     ts.ticker, sell_qty, price, ts.state.hwm, ts.state.stop_price)
        else:
            if order is not None:
                order["hwm"] = ts.state.hwm
            still_open.append(ts)
    STATE.trailing_stops = still_open
    return filled


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


@app.get("/v2/orders/{order_id}")
async def get_order(order_id: str) -> dict[str, Any]:
    """Fetch a single order by id — used by the trade-executor drain to poll sell
    fills before releasing buys. Market orders fill on submit, so this returns
    status='filled' for any submitted order."""
    for o in STATE.orders:
        if str(o.get("id")) == order_id:
            return o
    raise HTTPException(status_code=404, detail=f"order {order_id} not found")


@app.get("/v2/clock")
async def get_clock() -> dict[str, Any]:
    """Market clock. The sim is always 'open' so the drain submits immediately in
    tests; next_open/next_close are nominal stamps for deferral arithmetic."""
    now = datetime.now(timezone.utc)
    return {
        "timestamp": now.isoformat(),
        "is_open": True,
        "next_open": (now + timedelta(hours=12)).isoformat(),
        "next_close": (now + timedelta(hours=6)).isoformat(),
    }


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
    # Advancing the clock makes resting trailing stops react to the new day's close.
    triggered = await _evaluate_trailing_stops()
    return {
        "as_of_date": STATE.as_of_date.isoformat() if STATE.as_of_date else None,
        "trailing_stops_filled": [o["id"] for o in triggered],
    }


class _LiquidateIn(BaseModel):
    ticker: str


@app.post("/admin/liquidate-position")
async def admin_liquidate_position(req: _LiquidateIn) -> dict[str, Any]:
    """Sell the entire position at the most-recent price, add proceeds to cash.

    Simulates a manual liquidation outside the pipeline (e.g. operator clicks
    "sell all" at the broker directly). The system's next alpaca-sync run will
    observe the position is gone.
    """
    pos = STATE.positions.get(req.ticker)
    if pos is None:
        return {"status": "no_position", "ticker": req.ticker}
    price = await _last_price(req.ticker)
    if price is None or price <= 0:
        return {"status": "no_price", "ticker": req.ticker}
    qty = pos.qty
    proceeds = qty * price
    STATE.cash += proceeds
    del STATE.positions[req.ticker]
    log.info("liquidated %s qty=%.2f @ $%.4f → proceeds=$%.2f, cash=$%.2f",
             req.ticker, qty, price, proceeds, STATE.cash)
    return {
        "status": "liquidated",
        "ticker": req.ticker,
        "qty": qty,
        "price": price,
        "proceeds": proceeds,
        "cash_after": STATE.cash,
    }


class _WithdrawIn(BaseModel):
    amount: Optional[float] = None  # if None or > cash, withdraws all


@app.post("/admin/withdraw-cash")
async def admin_withdraw_cash(req: _WithdrawIn) -> dict[str, Any]:
    """Withdraw cash from the simulator (operator moves money out of brokerage).

    Subtracts `amount` (clamped to current cash) from STATE.cash. Pass
    amount=None or any amount >= cash to drain to exactly $0.
    """
    cash_before = STATE.cash
    amount = req.amount if req.amount is not None else cash_before
    amount = min(max(amount, 0.0), cash_before)
    STATE.cash -= amount
    if STATE.cash < 1e-6:
        STATE.cash = 0.0
    log.info("withdraw cash=$%.2f → remaining=$%.2f", amount, STATE.cash)
    return {
        "status": "withdrawn",
        "amount": amount,
        "cash_before": cash_before,
        "cash_after": STATE.cash,
    }


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


class _RestoreIn(BaseModel):
    cash: float
    as_of_date: Optional[str] = None
    positions: dict[str, dict[str, float]] = Field(default_factory=dict)


@app.post("/admin/restore-state")
async def admin_restore_state(req: _RestoreIn) -> dict[str, Any]:
    """Restore full simulator state from a prior snapshot (from GET /admin/state).

    Used by the test harness to preserve broker state across simulated internet
    outages: snapshot before stopping, restore after restarting.
    """
    STATE.cash = req.cash
    STATE.as_of_date = date.fromisoformat(req.as_of_date) if req.as_of_date else None
    STATE.positions.clear()
    for ticker, pd in req.positions.items():
        pos = _Position(ticker, pd["qty"], pd["avg_entry_price"])
        pos.cost_basis = pd.get("cost_basis", pos.cost_basis)
        STATE.positions[ticker] = pos
    log.info("state restored: cash=$%.2f positions=%d", STATE.cash, len(STATE.positions))
    return {"status": "restored", "cash": STATE.cash, "positions": len(STATE.positions)}
