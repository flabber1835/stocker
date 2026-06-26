"""Broker-agnostic adapter interface — the single seam between the deterministic
trading engine and a concrete paper/live broker.

Design intent (see docs/service-boundaries.md "Broker abstraction"):

  - EXACTLY ONE broker is active per deployment. Each machine runs one book with
    one broker (Alpaca or, later, IBKR), selected at deploy time by the `BROKER`
    env var via `factory.get_broker_adapter()`. There is NO runtime multi-broker
    routing — that keeps every per-account control (MAX_POSITIONS, turnover,
    sizing) operating on a single account, with no cross-broker scoping.

  - The adapter is a TRANSPORT + NORMALIZATION layer, never a decision-maker.
    `trade-executor` remains the only service that DECIDES to submit (sizing,
    risk-check, idempotency); the adapter is its outbound pipe. This preserves
    the architecture invariant "only trade-executor places orders".

  - Read methods return NORMALIZED dataclasses (broker-agnostic), so a second
    broker (IBKR) is a drop-in `BrokerAdapter` implementation and the services
    consuming `AccountSnapshot` / `BrokerPosition` / `BrokerOrder` don't change.

  - Order status is normalized into the canonical `order_status.py` DB tokens at
    THIS boundary (one place), so a new broker's status vocabulary can never
    re-introduce the `partial_fill` vs `partially_filled` split-brain class.

`http_provider`: callers may pass a zero-arg callable returning the httpx-like
module to use for transport. Services pass `lambda: <module>.httpx` so that the
existing test mocking strategy (`patch.object(<module>, "httpx")` /
`patch("<module>.httpx.AsyncClient")`) keeps intercepting adapter calls — the
provider is resolved at call time, so a patch applied after construction is
honoured. When omitted the real `httpx` module is used.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Normalized, broker-agnostic value objects
# ---------------------------------------------------------------------------


@dataclass
class AccountSnapshot:
    """Normalized account state. `raw` keeps the original broker payload for audit."""
    equity: Optional[float]
    buying_power: Optional[float]
    cash: Optional[float]
    raw: dict = field(default_factory=dict)


@dataclass
class BrokerPosition:
    """Normalized open position. Field set mirrors what `live_positions` stores."""
    ticker: str
    qty: Optional[float]
    avg_entry_price: Optional[float] = None
    current_price: Optional[float] = None
    market_value: Optional[float] = None
    cost_basis: Optional[float] = None
    unrealized_pl: Optional[float] = None
    unrealized_plpc: Optional[float] = None
    side: str = "long"
    lastday_price: Optional[float] = None
    change_today: Optional[float] = None
    raw: dict = field(default_factory=dict)


@dataclass
class BrokerOrder:
    """Normalized order as reported by the broker's order list / order lookup.

    `status` is the CANONICAL `alpaca_orders.status` token (or None when the
    order is still open/working in a state we don't persist as terminal —
    callers skip those). `raw_status` is the original broker spelling, stored in
    `alpaca_orders.alpaca_status` for audit."""
    broker_order_id: str
    status: Optional[str]
    raw_status: str
    filled_qty: Optional[float] = None
    avg_fill_price: Optional[float] = None
    filled_at: Optional[datetime] = None
    raw: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Adapter interface
# ---------------------------------------------------------------------------


class BrokerAdapter(abc.ABC):
    """One concrete subclass per broker. A deployment instantiates exactly one."""

    #: short broker identifier, e.g. "alpaca" / "ibkr"
    name: str = "base"

    #: sentinel returned by `close_position` when the position is ALREADY flat
    #: (e.g. a 404 close on Alpaca). The exit's goal — be out of the name — is
    #: met, so callers treat it as a benign terminal no-op, not a submission.
    #: Single source: trade-executor imports this instead of redefining it.
    ALREADY_CLOSED_STATUS: str = "position_already_closed"

    def __init__(self, http_provider: Optional[Callable[[], object]] = None) -> None:
        self._http_provider = http_provider

    # -- transport accessor -------------------------------------------------
    @property
    def _httpx(self):
        """The httpx-like module to use. Resolved at call time via the provider so
        module-level test patches applied after construction are honoured."""
        if self._http_provider is not None:
            return self._http_provider()
        import httpx  # local import: only the real transport needs the dependency
        return httpx

    # -- credentials --------------------------------------------------------
    @abc.abstractmethod
    def has_credentials(self) -> bool:
        """True when this adapter is configured to actually reach the broker."""

    # -- reads --------------------------------------------------------------
    @abc.abstractmethod
    async def get_account(self) -> Optional[AccountSnapshot]:
        ...

    @abc.abstractmethod
    async def get_positions(self) -> list[BrokerPosition]:
        ...

    @abc.abstractmethod
    async def list_orders(self, *, status: str = "all", limit: int = 500) -> list[BrokerOrder]:
        ...

    @abc.abstractmethod
    async def get_order(self, broker_order_id: str) -> Optional[dict]:
        """Raw broker order dict (used for fill reconciliation). None on failure."""

    @abc.abstractmethod
    async def get_clock(self) -> Optional[dict]:
        """{is_open, next_open, next_close} or None when unknown (creds/transport)."""

    # -- status normalization ----------------------------------------------
    @abc.abstractmethod
    def normalize_status(self, raw_status: str) -> Optional[str]:
        """Map a broker status spelling to a canonical `alpaca_orders.status` token,
        or None when the order is still open/working (not a terminal we persist)."""

    # -- writes -------------------------------------------------------------
    # These are TRANSPORT only. trade-executor owns the decision logic (sizing,
    # risk-check, idempotency, status persistence); the adapter just talks to the
    # broker and returns a broker-agnostic result. All three are the seam an IBKR
    # adapter implements to make the order path broker-portable.

    @abc.abstractmethod
    async def submit_order(
        self, payload: dict
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """Place an order. `payload` is the broker-agnostic order dict
        (symbol, qty, side, type, time_in_force, client_order_id).
        Returns (broker_order_id, broker_status, error) — error is None on success,
        else a short message and (broker_order_id, broker_status) are None."""

    @abc.abstractmethod
    async def close_position(
        self, symbol: str
    ) -> tuple[Optional[str], Optional[str], Optional[str]]:
        """Close 100% of `symbol`. Same return shape as `submit_order`. When the
        position is already flat, returns (None, ALREADY_CLOSED_STATUS, None)."""

    @abc.abstractmethod
    async def cancel_all_orders(self) -> tuple[int, Any, str]:
        """Cancel all open orders. Returns (http_status, parsed_body, text):
        parsed_body is the broker's per-order multi-status list (or None if it did
        not parse); text is the raw body (used when http_status is non-2xx).
        Transport errors propagate to the caller (which records a whole-call fail)."""
