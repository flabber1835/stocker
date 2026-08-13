"""Alpaca, mapped onto the execution contract.

This adapter's job is TRANSPORT and TRANSLATION. Every behavioural rule — when to
retry, what UNKNOWN means, whether an observation may support a conclusion —
lives above it and is certified once against the simulator. What is certified
HERE is only that Alpaca's messy reality maps onto the contract's vocabulary
correctly.

## Three things this does that the Stocker adapter does not

**It paginates, and admits when it did not finish.** The complete open-order set
pages backwards through Alpaca's stable `before_order_id` cursor and reports
`TRUNCATED` at the declared cap. A separate bounded closed-order traversal
recovers the interval since the durable processed watermark (plus overlap),
also by `before_order_id`; it never mixes timestamp filters with that cursor.
An inherited account's unbounded archive is not an open-order completeness
dependency. Exact durable-key lookup supplies additional positive evidence for
known commands that disappear from the open set.

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
from urllib.parse import quote

from sentinel.execution.contract import (
    BrokerAccountIdentity, BrokerAccountSnapshot, BrokerCapabilities, BrokerFill,
    BrokerInstrument, BrokerObservation, BrokerOrder, BrokerPosition, CommandOutcome,
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


class MalformedBrokerPayload(RuntimeError):
    """The broker sent a field this adapter cannot read as economics.

    Same rule as `UnmappedBrokerStatus`, applied to the other half of the
    payload. Status was strict and side/quantity were not, and the asymmetry
    was the wrong way round: a status is a hint about lifecycle, whereas side
    and quantity ARE the trade.

    ```text
    {"side": null, "qty": "garbage"}   ->   SELL, quantity 0
    ```

    `side` fell out of `BUY if payload["side"] == "buy" else SELL`, so anything
    that was not exactly "buy" became a SALE. `qty` fell back to `Decimal(0)`.
    The surrounding observation could then still be labelled COMPLETE, which
    makes corrupt evidence indistinguishable from a flat, quiet account — and
    a COMPLETE read of a flat account is what authorises increases.

    Raised, so the observation is unusable and the appliance holds.
    """


#: The only two sides that exist. A mapping rather than an `== "buy"` test so
#: that a value which is neither is VISIBLE rather than silently one of them.
_SIDES = {"buy": "BUY", "sell": "SELL"}


def _side(raw, *, where: str):
    from sentinel.execution.contract import Side
    key = str(raw).strip().lower() if raw is not None else ""
    if key not in _SIDES:
        raise MalformedBrokerPayload(
            f"{where}: side {raw!r} is neither 'buy' nor 'sell'. Refusing to "
            f"guess — the previous default turned every unrecognised value, "
            f"including null, into a SELL.")
    return Side.BUY if _SIDES[key] == "BUY" else Side.SELL


def _required_dec(value, *, where: str, allow_negative: bool = False) -> Decimal:
    """A quantity or price that MUST be readable.

    `_dec(..., Decimal(0))` returns zero for null, for "", and for "garbage"
    alike. Zero is a meaningful economic answer — nothing filled, nothing held
    — so an unreadable field became a confident statement about the account.
    """
    if value is None or value == "":
        raise MalformedBrokerPayload(
            f"{where}: missing. A missing quantity is not zero; zero is a "
            f"claim about the account and this is an absence of evidence.")
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise MalformedBrokerPayload(
            f"{where}: {value!r} is not a number.") from None
    if not out.is_finite():
        raise MalformedBrokerPayload(f"{where}: {value!r} is not finite.")
    if out < 0 and not allow_negative:
        raise MalformedBrokerPayload(
            f"{where}: {out} is negative. The envelope is long-only and a "
            f"negative quantity here is corrupt evidence, not a short.")
    return out


def _required_bool(payload: dict, key: str, *, where: str) -> bool:
    """Read an availability flag without treating malformed silence as False."""
    value = payload.get(key)
    if type(value) is not bool:  # bool is exact here; JSON 0/1 are malformed.
        raise MalformedBrokerPayload(
            f"{where}: {key} must be an explicit boolean, got {value!r}")
    return value


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
                 from_broker_symbol=None,
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
        self._from_symbol = (from_broker_symbol
                             or (lambda s: s.replace(".", "-")))
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
        return self._account_identity(payload)

    async def account_snapshot(self) -> BrokerAccountSnapshot:
        payload = await self._get("/v2/account")
        identity = self._account_identity(payload)
        return BrokerAccountSnapshot(
            identity=identity,
            equity=_required_dec(payload.get("equity"), where="account equity"),
            cash=_required_dec(payload.get("cash"), where="account cash",
                               allow_negative=True),
            buying_power=_required_dec(
                payload.get("buying_power"), where="account buying power",
                allow_negative=True),
            multiplier=_required_dec(
                payload.get("multiplier"), where="account multiplier"),
            status=str(payload.get("status") or ""),
            trading_blocked=_required_bool(
                payload, "trading_blocked", where="account"),
            account_blocked=_required_bool(
                payload, "account_blocked", where="account"),
            trade_suspended_by_user=_required_bool(
                payload, "trade_suspended_by_user", where="account"))

    @staticmethod
    def _account_identity(payload: dict) -> BrokerAccountIdentity:
        if not isinstance(payload, dict):
            raise MalformedBrokerPayload(
                "account payload must be an object")
        identity = BrokerAccountIdentity(
            broker="alpaca",
            account_id=str(payload.get("account_number") or payload.get("id") or ""),
            raw=payload)
        if not identity.account_id:
            raise MalformedBrokerPayload(
                "account payload has no account_number or id")
        return identity

    async def resolve_instrument(self, *, security_id: str,
                                 symbol: str) -> BrokerInstrument:
        """Resolve and verify Alpaca's stable asset identity before submit."""
        broker_symbol = self._to_symbol(symbol)
        payload = await self._get(f"/v2/assets/{quote(broker_symbol, safe='')}")
        if not isinstance(payload, dict):
            raise MalformedBrokerPayload(
                f"asset lookup for {symbol!r} must return an object")
        returned_symbol = str(payload.get("symbol") or "")
        asset_id = str(payload.get("id") or "")
        if not returned_symbol or not asset_id:
            raise MalformedBrokerPayload(
                f"asset lookup for {symbol!r} omitted symbol or stable asset id")
        if str(payload.get("status") or "").lower() != "active":
            raise MalformedBrokerPayload(
                f"asset {returned_symbol!r} is not active")
        if payload.get("tradable") is not True:
            raise MalformedBrokerPayload(
                f"asset {returned_symbol!r} is not tradable")
        instrument = self._instrument(returned_symbol, asset_id)
        if instrument.security_id != str(security_id):
            raise MalformedBrokerPayload(
                f"asset {returned_symbol!r}/{asset_id} resolves to permanent "
                f"security {instrument.security_id!r}, not requested "
                f"{security_id!r}")
        return instrument

    # -- observation --------------------------------------------------------
    async def observe(self) -> BrokerObservation:
        """Orders, positions, orders again. See the contract §5.3."""
        return await self._observe_snapshot()

    async def observe_with_terminal_recovery(
            self, *, submitted_after: datetime,
            processed_through: datetime) -> BrokerObservation:
        """Observe open truth plus a bounded, replayable closed interval."""
        floor = _required_aware_ts(
            submitted_after, where="terminal recovery floor")
        checkpoint = _required_aware_ts(
            processed_through, where="processed terminal watermark")
        recovery_through = datetime.now(timezone.utc)
        if recovery_through < checkpoint:
            raise MalformedBrokerPayload(
                "terminal recovery clock is behind the durable processed "
                f"watermark ({recovery_through.isoformat()} < "
                f"{checkpoint.isoformat()}); refusing to skip broker history")
        return await self._observe_snapshot(
            terminal_floor=floor, recovery_through=recovery_through)

    async def _observe_snapshot(
            self, *, terminal_floor: Optional[datetime] = None,
            recovery_through: Optional[datetime] = None) -> BrokerObservation:
        opened, complete_open_a = await self._list_open_orders()
        terminal_a: list = []
        complete_terminal_a = True
        if terminal_floor is not None:
            terminal_a, complete_terminal_a = await self._list_closed_orders(
                floor=terminal_floor, through=recovery_through)
        orders, merged_a = _merge_order_sets(opened, terminal_a)

        positions = await self._list_positions()

        reopened, complete_open_b = await self._list_open_orders()
        terminal_b: list = []
        complete_terminal_b = True
        if terminal_floor is not None:
            terminal_b, complete_terminal_b = await self._list_closed_orders(
                floor=terminal_floor, through=recovery_through)
        recheck, merged_b = _merge_order_sets(reopened, terminal_b)

        completeness = Completeness.COMPLETE
        if not (complete_open_a and complete_open_b
                and complete_terminal_a and complete_terminal_b):
            completeness = Completeness.TRUNCATED
        elif (not merged_a or not merged_b
              or _fingerprint(recheck) != _fingerprint(orders)):
            completeness = Completeness.INCONSISTENT

        return BrokerObservation(
            observed_at=datetime.now(timezone.utc), orders=tuple(recheck),
            positions=tuple(positions), completeness=completeness,
            terminal_recovery_through=recovery_through)

    async def _list_open_orders(self):
        """Page all currently open orders by stable exclusive broker id."""
        out: list = []
        seen_ids: set[str] = set()
        before_order_id: Optional[str] = None
        for _page in range(MAX_PAGES):
            params = {"status": "open", "limit": PAGE_SIZE,
                      "direction": "desc"}
            if before_order_id:
                params["before_order_id"] = before_order_id
            page = await self._get("/v2/orders", params)
            if not isinstance(page, list):
                raise MalformedBrokerPayload(
                    "open-order response must be an array")
            if len(page) > PAGE_SIZE:
                raise MalformedBrokerPayload(
                    f"open-order page contains {len(page)} rows for limit "
                    f"{PAGE_SIZE}")
            if not page:
                return out, True
            page_ids: list[str] = []
            for item in page:
                if not isinstance(item, dict):
                    raise MalformedBrokerPayload(
                        "open-order page contains a non-object row")
                order_id = str(item.get("id") or "").strip()
                if not order_id:
                    raise MalformedBrokerPayload(
                        "open-order row has no broker order id")
                if order_id in seen_ids:
                    raise MalformedBrokerPayload(
                        f"open-order pagination repeated broker id "
                        f"{order_id}")
                seen_ids.add(order_id)
                page_ids.append(order_id)
                out.append(self._to_order(item))
            if len(page) < PAGE_SIZE:
                return out, True
            next_cursor = page_ids[-1]
            if not next_cursor or next_cursor == before_order_id:
                # Cannot advance the stable exclusive cursor, so we cannot
                # claim completeness. A timestamp cursor is not a fallback:
                # tied submitted_at values at a page boundary would be skipped.
                return out, False
            before_order_id = next_cursor
        # HIT THE CAP. There may be more, and saying "complete" here is the
        # unstated assumption the contract exists to remove.
        log.warning("sentinel: %s order list hit the %d-page cap; reporting "
                    "TRUNCATED rather than assuming completeness",
                    "open", MAX_PAGES)
        return out, False

    async def _list_closed_orders(self, *, floor: datetime,
                                  through: datetime):
        """Page closed history until a validated page crosses ``floor``.

        Alpaca forbids timestamp filters with its order-id cursors. Submission
        times are therefore validated locally, and equality with the inclusive
        floor continues because a timestamp tie can span a page boundary.
        """
        floor = _required_aware_ts(floor, where="terminal recovery floor")
        through = _required_aware_ts(
            through, where="terminal recovery upper boundary")
        if floor > through:
            raise MalformedBrokerPayload(
                "terminal recovery floor is later than its captured upper "
                "boundary")

        out: list = []
        seen_ids: set[str] = set()
        before_order_id: Optional[str] = None
        previous_submitted: Optional[datetime] = None
        for _page in range(MAX_PAGES):
            params = {"status": "closed", "limit": PAGE_SIZE,
                      "direction": "desc"}
            if before_order_id:
                params["before_order_id"] = before_order_id
            page = await self._get("/v2/orders", params)
            if not isinstance(page, list):
                raise MalformedBrokerPayload(
                    "closed-order response must be an array")
            if len(page) > PAGE_SIZE:
                raise MalformedBrokerPayload(
                    f"closed-order page contains {len(page)} rows for limit "
                    f"{PAGE_SIZE}")
            if not page:
                return out, True

            page_ids: list[str] = []
            oldest: Optional[datetime] = None
            for item in page:
                if not isinstance(item, dict):
                    raise MalformedBrokerPayload(
                        "closed-order page contains a non-object row")
                order_id = str(item.get("id") or "").strip()
                if not order_id:
                    raise MalformedBrokerPayload(
                        "closed-order row has no broker order id")
                if order_id in seen_ids:
                    raise MalformedBrokerPayload(
                        "closed-order pagination repeated broker id "
                        f"{order_id}")
                seen_ids.add(order_id)
                page_ids.append(order_id)

                submitted = _required_aware_ts(
                    item.get("submitted_at"),
                    where=f"closed order {order_id} submitted_at")
                if (previous_submitted is not None
                        and submitted > previous_submitted):
                    raise MalformedBrokerPayload(
                        "closed-order pagination is not descending by "
                        f"submitted_at at broker order {order_id}")
                previous_submitted = submitted
                oldest = submitted
                if floor <= submitted <= through:
                    out.append(self._to_order(item))

            if len(page) < PAGE_SIZE:
                return out, True
            if oldest is not None and oldest < floor:
                return out, True
            next_cursor = page_ids[-1]
            if not next_cursor or next_cursor == before_order_id:
                return out, False
            before_order_id = next_cursor

        log.warning(
            "sentinel: closed-order recovery hit the %d-page cap before "
            "crossing %s; reporting TRUNCATED",
            MAX_PAGES, floor.isoformat())
        return out, False

    async def _list_positions(self):
        payload = await self._get("/v2/positions")
        if not isinstance(payload, list):
            raise MalformedBrokerPayload(
                "positions response must be an array")
        out = []
        seen_security_ids: set[str] = set()
        for p in payload:
            if not isinstance(p, dict):
                raise MalformedBrokerPayload(
                    "positions response contains a non-object row")
            symbol = str(p.get("symbol") or "")
            # A POSITION quantity may legitimately be negative at a broker
            # (a short), and Sentinel's envelope forbids holding one — so it is
            # read faithfully and refused upstream, rather than being read as
            # zero here, which would make a short position INVISIBLE.
            qty = _required_dec(p.get("qty"), allow_negative=True,
                                where=f"position {p.get('symbol')} qty")
            instrument = self._instrument(symbol, p.get("asset_id"))
            if instrument.security_id in seen_security_ids:
                raise MalformedBrokerPayload(
                    "positions response repeats permanent security "
                    f"{instrument.security_id}")
            seen_security_ids.add(instrument.security_id)
            out.append(BrokerPosition(
                instrument=instrument, quantity=qty or Decimal(0)))
        return out

    def _instrument(self, symbol: str, asset_id=None, *, as_of=None
                    ) -> BrokerInstrument:
        system_symbol = self._from_symbol(symbol)
        try:
            security_id = self._resolve(system_symbol, as_of)
        except TypeError:
            # Backward-compatible test/custom resolvers may accept only the
            # symbol. Production accepts the point-in-time session as well.
            security_id = self._resolve(system_symbol)
        if security_id is None or not str(security_id).strip():
            raise MalformedBrokerPayload(
                f"instrument {symbol!r} has no permanent security identity")
        return BrokerInstrument(security_id=str(security_id),
                                symbol=system_symbol,
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
            instrument=self._instrument(
                symbol, payload.get("asset_id"),
                as_of=str(payload.get("submitted_at") or "")[:10] or None),
            side=_side(payload.get("side"),
                       where=f"order {payload.get('id')} side"),
            state=map_status(raw_status),
            quantity=_required_dec(payload.get("qty"),
                                   where=f"order {payload.get('id')} qty"),
            filled_quantity=_required_dec(
                payload.get("filled_qty"),
                where=f"order {payload.get('id')} filled_qty"),
            filled_average_price=(
                _required_dec(
                    payload.get("filled_avg_price"),
                    where=f"order {payload.get('id')} filled_avg_price")
                if payload.get("filled_avg_price") not in (None, "") else None),
            submitted_at=_parse_ts(payload.get("submitted_at")),
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
                quantity=_required_dec(a.get("qty"),
                                       where=f"activity {a.get('id')} qty"),
                price=_required_dec(a.get("price"),
                                    where=f"activity {a.get('id')} price"),
                filled_at=_parse_ts(a.get("transaction_time"))))
        return tuple(out)


def _fingerprint(orders) -> tuple:
    return tuple(sorted((
        o.broker_order_id, o.client_key or "", o.instrument.security_id,
        o.side.value, str(o.quantity), o.state.value, str(o.filled_quantity),
        str(o.filled_average_price) if o.filled_average_price is not None else "",
        o.submitted_at.isoformat() if o.submitted_at is not None else "",
    ) for o in orders))


def _merge_order_sets(opened, closed) -> tuple[list, bool]:
    """Merge one bounded read; overlap means open/closed raced."""
    merged = {order.broker_order_id: order for order in opened}
    stable = True
    for order in closed:
        if order.broker_order_id in merged:
            stable = False
        merged[order.broker_order_id] = order
    return list(merged.values()), stable


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


def _required_aware_ts(value, *, where: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = _parse_ts(value)
    if parsed is None or parsed.tzinfo is None:
        raise MalformedBrokerPayload(
            f"{where} must be a parseable timezone-aware timestamp")
    return parsed.astimezone(timezone.utc)
