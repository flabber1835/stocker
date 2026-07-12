"""IBKR implementation of `BrokerAdapter` — DORMANT until explicitly activated.

Targets the IBKR **Client Portal Web API** through a session gateway sidecar
(compose `--profile ibkr`, ibeam image): the gateway owns the hard part —
username/password + 2FA login, session keepalive, re-auth — and exposes the
CP REST API on `IBKR_GATEWAY_URL`. This adapter is pure transport+normalization
against that gateway; it holds NO IBKR username/password (those live only in the
sidecar's env).

Dormancy (three independent layers, all default-off):
  1. `BROKER` defaults to `alpaca` — the factory never constructs this class.
  2. The gateway sidecar is behind `--profile ibkr` — plain `up` never starts it.
  3. `has_credentials()` is False while IBKR_GATEWAY_URL / IBKR_ACCOUNT_ID are
     unset — even a mis-set BROKER=ibkr short-circuits to no-op, exactly like
     the empty-ALPACA_API_KEY path.

IBKR-specific translations this adapter centralizes (see
docs/service-boundaries.md "Broker abstraction — IBKR"):
  - conid resolution: CP orders take CONTRACT IDS, not symbols. Resolved via
    /iserver/secdef/search (STK section preferred), cached per process.
  - reply confirmations: order submission can return "question" prompts that
    must be acknowledged before the order exists; benign ones are auto-confirmed
    via /iserver/reply/{id} (bounded loop).
  - close_position: CP has no close endpoint — synthesized as a full-qty MKT
    SELL of the LIVE gateway-reported position (fresh read, not the DB).
  - cancel_all_orders: CP has no cancel-all — working orders are listed and
    cancelled one by one; the result is synthesized into the same
    (207, [{id, status}], text) multi-status shape trade-executor already
    consumes for Alpaca.
  - get_order: normalized to the ALPACA-SHAPED dict the fill reconciler reads
    (status/filled_qty/filled_avg_price/filled_at) — that consumer contract
    predates the abstraction.
  - list_orders: the CP `order_ref` (our client_order_id echo) is injected into
    `raw["client_order_id"]` so the reaper's reconcile-by-client_order_id works
    unchanged.
  - symbology: system form is AV's HYPHEN (BRK-B); IBKR class shares use a
    SPACE (BRK B). Blanket hyphen↔space swap at the boundary, mirroring the
    Alpaca dot swap.
  - get_clock: CP has no clock endpoint. Regular NYSE hours are computed
    locally (ET, Mon–Fri 09:30–16:00) with NO holiday calendar — ACTIVATION
    ITEM: wire a holiday source before going live. Contained risk: a holiday
    misread as "open" only makes an immediate approval submit inline instead of
    draining; DAY orders queue at IBKR until the next real session either way.

Status vocabulary (CP): PendingSubmit / PreSubmitted / Submitted / PendingCancel
stay open (→ None); Filled / Cancelled / ApiCancelled / Inactive are terminal.
`Inactive` means rejected-or-not-eligible → `failed`. CP reports partial fills
as still-`Submitted` with a filledQuantity, so `partial_fill` is never emitted
here — a partially-filled order simply stays open until terminal.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, time, timedelta
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

from .base import (
    AccountSnapshot,
    BrokerAdapter,
    BrokerOrder,
    BrokerPosition,
)

_ET = ZoneInfo("America/New_York")

_IBKR_TO_STATUS: dict[str, str] = {
    "filled":       "filled",
    "cancelled":    "cancelled",
    "canceled":     "cancelled",
    "apicancelled": "cancelled",
    "inactive":     "failed",
}

#: raw CP statuses that mean "working at the broker" — cancel_all targets these
_WORKING_STATUSES = {"pendingsubmit", "presubmitted", "submitted", "pendingcancel"}

_ORDER_TYPE_MAP = {"market": "MKT", "limit": "LMT"}
_TIF_MAP = {"day": "DAY", "gtc": "GTC", "opg": "OPG"}


def _f(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(str(v))
    except (TypeError, ValueError):
        return None


def _amount(v) -> Optional[float]:
    """CP account-summary values arrive either bare or as {'amount': X, ...}."""
    if isinstance(v, dict):
        return _f(v.get("amount"))
    return _f(v)


class IBKRBrokerAdapter(BrokerAdapter):
    name = "ibkr"

    def __init__(
        self,
        *,
        gateway_url: Optional[str] = None,
        account_id: Optional[str] = None,
        tls_verify: Optional[bool] = None,
        http_provider: Optional[Callable[[], object]] = None,
        timeout: float = 30.0,
    ) -> None:
        super().__init__(http_provider=http_provider)
        self.gateway_url = (
            gateway_url if gateway_url is not None else os.getenv("IBKR_GATEWAY_URL", "")
        ).rstrip("/")
        self.account_id = (
            account_id if account_id is not None else os.getenv("IBKR_ACCOUNT_ID", "")
        )
        if tls_verify is None:
            # The CP gateway serves a self-signed cert on localhost/compose-net;
            # verification is off unless explicitly enabled.
            tls_verify = os.getenv("IBKR_TLS_VERIFY", "false").strip().lower() == "true"
        self.tls_verify = bool(tls_verify)
        self.timeout = timeout
        self._conid_cache: dict[str, int] = {}

    # -- config ---------------------------------------------------------------
    @property
    def _api(self) -> str:
        return f"{self.gateway_url}/v1/api"

    def _client(self, timeout: Optional[float] = None):
        return self._httpx.AsyncClient(timeout=timeout or self.timeout,
                                       verify=self.tls_verify)

    def has_credentials(self) -> bool:
        return bool(self.gateway_url) and bool(self.account_id)

    # -- status normalization --------------------------------------------------
    def normalize_status(self, raw_status: str) -> Optional[str]:
        return _IBKR_TO_STATUS.get((raw_status or "").strip().lower())

    # -- symbology --------------------------------------------------------------
    # System form is AV's HYPHEN (BRK-B, PBR-A); IBKR class shares use a SPACE
    # (BRK B). US symbols contain no legitimate spaces/hyphens outside these
    # suffixes, so the blanket swap is a bijection (same argument as Alpaca's
    # dot swap).
    def to_broker_symbol(self, ticker: str) -> str:
        return (ticker or "").replace("-", " ")

    def from_broker_symbol(self, symbol: str) -> str:
        return (symbol or "").replace(" ", "-")

    # -- conid resolution -------------------------------------------------------
    async def _resolve_conid(self, client, ticker: str) -> Optional[int]:
        """System ticker → IBKR contract id via /iserver/secdef/search. Prefers
        the exact-symbol match carrying an STK section. Cached per process (conids
        are stable identifiers)."""
        if ticker in self._conid_cache:
            return self._conid_cache[ticker]
        symbol = self.to_broker_symbol(ticker)
        r = await client.post(f"{self._api}/iserver/secdef/search",
                              json={"symbol": symbol, "name": False, "secType": "STK"})
        if r.status_code != 200:
            return None
        items = r.json() or []
        best: Optional[int] = None
        for item in items:
            if not isinstance(item, dict) or item.get("conid") in (None, ""):
                continue
            sections = item.get("sections") or []
            has_stk = any(isinstance(s, dict) and s.get("secType") == "STK"
                          for s in sections)
            exact = str(item.get("symbol", "")).upper() == symbol.upper()
            if exact and has_stk:
                best = int(item["conid"])
                break
            if best is None and has_stk:
                best = int(item["conid"])
        if best is not None:
            self._conid_cache[ticker] = best
        return best

    # -- reads ------------------------------------------------------------------
    async def get_account(self) -> Optional[AccountSnapshot]:
        async with self._client() as client:
            # CP requires the account list be touched once per session before
            # portfolio subresources respond; harmless when already primed.
            await client.get(f"{self._api}/portfolio/accounts")
            r = await client.get(f"{self._api}/portfolio/{self.account_id}/summary")
            r.raise_for_status()
            acct = r.json() or {}
        return AccountSnapshot(
            equity=_amount(acct.get("netliquidation")),
            buying_power=_amount(acct.get("buyingpower")),
            cash=_amount(acct.get("totalcashvalue")),
            raw=acct if isinstance(acct, dict) else {},
        )

    async def get_positions(self) -> list[BrokerPosition]:
        async with self._client() as client:
            await client.get(f"{self._api}/portfolio/accounts")
            r = await client.get(
                f"{self._api}/portfolio/{self.account_id}/positions/0")
            r.raise_for_status()
            positions = r.json() or []
        out: list[BrokerPosition] = []
        for pos in positions:
            if not isinstance(pos, dict):
                continue
            qty = _f(pos.get("position"))
            if not qty:
                continue
            mkt_value = _f(pos.get("mktValue"))
            unrealized = _f(pos.get("unrealizedPnl"))
            cost = (mkt_value - unrealized
                    if mkt_value is not None and unrealized is not None else None)
            out.append(BrokerPosition(
                ticker=self.from_broker_symbol(str(pos.get("ticker") or "")),
                qty=qty,
                avg_entry_price=_f(pos.get("avgCost")),
                current_price=_f(pos.get("mktPrice")),
                market_value=mkt_value,
                cost_basis=cost,
                unrealized_pl=unrealized,
                unrealized_plpc=(unrealized / cost
                                 if unrealized is not None and cost else None),
                side="long" if qty > 0 else "short",
                raw=pos,
            ))
        return out

    async def list_orders(self, *, status: str = "all", limit: int = 500) -> list[BrokerOrder]:
        async with self._client() as client:
            r = await client.get(f"{self._api}/iserver/account/orders")
            r.raise_for_status()
            body = r.json() or {}
        orders = body.get("orders") if isinstance(body, dict) else body
        out: list[BrokerOrder] = []
        for o in (orders or [])[:limit]:
            if not isinstance(o, dict):
                continue
            raw_status = str(o.get("status", ""))
            raw = dict(o)
            # CP echoes our client_order_id as order_ref; the reaper reconciles
            # via raw["client_order_id"] (Alpaca field name — consumer contract).
            raw.setdefault("client_order_id", o.get("order_ref"))
            out.append(BrokerOrder(
                broker_order_id=str(o.get("orderId", "")),
                status=self.normalize_status(raw_status),
                raw_status=raw_status,
                filled_qty=_f(o.get("filledQuantity")),
                avg_fill_price=_f(o.get("avgPrice")),
                filled_at=None,   # CP order list carries no fill timestamp
                raw=raw,
            ))
        return out

    async def get_order(self, broker_order_id: str) -> Optional[dict]:
        """CP order status, NORMALIZED to the Alpaca-shaped dict the fill
        reconciler reads (status / filled_qty / filled_avg_price / filled_at)."""
        async with self._client(timeout=10.0) as client:
            r = await client.get(
                f"{self._api}/iserver/account/order/status/{broker_order_id}")
        if r.status_code != 200:
            return None
        d = r.json() or {}
        raw_status = str(d.get("order_status", ""))
        return {
            "status": self.normalize_status(raw_status) or raw_status.lower(),
            "filled_qty": d.get("cum_fill"),
            "filled_avg_price": d.get("avg_price") or d.get("average_price"),
            "filled_at": None,   # reconciler falls back to now() when absent
            "raw": d,
        }

    async def get_clock(self) -> Optional[dict]:
        """Regular NYSE hours computed locally in ET (CP has no clock endpoint).
        NO holiday calendar — see module docstring ACTIVATION ITEM."""
        now = datetime.now(_ET)
        open_t, close_t = time(9, 30), time(16, 0)

        def _next_weekday_at(d: datetime, t: time) -> datetime:
            day = d.date()
            while day.weekday() >= 5:
                day += timedelta(days=1)
            return datetime.combine(day, t, tzinfo=_ET)

        is_open = now.weekday() < 5 and open_t <= now.time() < close_t
        if is_open:
            next_close = datetime.combine(now.date(), close_t, tzinfo=_ET)
            next_open = _next_weekday_at(
                datetime.combine(now.date() + timedelta(days=1), open_t, tzinfo=_ET),
                open_t)
        else:
            base = now
            if now.weekday() < 5 and now.time() >= close_t:
                base = now + timedelta(days=1)
            next_open = _next_weekday_at(
                datetime.combine(base.date(), open_t, tzinfo=_ET), open_t)
            if now.weekday() < 5 and now.time() < open_t:
                next_open = datetime.combine(now.date(), open_t, tzinfo=_ET)
            next_close = datetime.combine(next_open.date(), close_t, tzinfo=_ET)
        return {"is_open": is_open, "next_open": next_open, "next_close": next_close}

    # -- writes -------------------------------------------------------------
    async def submit_order(
        self, payload: dict
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """POST to /iserver/account/{acct}/orders, auto-confirming benign reply
        questions. Returns (broker_order_id, broker_status, error)."""
        ticker = payload.get("symbol", "")
        async with self._client() as client:
            conid = await self._resolve_conid(client, ticker)
            if conid is None:
                return None, None, f"could not resolve IBKR conid for {ticker!r}"
            order = {
                "conid": conid,
                "orderType": _ORDER_TYPE_MAP.get(
                    str(payload.get("type", "market")).lower(), "MKT"),
                "side": str(payload.get("side", "")).upper(),
                "tif": _TIF_MAP.get(
                    str(payload.get("time_in_force", "day")).lower(), "DAY"),
                "quantity": _f(payload.get("qty")),
            }
            if payload.get("client_order_id"):
                order["cOID"] = str(payload["client_order_id"])
            r = await client.post(
                f"{self._api}/iserver/account/{self.account_id}/orders",
                json={"orders": [order]})
            # Reply-confirmation loop: a "question" response ({id, message[]})
            # must be acknowledged before the order exists. Bounded — a broker
            # that keeps asking gets a failure, not an infinite loop.
            for _ in range(5):
                if r.status_code != 200:
                    return None, None, r.text[:1000]
                body = r.json()
                items = body if isinstance(body, list) else [body]
                first = items[0] if items and isinstance(items[0], dict) else {}
                if first.get("order_id"):
                    return (str(first["order_id"]),
                            first.get("order_status"), None)
                reply_id = first.get("id")
                if not reply_id:
                    return None, None, f"unrecognized IBKR order response: {str(body)[:500]}"
                r = await client.post(f"{self._api}/iserver/reply/{reply_id}",
                                      json={"confirmed": True})
            return None, None, "IBKR kept returning confirmation prompts (5 replies)"

    async def close_position(
        self, symbol: str
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """No close endpoint at CP: read the LIVE position from the gateway and
        submit a full-qty MKT SELL. Already flat → ALREADY_CLOSED_STATUS."""
        try:
            positions = await self.get_positions()
        except Exception as exc:  # noqa: BLE001 — surface as submit error
            return None, None, f"position read failed: {exc}"[:1000]
        qty = next((p.qty for p in positions if p.ticker == symbol), None)
        if not qty:
            return None, self.ALREADY_CLOSED_STATUS, None
        return await self.submit_order({
            "symbol": symbol,
            "qty": abs(qty),
            "side": "sell" if qty > 0 else "buy",
            "type": "market",
            "time_in_force": "day",
            "client_order_id": f"close-{symbol}-{uuid.uuid4().hex[:12]}",
        })

    async def cancel_all_orders(self) -> tuple[int, Any, str]:
        """No cancel-all endpoint at CP: cancel each working order individually
        and synthesize the (207, [{id, status}], text) multi-status shape
        trade-executor's confirmed/failed split already consumes."""
        async with self._client() as client:
            r = await client.get(f"{self._api}/iserver/account/orders")
            if r.status_code != 200:
                return r.status_code, None, r.text[:1000]
            body = r.json() or {}
            orders = body.get("orders") if isinstance(body, dict) else body
            items: list[dict] = []
            for o in orders or []:
                if not isinstance(o, dict):
                    continue
                if str(o.get("status", "")).strip().lower() not in _WORKING_STATUSES:
                    continue
                oid = o.get("orderId")
                resp = await client.delete(
                    f"{self._api}/iserver/account/{self.account_id}/order/{oid}")
                items.append({
                    "id": str(oid),
                    "status": 200 if 200 <= resp.status_code < 300 else resp.status_code,
                    "body": None if 200 <= resp.status_code < 300 else resp.text[:200],
                })
        return 207, items, ""
