"""Alpaca implementation of `BrokerAdapter`.

Centralizes ALL Alpaca-specific knowledge that was previously duplicated across
`alpaca-sync` and `trade-executor`: the base URL, the auth headers, the
endpoint shapes, the float/timestamp parsing, and the broker-status → canonical
DB-token map. Read methods return the broker-agnostic dataclasses from `base`.

Error policy: read methods raise on transport / non-2xx (httpx exceptions are
propagated unchanged) so each caller keeps its own error handling identical to
the pre-refactor inline code (alpaca-sync lets the run fail; trade-executor's
read helpers wrap the call in try/except → None).
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Callable, Optional

from typing import Any

from .base import (
    AccountSnapshot,
    BrokerAdapter,
    BrokerOrder,
    BrokerPosition,
)


# Alpaca caps one order-list response at 500.  A finite local cap keeps an
# unexpected broker loop bounded, but exhausting it is incomplete evidence and
# therefore raises rather than returning a prefix that migration could call
# flat.
ORDER_PAGE_MAX = 500
ORDER_PAGE_CAP = 100


class IncompleteOrderList(RuntimeError):
    """The broker did not prove that its order list was exhausted."""


def _f(v) -> Optional[float]:
    """Convert any numeric-ish value (Decimal, str, float) to float or None.
    Matches the `_f`/`_parse_float` helper both services used verbatim."""
    if v is None:
        return None
    try:
        return float(str(v))
    except (TypeError, ValueError):
        return None


def _parse_dt(raw) -> Optional[datetime]:
    """Parse an Alpaca ISO timestamp (e.g. '2026-06-01T09:30:00-04:00')."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


# Map Alpaca terminal statuses → canonical `alpaca_orders.status` DB tokens.
# Single source of truth (was previously inline in alpaca-sync as
# `_ALPACA_TO_STATUS`). Values are canonical tokens from order_status.py's set
# (`partial_fill`, NOT the broker spelling `partially_filled`). A status absent
# from this map means "still open/working" → callers leave the order untouched.
_ALPACA_TO_STATUS: dict[str, str] = {
    "filled":           "filled",
    "partially_filled": "partial_fill",
    "canceled":         "cancelled",
    "done_for_day":     "cancelled",
    "expired":          "cancelled",
    "replaced":         "cancelled",
    "rejected":         "failed",
}


class AlpacaBrokerAdapter(BrokerAdapter):
    name = "alpaca"

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        base_url: Optional[str] = None,
        http_provider: Optional[Callable[[], object]] = None,
        timeout: float = 30.0,
    ) -> None:
        super().__init__(http_provider=http_provider)
        self.api_key = api_key if api_key is not None else os.getenv("ALPACA_API_KEY", "")
        self.secret_key = (
            secret_key if secret_key is not None else os.getenv("ALPACA_SECRET_KEY", "")
        )
        self.base_url = (
            base_url
            if base_url is not None
            else os.getenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
        )
        self.timeout = timeout

    # -- config -------------------------------------------------------------
    def headers(self) -> dict:
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.secret_key,
        }

    def has_credentials(self) -> bool:
        # Mirrors alpaca-sync's `_has_credentials` (rejects the 'demo' placeholder)
        # AND trade-executor's `ALPACA_API_KEY and ALPACA_SECRET_KEY` gate.
        return bool(self.api_key) and self.api_key != "demo" and bool(self.secret_key)

    # -- status normalization ----------------------------------------------
    def normalize_status(self, raw_status: str) -> Optional[str]:
        return _ALPACA_TO_STATUS.get(raw_status)

    # -- symbology -----------------------------------------------------------
    # Alpaca uses DOT notation for share classes / preferreds / units (PBR.A,
    # BRK.B); the system form is Alpha Vantage's HYPHEN (PBR-A, BRK-B). US
    # symbols contain no legitimate hyphens or dots outside these suffixes, so a
    # blanket swap is a bijection. Discovered live: entry intent for PBR-A →
    # Alpaca 'asset "PBR-A" not found'.
    def to_broker_symbol(self, ticker: str) -> str:
        return (ticker or "").replace("-", ".")

    def from_broker_symbol(self, symbol: str) -> str:
        return (symbol or "").replace(".", "-")

    # -- reads --------------------------------------------------------------
    async def get_account(self) -> Optional[AccountSnapshot]:
        async with self._httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.get(f"{self.base_url}/v2/account", headers=self.headers())
            r.raise_for_status()
            acct = r.json()
        return AccountSnapshot(
            equity=_f(acct.get("equity")),
            buying_power=_f(acct.get("buying_power")),
            cash=_f(acct.get("cash")),
            raw=acct if isinstance(acct, dict) else {},
        )

    async def get_positions(self) -> list[BrokerPosition]:
        async with self._httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.get(f"{self.base_url}/v2/positions", headers=self.headers())
            r.raise_for_status()
            positions = r.json()
        out: list[BrokerPosition] = []
        for pos in positions or []:
            if not isinstance(pos, dict):
                continue
            out.append(
                BrokerPosition(
                    # broker → SYSTEM symbology (PBR.A → PBR-A) so live_positions
                    # matches rankings/targets and held-detection can't miss.
                    ticker=self.from_broker_symbol(pos.get("symbol", "")),
                    qty=_f(pos.get("qty")),
                    avg_entry_price=_f(pos.get("avg_entry_price")),
                    current_price=_f(pos.get("current_price")),
                    market_value=_f(pos.get("market_value")),
                    cost_basis=_f(pos.get("cost_basis")),
                    unrealized_pl=_f(pos.get("unrealized_pl")),
                    unrealized_plpc=_f(pos.get("unrealized_plpc")),
                    side=pos.get("side", "long"),
                    lastday_price=_f(pos.get("lastday_price")),
                    change_today=_f(pos.get("change_today")),
                    raw=pos,
                )
            )
        return out

    async def list_orders(self, *, status: str = "all", limit: int = 500
                          ) -> list[BrokerOrder]:
        """Return the complete filtered order list or raise.

        ``limit`` is the per-page size. Alpaca's ``before_order_id`` cursor is
        exclusive and stable even when many orders share a submission
        timestamp, unlike timestamp arithmetic. Returning a capped prefix would
        let migration declare an inherited account flat while an older working
        order can still fill, so every non-exhaustive shape fails closed.
        """
        if not isinstance(limit, int) or isinstance(limit, bool):
            raise ValueError("order page limit must be an integer")
        if not 1 <= limit <= ORDER_PAGE_MAX:
            raise ValueError(
                f"order page limit must be between 1 and {ORDER_PAGE_MAX}")

        rows: list[dict] = []
        seen_ids: set[str] = set()
        before_order_id: Optional[str] = None
        async with self._httpx.AsyncClient(timeout=self.timeout) as client:
            for _page_number in range(ORDER_PAGE_CAP):
                params = {
                    "status": status,
                    "limit": limit,
                    "direction": "desc",
                }
                if before_order_id is not None:
                    params["before_order_id"] = before_order_id
                r = await client.get(
                    f"{self.base_url}/v2/orders",
                    headers=self.headers(), params=params)
                r.raise_for_status()
                page = r.json()
                if not isinstance(page, list):
                    raise IncompleteOrderList(
                        "Alpaca order-list response was not an array; refusing "
                        "to treat malformed evidence as a complete read")
                if len(page) > limit:
                    raise IncompleteOrderList(
                        f"Alpaca returned {len(page)} orders for page limit "
                        f"{limit}; response boundaries are not trustworthy")

                page_ids: list[str] = []
                for item in page:
                    if not isinstance(item, dict):
                        raise IncompleteOrderList(
                            "Alpaca order-list page contained a non-object; "
                            "refusing a partial administrative read")
                    order_id = str(item.get("id") or "").strip()
                    if not order_id:
                        raise IncompleteOrderList(
                            "Alpaca order-list page omitted an order id; the "
                            "next stable cursor and targeted cancellation are "
                            "not provable")
                    if order_id in seen_ids:
                        raise IncompleteOrderList(
                            f"Alpaca repeated order {order_id} across exclusive "
                            "cursor pages; pagination did not make progress")
                    seen_ids.add(order_id)
                    page_ids.append(order_id)
                    rows.append(item)

                if len(page) < limit:
                    break
                # direction=desc makes the last row the oldest row on this
                # page. before_order_id is exclusive, so the next response
                # begins strictly behind this durable broker identity.
                before_order_id = page_ids[-1]
            else:
                raise IncompleteOrderList(
                    f"Alpaca open-order read reached the fail-closed cap of "
                    f"{ORDER_PAGE_CAP} full pages ({ORDER_PAGE_CAP * limit} "
                    "orders); migration cannot conclude that the account is "
                    "free of older working orders")

        out: list[BrokerOrder] = []
        for o in rows:
            raw_status = o.get("status", "")
            out.append(
                BrokerOrder(
                    broker_order_id=str(o.get("id", "")),
                    status=self.normalize_status(raw_status),
                    raw_status=raw_status,
                    filled_qty=_f(o.get("filled_qty")),
                    avg_fill_price=_f(o.get("filled_avg_price")),
                    filled_at=_parse_dt(o.get("filled_at")),
                    raw=o,
                )
            )
        return out

    async def get_order(self, broker_order_id: str) -> Optional[dict]:
        async with self._httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{self.base_url}/v2/orders/{broker_order_id}",
                headers=self.headers(),
            )
        if r.status_code == 200:
            return r.json()
        return None

    async def get_clock(self) -> Optional[dict]:
        async with self._httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{self.base_url}/v2/clock", headers=self.headers())
        if r.status_code == 200:
            d = r.json()
            return {
                "is_open": bool(d.get("is_open")),
                "next_open": _parse_dt(d.get("next_open")),
                "next_close": _parse_dt(d.get("next_close")),
            }
        return None

    # -- writes (transport only; trade-executor owns the decision logic) -----
    async def submit_order(
        self, payload: dict
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """POST an order to Alpaca. Returns (alpaca_order_id, alpaca_status, error).
        Transport errors propagate (caller wraps them). The payload's symbol is
        translated SYSTEM → broker form here (PBR-A → PBR.A); callers keep the
        system form everywhere (intents, alpaca_orders rows, risk checks)."""
        if payload.get("symbol"):
            payload = {**payload, "symbol": self.to_broker_symbol(payload["symbol"])}
        async with self._httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(
                f"{self.base_url}/v2/orders", json=payload, headers=self.headers()
            )
        if resp.status_code in (200, 201):
            data = resp.json()
            return data.get("id"), data.get("status"), None
        return None, None, resp.text[:1000]

    async def close_position(
        self, symbol: str
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """Close 100% of a position via DELETE /v2/positions/{symbol}. Same return
        shape as submit_order. A 404 (already flat) maps to the benign
        ALREADY_CLOSED_STATUS sentinel rather than a spurious error.

        Alpaca computes the exact held qty at execution, so this never over-sells a
        fractional position ("insufficient qty available") and is immune to drift
        since the last sync."""
        async with self._httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.delete(
                f"{self.base_url}/v2/positions/{self.to_broker_symbol(symbol)}",
                headers=self.headers(),
            )
        if resp.status_code in (200, 201):
            data = resp.json()
            return data.get("id"), data.get("status"), None
        if resp.status_code == 404:
            return None, self.ALREADY_CLOSED_STATUS, None
        return None, None, resp.text[:1000]

    async def cancel_all_orders(self) -> tuple[int, Any, str]:
        """DELETE /v2/orders. Returns (http_status, parsed_body, text). Alpaca
        replies 207 multi-status with a list of {id, status} items; parsed_body is
        that list (or None if it did not parse). Transport errors propagate."""
        async with self._httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.delete(
                f"{self.base_url}/v2/orders", headers=self.headers()
            )
        body: Any = None
        try:
            body = resp.json()
        except Exception:
            body = None
        text = ""
        try:
            text = resp.text
        except Exception:
            text = ""
        return resp.status_code, body, text
