"""Alpaca, mapped onto the execution contract.

This adapter's job is TRANSPORT and TRANSLATION. Every behavioural rule — when to
retry, what UNKNOWN means, whether an observation may support a conclusion —
lives above it and is certified once against the simulator. What is certified
HERE is only that Alpaca's messy reality maps onto the contract's vocabulary
correctly.

## Three things this does that the Stocker adapter does not

**It paginates, and admits when it did not finish.** `AlpacaBrokerAdapter.
list_orders` issues one GET with `limit=500, direction=desc` and no pagination,
so a busy account silently loses its OLDEST orders — exactly the stale resting
ones that matter. Here the read pages backwards through `until` and reports
`TRUNCATED` if it hits the page cap, so a caller can tell the difference between
"there were no more" and "we stopped looking".

**It re-reads the orders after the positions.** No broker offers an atomic
snapshot. Orders-first stops a mid-read fill making an object vanish; the third
read is what stops the same fill being counted twice.

**It has no `close_position`.** `DELETE /v2/positions/{symbol}` accepts no
`client_order_id`, so an order placed through it cannot carry Sentinel's derived
identity and is unrecoverable after a crash. Exits are exact-quantity SELLs like
everything else.

## Capabilities are declared, and two of them are False on purpose

`market_on_open` is not claimed: this adapter submits DAY orders, and claiming
MOO while sending DAY would be exactly the silent substitution the fail-closed
rule exists to prevent. `fractional_quantities` is not claimed either — Alpaca
supports fractional shares, but nothing here has been certified against a
fractional exit, and a capability is a statement about what has been PROVEN, not
about what the vendor's documentation permits.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional, Sequence

from sentinel.execution.contract import (
    BrokerAccountIdentity, BrokerCapabilities, BrokerFill, BrokerInstrument,
    BrokerObservation, BrokerOrder, BrokerPosition, CommandOutcome,
    Completeness, ExecutionBroker, Side)
from sentinel.execution.states import CommandState as S

log = logging.getLogger(__name__)

#: Orders per page, and how many pages before we admit we stopped looking.
PAGE_SIZE = 500
MAX_PAGES = 20

#: Alpaca's order vocabulary -> ours. The mapping lives in ONE place so a new
#: broker cannot re-introduce the `partial_fill` / `partially_filled`
#: split-brain that lived in Stocker for months.
#:
#: THE CLASSIFYING QUESTION IS NOT "does this sound finished?" IT IS:
#:
#:     can a trade still occur under this order?
#:
#: If yes — or if we cannot be certain it is no — the status must map to a state
#: for which `blocks_overlapping` is True. A wrongly-terminal status frees the
#: security for a second command and the original then fills too: a doubled
#: position, which is the exact failure the whole in-flight machinery exists to
#: prevent. A wrongly-in-flight status stalls one security until an operator
#: looks, which is visible and recoverable. Those costs are not symmetric, so
#: neither is the default.
#:
#: `stopped` was mapped to REJECTED here and that was a MONEY BUG. Alpaca
#: defines it as "the trade is guaranteed, usually at a stated price or better,
#: but has not yet occurred" — a fill that is CERTAIN and PENDING, which is very
#: nearly the opposite of a rejection. Marked terminal it freed the security,
#: and the guaranteed trade then landed alongside whatever replaced it.
_STATUS = {
    # ── working: routed or awaiting routing ─────────────────────────────────
    "new": S.ACKNOWLEDGED,
    "accepted": S.ACKNOWLEDGED,
    "pending_new": S.ACKNOWLEDGED,
    "accepted_for_bidding": S.ACKNOWLEDGED,
    "held": S.ACKNOWLEDGED,
    "suspended": S.ACKNOWLEDGED,

    # ── a trade is COMING, or may still be reported ─────────────────────────
    # `stopped`: the trade is GUARANTEED and has not happened yet.
    "stopped": S.ACKNOWLEDGED,
    # `calculated`: complete for the day, settlement calculations pending. The
    # final fill quantity is not yet established, so the command is not done.
    "calculated": S.ACKNOWLEDGED,
    # `done_for_day`: no further execution TODAY. Not the same as "no further
    # execution" — and for a partially filled order the remainder's fate is
    # still open, so this does not release the security on its own.
    "done_for_day": S.ACKNOWLEDGED,

    # ── replacement: Sentinel never issues one ──────────────────────────────
    # Seeing either means something OUTSIDE Sentinel altered our order. The
    # replacement carries a broker id we do not know and may still fill, so
    # releasing the security here would let us trade alongside an order we
    # cannot see. Blocked, and surfaced — see `is_anomalous_status`.
    "pending_replace": S.ACKNOWLEDGED,
    "replaced": S.ACKNOWLEDGED,

    # ── genuinely settled ───────────────────────────────────────────────────
    "partially_filled": S.PARTIALLY_FILLED,
    "filled": S.FILLED,
    "canceled": S.CANCELLED,
    "cancelled": S.CANCELLED,
    "expired": S.CANCELLED,
    "pending_cancel": S.CANCEL_PENDING,
    "rejected": S.REJECTED,
}

#: Statuses that mean an order of OURS was interfered with from outside. They
#: are blocked like any working order, but a human should know: Sentinel never
#: replaces an order, so their appearance is not something it can have caused.
ANOMALOUS_STATUSES = frozenset({"replaced", "pending_replace"})


def is_anomalous_status(raw: str) -> bool:
    return (raw or "").strip().lower() in ANOMALOUS_STATUSES


class UnmappedBrokerStatus(RuntimeError):
    """Alpaca reported a status this adapter has not been certified against.

    RAISED, not defaulted. Guessing that an unknown status is "probably still
    working" would let a filled or rejected order sit in the journal as live,
    and the two guesses fail in opposite directions.
    """


def map_status(raw: str) -> S:
    key = (raw or "").strip().lower()
    if key not in _STATUS:
        raise UnmappedBrokerStatus(
            f"Alpaca status {raw!r} has no certified mapping. Refusing to guess: "
            f"treating an unknown status as working leaves a settled order live "
            f"in the journal, and treating it as terminal abandons one that is "
            f"not. Add it to _STATUS with a test.")
    return _STATUS[key]


def _dec(value, default: Optional[Decimal] = None) -> Optional[Decimal]:
    """Decimal from the WIRE STRING, never via float.

    `Decimal(str(0.1))` and `Decimal(0.1)` differ, and the second is the one
    that makes an exact-quantity exit fail for over-sell by 1e-17.
    """
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return default


class AlpacaExecutionBroker(ExecutionBroker):
    """`ExecutionBroker` over Alpaca's REST API."""

    capabilities = BrokerCapabilities(
        stable_client_key=True,
        single_order_cancel=True,
        complete_order_pagination=True,
        recent_fill_history=True,
        instrument_identity=True,
        # NOT claimed. See the module docstring: a capability is what has been
        # PROVEN, not what the vendor's docs permit.
        fractional_quantities=False,
        market_on_open=False,
    )

    def __init__(self, *, api_key: str, secret_key: str, base_url: str,
                 resolve_security_id=None, to_broker_symbol=None,
                 http_provider=None) -> None:
        # THE PAPER GATE, AT THE CONSTRUCTOR. `sentinel/config.py` refuses a
        # non-paper `ALPACA_BASE_URL`, but that check guards the CONFIG path —
        # and this class takes a `base_url` string from anyone who imports it.
        # A future wiring commit that builds the adapter directly would bypass
        # the appliance's only live-trading protection without touching the
        # file that documents it, and the resulting diff would look like
        # plumbing.
        #
        # Enforced HERE so the bypass does not exist rather than being
        # discouraged: this is the object that holds the credentials and forms
        # the URLs, so it is the last honest place to ask.
        #
        # Deliberately importing the predicate rather than restating it. Two
        # copies of an allowlist drift, and the copy that drifts is the one
        # nobody is reading when it matters.
        from sentinel.config import assert_paper_url
        assert_paper_url(base_url)

        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = base_url.rstrip("/")
        self._http_provider = http_provider
        # Symbol <-> security identity is the CALLER's mapping: this adapter
        # must not invent one, because a guess here silently retargets an order.
        self._resolve = resolve_security_id or (lambda symbol: symbol)
        self._to_symbol = to_broker_symbol or (lambda s: s.replace("-", "."))

    # -- transport ----------------------------------------------------------
    @property
    def _httpx(self):
        if self._http_provider is not None:
            return self._http_provider()
        import httpx                       # noqa: PLC0415
        return httpx

    def _headers(self) -> dict:
        return {"APCA-API-KEY-ID": self.api_key,
                "APCA-API-SECRET-KEY": self.secret_key}

    async def _get(self, path: str, params: Optional[dict] = None):
        async with self._httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(f"{self.base_url}{path}",
                                    headers=self._headers(), params=params or {})
            resp.raise_for_status()
            return resp.json()

    # -- identity -----------------------------------------------------------
    async def identify_account(self) -> BrokerAccountIdentity:
        payload = await self._get("/v2/account")
        return BrokerAccountIdentity(
            broker="alpaca",
            account_id=str(payload.get("account_number") or payload.get("id") or ""),
            raw=payload)

    # -- observation --------------------------------------------------------
    async def observe(self) -> BrokerObservation:
        """Orders, positions, orders again. See the contract §5.3."""
        orders, complete_a = await self._list_orders()
        positions = await self._list_positions()
        recheck, complete_b = await self._list_orders()

        completeness = Completeness.COMPLETE
        if not (complete_a and complete_b):
            completeness = Completeness.TRUNCATED
        elif _fingerprint(recheck) != _fingerprint(orders):
            # The two halves describe different instants. Netting a working
            # order against the position it has just become would produce a
            # delta that sells a holding acquired seconds earlier.
            completeness = Completeness.INCONSISTENT

        return BrokerObservation(
            observed_at=datetime.now(timezone.utc), orders=tuple(recheck),
            positions=tuple(positions), completeness=completeness)

    async def _list_orders(self):
        """Page backwards through the order list. Returns (orders, complete)."""
        out: list = []
        until: Optional[str] = None
        for _page in range(MAX_PAGES):
            params = {"status": "all", "limit": PAGE_SIZE, "direction": "desc"}
            if until:
                params["until"] = until
            page = await self._get("/v2/orders", params)
            if not page:
                return out, True
            out.extend(self._to_order(o) for o in page if isinstance(o, dict))
            if len(page) < PAGE_SIZE:
                return out, True
            submitted = [o.get("submitted_at") for o in page
                         if isinstance(o, dict) and o.get("submitted_at")]
            if not submitted:
                # Cannot advance the cursor, so we cannot claim completeness.
                return out, False
            until = min(submitted)
        # HIT THE CAP. There may be more, and saying "complete" here is the
        # unstated assumption the contract exists to remove.
        log.warning("sentinel: order list hit the %d-page cap; reporting "
                    "TRUNCATED rather than assuming completeness", MAX_PAGES)
        return out, False

    async def _list_positions(self):
        payload = await self._get("/v2/positions")
        out = []
        for p in payload or []:
            if not isinstance(p, dict):
                continue
            symbol = str(p.get("symbol") or "")
            qty = _dec(p.get("qty"), Decimal(0))
            out.append(BrokerPosition(
                instrument=self._instrument(symbol, p.get("asset_id")),
                quantity=qty or Decimal(0)))
        return out

    def _instrument(self, symbol: str, asset_id=None) -> BrokerInstrument:
        return BrokerInstrument(security_id=str(self._resolve(symbol)),
                                symbol=symbol,
                                broker_id=str(asset_id) if asset_id else None)

    def _to_order(self, payload: dict) -> BrokerOrder:
        symbol = str(payload.get("symbol") or "")
        raw_status = str(payload.get("status") or "")
        if is_anomalous_status(raw_status):
            log.warning(
                "sentinel: order %s reports %r — Sentinel never issues a "
                "replacement, so this order was altered from OUTSIDE. It stays "
                "BLOCKING because the replacement may still fill under a broker "
                "id we do not hold.", payload.get("id"), raw_status)
        return BrokerOrder(
            broker_order_id=str(payload.get("id") or ""),
            client_key=payload.get("client_order_id") or None,
            instrument=self._instrument(symbol, payload.get("asset_id")),
            side=Side.BUY if str(payload.get("side")) == "buy" else Side.SELL,
            state=map_status(raw_status),
            quantity=_dec(payload.get("qty"), Decimal(0)) or Decimal(0),
            filled_quantity=_dec(payload.get("filled_qty"), Decimal(0)) or Decimal(0),
            raw=payload)

    # -- recovery -----------------------------------------------------------
    async def find_by_client_key(self, client_key: str) -> Optional[BrokerOrder]:
        """`GET /v2/orders:by_client_order_id` — the exact-lookup primitive.

        A 404 means the broker has no such order. That is only safe to act on
        when the surrounding observation was COMPLETE, which is the caller's
        rule, not this method's.
        """
        try:
            payload = await self._get("/v2/orders:by_client_order_id",
                                      {"client_order_id": client_key})
        except Exception as exc:                              # noqa: BLE001
            if _is_not_found(exc):
                return None
            raise
        return self._to_order(payload) if payload else None

    # -- writes -------------------------------------------------------------
    async def submit(self, *, client_key: str, instrument: BrokerInstrument,
                     side: Side, quantity: Decimal) -> CommandOutcome:
        body = {
            "symbol": self._to_symbol(instrument.symbol),
            "qty": str(quantity),
            "side": "buy" if side is Side.BUY else "sell",
            "type": "market",
            "time_in_force": "day",
            "client_order_id": client_key,
        }
        try:
            async with self._httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(f"{self.base_url}/v2/orders",
                                         headers=self._headers(), json=body)
        except Exception as exc:                              # noqa: BLE001
            # THE MOST IMPORTANT LINE IN THE ADAPTER. The request may have been
            # accepted; we simply do not know. Anything other than UNKNOWN here
            # licences a retry that opens a second position.
            return CommandOutcome(state=S.UNKNOWN,
                                  detail=f"{type(exc).__name__}: {exc}")

        if resp.status_code in (200, 201):
            payload = resp.json()
            return CommandOutcome(state=map_status(str(payload.get("status"))),
                                  broker_order_id=str(payload.get("id") or ""),
                                  detail="accepted")
        if resp.status_code == 422:
            # A DUPLICATE client_order_id lands here, and it is a SUCCESS for
            # our purposes: the key is already resting, which is precisely what
            # makes a blind retry safe. Resolving it needs a lookup, not a guess.
            text = (resp.text or "")[:500]
            if "client_order_id" in text or "duplicate" in text.lower():
                return CommandOutcome(state=S.UNKNOWN,
                                      detail=f"duplicate key at broker: {text}")
            return CommandOutcome(state=S.REJECTED, detail=text)
        if 400 <= resp.status_code < 500:
            return CommandOutcome(state=S.REJECTED,
                                  detail=f"HTTP {resp.status_code}: "
                                         f"{(resp.text or '')[:500]}")
        # 5xx: the broker's own failure. It may or may not have recorded the
        # order, so this is undetermined, not a rejection.
        return CommandOutcome(state=S.UNKNOWN,
                              detail=f"HTTP {resp.status_code}")

    async def cancel(self, broker_order_id: str) -> CommandOutcome:
        try:
            async with self._httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.delete(
                    f"{self.base_url}/v2/orders/{broker_order_id}",
                    headers=self._headers())
        except Exception as exc:                              # noqa: BLE001
            return CommandOutcome(state=S.UNKNOWN,
                                  detail=f"{type(exc).__name__}: {exc}")
        if resp.status_code in (200, 204):
            # ACKNOWLEDGED, not CANCELLED. A broker can accept a cancel and
            # cancel nothing — observed 2026-08-09 — so only an observation
            # showing the order gone may advance the command.
            return CommandOutcome(state=S.ACKNOWLEDGED,
                                  broker_order_id=broker_order_id,
                                  detail="cancel accepted (unconfirmed)")
        if resp.status_code == 404:
            return CommandOutcome(state=S.REJECTED, detail="no such order")
        return CommandOutcome(state=S.UNKNOWN,
                              detail=f"HTTP {resp.status_code}")

    async def recent_fills(self, since: datetime) -> Sequence[BrokerFill]:
        payload = await self._get("/v2/account/activities/FILL",
                                  {"after": since.isoformat()})
        out = []
        for a in payload or []:
            if not isinstance(a, dict):
                continue
            out.append(BrokerFill(
                client_key=None,
                broker_order_id=str(a.get("order_id") or ""),
                quantity=_dec(a.get("qty"), Decimal(0)) or Decimal(0),
                price=_dec(a.get("price"), Decimal(0)) or Decimal(0),
                filled_at=_parse_ts(a.get("transaction_time"))))
        return tuple(out)


def _fingerprint(orders) -> tuple:
    return tuple(sorted((o.broker_order_id, o.state.value, str(o.filled_quantity))
                        for o in orders))


def _is_not_found(exc) -> bool:
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None) == 404


def _parse_ts(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
