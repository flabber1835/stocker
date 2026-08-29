"""Canonical Alpaca PAPER execution adapter.

The final broker semantics are expressed by ordinary classes and functions in
this module. Importing :mod:`sentinel.execution` does not patch broker, journal,
reconciliation, authority, or executor modules. The private ``_alpaca_base``
module retains the reviewed transport implementation; the two classes below
statically compose the hardened observation boundary and the final
financial-grade adapter.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Mapping, Optional, Sequence
from urllib.parse import quote

from sentinel.execution import _alpaca_base as alpaca
from sentinel.execution import broker_cash, contract, journal
from sentinel.execution.broker_cash import (
    BrokerCashActivity,
    BrokerCashActivityBatch,
    RECOGNIZED_ACTIVITY_TYPES,
)
from sentinel.execution.guarded import BrokerAuthorityRefused
from sentinel.execution.identity import is_sentinel_key
from sentinel.execution.states import CommandState, TERMINAL
from sentinel.feed import calendar

# Preserve the public helper/exception surface of the original module. This
# copies references only; it never mutates the retained base.
for _name in dir(alpaca):
    if not _name.startswith("__"):
        globals().setdefault(_name, getattr(alpaca, _name))

_ACTIVITY_BUSINESS_TIME_FLOOR = datetime(1970, 1, 1, tzinfo=timezone.utc)
ACTIVITY_FILL_INTERVAL_SOURCE = "alpaca_trading_activity_sse_candidate"
ACTIVITY_FILL_INTERVAL_SEMANTICS = (
    "ALPACA_ACCOUNT_ACTIVITY_FIXED_EVENT_FRONTIER_UNACCEPTED_V1"
)
_OBSERVATION_PREFIX = "broker-observation:v2:"
_WITNESS_PREFIX = "terminal-recovery-witness:v3:"
_PROVENANCE_PREFIX = _OBSERVATION_PREFIX
_DB_INCARCERATION_CURSOR = "broker-recovery-db-incarnation:v1"
_DB_CURSOR = _DB_INCARCERATION_CURSOR

class ActivityCorrectionRequiresRecovery(RuntimeError):
    """A correction/bust needs reversal semantics before trading may continue."""

class RestoreGradeIncreaseDeferred(RuntimeError):
    """A database takeover has not yet made predecessor DAY orders harmless."""

def _loads_state(raw, *, where: str) -> dict:
    if isinstance(raw, dict):
        value = raw
    else:
        try:
            value = json.loads(str(raw))
        except Exception as exc:
            raise RuntimeError(f"{where} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{where} must be a JSON object")
    return value

def _sse_events(text: str, *, malformed) -> tuple[dict, ...]:
    """Parse a bounded Alpaca SSE response; comments that signal loss refuse."""
    events: list[dict] = []
    data: list[str] = []

    def flush() -> None:
        if not data:
            return
        payload = "\n".join(data)
        data.clear()
        try:
            event = json.loads(payload)
        except Exception as exc:
            raise malformed("Activity SSE contained malformed JSON") from exc
        if not isinstance(event, dict):
            raise malformed("Activity SSE data event must be a JSON object")
        events.append(event)

    for raw in str(text).splitlines():
        line = raw.rstrip("\r")
        if line.startswith(":"):
            lowered = line.lower()
            if "dropped" in lowered or "internal server error" in lowered:
                raise malformed(
                    "Activity SSE reported message loss/server failure; "
                    "history is not complete")
            continue
        if line == "":
            flush()
            continue
        if line.startswith("data:"):
            data.append(line[5:].lstrip())
            continue
        # event/id/retry fields are transport metadata. Unknown non-comment,
        # non-SSE fields are not ignored because doing so can hide corruption.
        if line.startswith(("event:", "id:", "retry:")):
            continue
        raise malformed(f"Activity SSE contained unknown line {line!r}")
    flush()
    return tuple(events)

def _json(raw, *, where: str) -> dict:
    if isinstance(raw, dict):
        value = raw
    else:
        try:
            value = json.loads(str(raw))
        except Exception as exc:
            raise RuntimeError(f"{where} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{where} must be a JSON object")
    return value

class AccountBoundObservation(contract.BrokerObservation):
    """Observation carrying the account identity that bracketed its reads."""

    account_identity: Optional[contract.BrokerAccountIdentity] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.account_identity is not None:
            if (not self.account_identity.broker
                    or not self.account_identity.account_id):
                raise ValueError("account-bound observation identity is incomplete")

class NativeBrokerFill(contract.BrokerFill):
    """Fill whose broker-native activity id is the idempotency authority."""

    activity_id: Optional[str] = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.activity_id is not None and not str(self.activity_id).strip():
            raise ValueError("native fill activity id must be non-empty")

OriginalAlpaca = alpaca.AlpacaExecutionBroker

class HardenedAlpacaExecutionBroker(OriginalAlpaca):
    """Alpaca adapter with account, asset and activity evidence tightened."""

    def _validate_submit_response(
            self, payload, *, client_key: str,
            instrument: contract.BrokerInstrument,
            side: contract.Side, quantity: Decimal):
        # Alpaca represents a simple order as either "" or "simple".  PR
        # #184's validator accepted only the latter, turning a valid 2xx into
        # false uncertainty.  Normalize only this documented equivalence;
        # bracket/oco/oto values still fail closed in the original validator.
        if isinstance(payload, dict) and payload.get("order_class") == "":
            payload = dict(payload)
            payload["order_class"] = "simple"
        return super()._validate_submit_response(
            payload, client_key=client_key, instrument=instrument,
            side=side, quantity=quantity)

    async def account_cash_activities(
            self, *, after: datetime,
            through: datetime) -> BrokerCashActivityBatch:
        floor = alpaca._required_aware_ts(
            after, where="cash activity lower boundary")
        upper = alpaca._required_aware_ts(
            through, where="cash activity upper boundary")
        if floor > upper:
            raise alpaca.MalformedBrokerPayload(
                "cash activity lower boundary is later than upper boundary")

        activities: list[BrokerCashActivity] = []
        seen_ids: set[str] = set()
        page_token: Optional[str] = None
        last_recognized_id: Optional[str] = None
        for _page in range(alpaca.MAX_ACTIVITY_PAGES):
            # Category, not a fixed activity-type allowlist.  A vendor-added
            # non-zero cash type must reach Sentinel and become a refusal;
            # filtering it at the request would make the negative space
            # unknowable and could defeat cash authority.
            params = {
                "category": "non_trade_activity",
                "after": floor.isoformat(),
                "until": upper.isoformat(),
                "direction": "asc",
                "page_size": alpaca.ACTIVITY_PAGE_SIZE,
            }
            if page_token:
                params["page_token"] = page_token
            page = await self._get("/v2/account/activities", params)
            if not isinstance(page, list):
                raise alpaca.MalformedBrokerPayload(
                    "account-activities response must be an array")
            if len(page) > alpaca.ACTIVITY_PAGE_SIZE:
                raise alpaca.MalformedBrokerPayload(
                    "account-activities page exceeds requested page size")
            if not page:
                return BrokerCashActivityBatch(
                    activities=tuple(activities), processed_through=upper,
                    completeness=contract.Completeness.COMPLETE,
                    last_activity_id=last_recognized_id)

            page_ids: list[str] = []
            for item in page:
                if not isinstance(item, dict):
                    raise alpaca.MalformedBrokerPayload(
                        "account-activities page contains a non-object row")
                activity_id = str(item.get("id") or "").strip()
                if not activity_id:
                    raise alpaca.MalformedBrokerPayload(
                        "account activity row has no native activity id")
                if activity_id in seen_ids:
                    raise alpaca.MalformedBrokerPayload(
                        "account-activities pagination repeated native id "
                        f"{activity_id}")
                seen_ids.add(activity_id)
                page_ids.append(activity_id)
                activity_type = str(
                    item.get("activity_type") or "").upper()
                amount = alpaca._required_dec(
                    item.get("net_amount"),
                    where=f"account activity {activity_id} net_amount",
                    allow_negative=True)
                if activity_type not in RECOGNIZED_ACTIVITY_TYPES:
                    if amount == 0:
                        # A non-cash corporate event is outside this cash
                        # ledger. Its native id still participates in page
                        # progress, but it does not pretend to be cash.
                        continue
                    raise alpaca.MalformedBrokerPayload(
                        "unrecognized non-trade cash activity "
                        f"{activity_id}: type={activity_type!r}, "
                        f"net_amount={amount}")
                try:
                    activity_date = date.fromisoformat(
                        str(item.get("date") or "")[:10])
                except ValueError:
                    raise alpaca.MalformedBrokerPayload(
                        f"account activity {activity_id} has invalid date "
                        f"{item.get('date')!r}") from None
                activities.append(BrokerCashActivity(
                    activity_id=activity_id,
                    activity_type=activity_type,
                    activity_date=activity_date,
                    net_amount=amount,
                    raw=item,
                ))
                last_recognized_id = activity_id

            if len(page) < alpaca.ACTIVITY_PAGE_SIZE:
                return BrokerCashActivityBatch(
                    activities=tuple(activities), processed_through=upper,
                    completeness=contract.Completeness.COMPLETE,
                    last_activity_id=last_recognized_id)
            next_token = page_ids[-1]
            if not next_token or next_token == page_token:
                return BrokerCashActivityBatch(
                    activities=tuple(activities), processed_through=upper,
                    completeness=contract.Completeness.TRUNCATED,
                    last_activity_id=last_recognized_id)
            page_token = next_token

        return BrokerCashActivityBatch(
            activities=tuple(activities), processed_through=upper,
            completeness=contract.Completeness.TRUNCATED,
            last_activity_id=last_recognized_id)

    async def _recent_fills_bounded(
            self, since: datetime,
            through: Optional[datetime]) -> Sequence[contract.BrokerFill]:
        floor = alpaca._required_aware_ts(
            since, where="fill activity lower boundary")
        upper = (alpaca._required_aware_ts(
            through, where="fill activity upper boundary")
                 if through is not None else None)
        if upper is not None and floor > upper:
            raise alpaca.MalformedBrokerPayload(
                "fill activity lower boundary is later than upper boundary")
        out: list[contract.BrokerFill] = []
        seen_ids: set[str] = set()
        page_token: Optional[str] = None
        for _page in range(alpaca.MAX_ACTIVITY_PAGES):
            params = {
                "after": floor.isoformat(),
                "direction": "asc",
                "page_size": alpaca.ACTIVITY_PAGE_SIZE,
            }
            if upper is not None:
                params["until"] = upper.isoformat()
            if page_token:
                params["page_token"] = page_token
            page = await self._get("/v2/account/activities/FILL", params)
            if not isinstance(page, list):
                raise alpaca.MalformedBrokerPayload(
                    "fill activities response must be an array")
            if len(page) > alpaca.ACTIVITY_PAGE_SIZE:
                raise alpaca.MalformedBrokerPayload(
                    "fill activities page exceeds requested page size")
            if not page:
                return tuple(out)
            page_ids: list[str] = []
            for item in page:
                if not isinstance(item, dict):
                    raise alpaca.MalformedBrokerPayload(
                        "fill activities page contains a non-object row")
                activity_id = str(item.get("id") or "").strip()
                if not activity_id:
                    raise alpaca.MalformedBrokerPayload(
                        "fill activity has no broker-native id")
                if activity_id in seen_ids:
                    raise alpaca.MalformedBrokerPayload(
                        "fill activity pagination repeated native id "
                        f"{activity_id}")
                seen_ids.add(activity_id)
                page_ids.append(activity_id)
                broker_order_id = str(item.get("order_id") or "").strip()
                if not broker_order_id:
                    raise alpaca.MalformedBrokerPayload(
                        f"fill activity {activity_id} omitted order_id")
                out.append(NativeBrokerFill(
                    activity_id=activity_id,
                    client_key=None,
                    broker_order_id=broker_order_id,
                    quantity=alpaca._required_dec(
                        item.get("qty"),
                        where=f"activity {activity_id} qty"),
                    price=alpaca._required_dec(
                        item.get("price"),
                        where=f"activity {activity_id} price"),
                    filled_at=alpaca._parse_ts(
                        item.get("transaction_time")),
                ))
            if len(page) < alpaca.ACTIVITY_PAGE_SIZE:
                return tuple(out)
            next_token = page_ids[-1]
            if not next_token or next_token == page_token:
                raise alpaca.MalformedBrokerPayload(
                    "fill activity pagination cannot prove completeness")
            page_token = next_token
        raise alpaca.MalformedBrokerPayload(
            "fill activity traversal hit its page cap; refusing to imply "
            "complete recovery history")

    async def recent_fills(
            self, since: datetime) -> Sequence[contract.BrokerFill]:
        return await self._recent_fills_bounded(since, None)

    async def _observe_snapshot(
            self, *, terminal_floor: Optional[datetime] = None,
            recovery_through: Optional[datetime] = None):
        # The base adapter already binds ordinary snapshots with identity
        # reads around every major phase.  This overlay needs an additional
        # outer fence only when it adds fill-activity recovery work.
        if terminal_floor is None:
            return await super()._observe_snapshot(
                terminal_floor=terminal_floor,
                recovery_through=recovery_through)
        account_before = await self.identify_account()
        observed = await super()._observe_snapshot(
            terminal_floor=terminal_floor,
            recovery_through=recovery_through)

        # A fill activity is keyed to when the economic event occurred, not
        # to the order's ancient submitted_at.  Join a newly reported fill
        # back to its exact order so a CANCELLED/FILLED command cannot age
        # out of closed-order pagination and then mutate silently (#127).
        orders = list(observed.orders)
        known_order_ids = {o.broker_order_id for o in orders}
        if terminal_floor is not None:
            fills = await self._recent_fills_bounded(
                terminal_floor, recovery_through)
            for fill in fills:
                if fill.broker_order_id in known_order_ids:
                    continue
                payload = await self._get(
                    f"/v2/orders/{quote(fill.broker_order_id, safe='')}")
                if not isinstance(payload, dict):
                    raise alpaca.MalformedBrokerPayload(
                        "late-fill exact order lookup returned no order object")
                order = self._to_order(payload)
                if order.broker_order_id != fill.broker_order_id:
                    raise alpaca.MalformedBrokerPayload(
                        "late-fill exact order lookup changed broker order id")
                orders.append(order)
                known_order_ids.add(order.broker_order_id)

        account_after = await self.identify_account()
        completeness = observed.completeness
        if (account_after.broker != account_before.broker
                or account_after.account_id != account_before.account_id):
            completeness = contract.Completeness.INCONSISTENT

        return AccountBoundObservation(
            observed_at=observed.observed_at,
            orders=tuple(orders),
            positions=tuple(observed.positions),
            completeness=completeness,
            terminal_recovery_through=observed.terminal_recovery_through,
            account_identity=account_before,
        )

CurrentAlpaca = HardenedAlpacaExecutionBroker

class FinancialGradeAlpacaExecutionBroker(CurrentAlpaca):
    """Alpaca adapter using stable asset identity and unified Activity SSE."""

    # The generic flag historically implied more than Alpaca can prove from
    # open-order REST enumeration after a stale restore. Ordinary pagination
    # remains usable, but restore-grade safety is supplied by the independent
    # DB-incarnation/DAY-order fence below, not by this claim.
    capabilities = replace(
        CurrentAlpaca.capabilities,
        complete_order_pagination=False,
        recent_fill_history=False,
    )
    restore_grade_order_recovery = False
    account_snapshot_freshness = False
    # Candidate parser only. Alpaca's current changelog lists Activity SSE
    # for the Trading API, but method presence and documentation cannot
    # prove that this paper account's APCA credentials can reach the stream.
    # Keep every authority claim false until a real reachable account-bound
    # NAS integration passes acceptance; production guards cannot call it.
    financial_activity_sse = False
    candidate_financial_activity_sse = True
    candidate_account_fill_interval_evidence = True
    account_fill_interval_nas_accepted = False

    async def submit(
            self, *, client_key: str,
            instrument: contract.BrokerInstrument,
            side: contract.Side,
            quantity: Decimal) -> contract.CommandOutcome:
        if not instrument.broker_id:
            raise BrokerAuthorityRefused(
                "Alpaca submit requires the durable broker asset_id; "
                "ticker-only mutation is not certified")
        # Alpaca's create-order `symbol` parameter accepts an asset ID. Use
        # that stable handle directly so a symbol remap cannot retarget the
        # mutation between the final identity read and POST.
        body = {
            "symbol": str(instrument.broker_id),
            "qty": str(quantity),
            "side": "buy" if side is contract.Side.BUY else "sell",
            "type": "market",
            "time_in_force": "day",
            "client_order_id": client_key,
            "order_class": "simple",
            "extended_hours": False,
        }
        try:
            async with self._httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(
                    f"{self.base_url}/v2/orders",
                    headers=self._headers(), json=body)
        except Exception as exc:                          # noqa: BLE001
            return contract.CommandOutcome(
                state=CommandState.UNKNOWN,
                detail=f"{type(exc).__name__}: {exc}")

        if resp.status_code in (200, 201):
            try:
                payload = resp.json()
            except Exception as exc:                      # noqa: BLE001
                return contract.CommandOutcome(
                    state=CommandState.UNKNOWN,
                    detail=("2xx response body unreadable: "
                            f"{type(exc).__name__}: {exc}"))
            try:
                order = self._validate_submit_response(
                    payload, client_key=client_key,
                    instrument=instrument, side=side, quantity=quantity)
            except alpaca.IncompleteBrokerPayload as exc:
                broker_order_id = (
                    str(payload.get("id") or "")
                    if isinstance(payload, dict) else "")
                return contract.CommandOutcome(
                    state=CommandState.UNKNOWN,
                    broker_order_id=broker_order_id or None,
                    detail=f"incomplete 2xx acknowledgement: {exc}")
            return alpaca._submit_outcome(order)
        return alpaca._submit_error_outcome(resp)

    async def _bounded_activity_events(
            self, *, after: datetime,
            through: datetime,
            since_event_id: Optional[str] = None,
            verify_fixed_frontier: bool = False) -> tuple[dict, ...]:
        floor = alpaca._required_aware_ts(
            after, where="Activity SSE lower boundary")
        upper = alpaca._required_aware_ts(
            through, where="Activity SSE upper boundary")
        if floor > upper:
            raise alpaca.MalformedBrokerPayload(
                "Activity SSE lower boundary exceeds upper boundary")
        account = await self.identify_account()
        account_uuid = str(account.raw.get("id") or "").strip()
        if not account_uuid:
            raise alpaca.MalformedBrokerPayload(
                "Alpaca account payload has no UUID for Activity SSE binding")
        headers = dict(self._headers())
        headers["Accept"] = "text/event-stream"

        async def request(params: Mapping[str, str]) -> tuple[dict, ...]:
            try:
                async with self._httpx.AsyncClient(timeout=60.0) as client:
                    resp = await client.get(
                        f"{self.base_url}/v2beta1/events/activities",
                        headers=headers, params=dict(params))
            except Exception as exc:                      # noqa: BLE001
                raise RuntimeError(
                    "Activity SSE transport failed: "
                    f"{type(exc).__name__}: {exc}") from exc
            if resp.status_code in (401, 403):
                raise alpaca.AlpacaCredentialsRefused(
                    "Activity SSE authority refused with HTTP "
                    f"{resp.status_code}")
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Activity SSE returned HTTP {resp.status_code}")
            events = tuple(_sse_events(
                resp.text, malformed=alpaca.MalformedBrokerPayload))
            seen_event: set[str] = set()
            seen_ref: set[str] = set()
            prior_event = ""
            for event in events:
                event_id = str(event.get("event_id") or "").strip()
                ref_id = str(event.get("ref_id") or "").strip()
                event_account = str(event.get("account_id") or "").strip()
                if not event_id or not ref_id:
                    raise alpaca.MalformedBrokerPayload(
                        "Activity SSE event omitted event_id/ref_id")
                if event_account != account_uuid:
                    raise alpaca.MalformedBrokerPayload(
                        "Activity SSE event belongs to another account")
                # The cash and fill consumers below are USD ledgers and
                # accept only completed economic state changes.  Alpaca's
                # common envelope requires both fields; silently accepting
                # a missing/foreign currency would interpret local-currency
                # ``net_amount``/``price`` values as USD, while accepting a
                # non-final status could book economics before completion.
                currency = str(event.get("currency") or "").strip().upper()
                if currency != "USD":
                    raise alpaca.MalformedBrokerPayload(
                        f"Activity SSE event {event_id} currency "
                        f"{currency or '<missing>'!r} is not USD")
                status = str(event.get("status") or "").strip().lower()
                if status != "executed":
                    raise alpaca.MalformedBrokerPayload(
                        f"Activity SSE event {event_id} status "
                        f"{status or '<missing>'!r} is not executed")
                business_at = alpaca._required_aware_ts(
                    event.get("at"),
                    where=f"Activity SSE {event_id} business time")
                if not (floor <= business_at <= upper):
                    raise alpaca.MalformedBrokerPayload(
                        f"Activity SSE event {event_id} business time lies "
                        "outside the requested bounded snapshot")
                alpaca._required_aware_ts(
                    event.get("executed_at"),
                    where=f"Activity SSE {event_id} execution time")
                settle_date = event.get("settle_date")
                try:
                    if not isinstance(settle_date, str):
                        raise TypeError
                    date.fromisoformat(settle_date)
                except (TypeError, ValueError) as exc:
                    raise alpaca.MalformedBrokerPayload(
                        f"Activity SSE event {event_id} settle_date is "
                        "not an ISO date") from exc
                if event_id in seen_event:
                    raise alpaca.MalformedBrokerPayload(
                        f"Activity SSE repeated event_id {event_id}")
                if ref_id in seen_ref:
                    raise alpaca.MalformedBrokerPayload(
                        f"Activity SSE repeated ref_id {ref_id}")
                if prior_event and event_id <= prior_event:
                    raise alpaca.MalformedBrokerPayload(
                        "Activity SSE event_id order is not strictly monotonic")
                seen_event.add(event_id)
                seen_ref.add(ref_id)
                prior_event = event_id
                if not isinstance(event.get("details"), dict):
                    raise alpaca.MalformedBrokerPayload(
                        f"Activity SSE event {event_id} has no details object")
            return events

        # Timestamp filters establish only a *bounded snapshot*. They are
        # not a replay cursor because Alpaca filters business time (`at`),
        # while delayed/backfilled events append later in event_id order.
        snapshot = await request({
            "since": floor.isoformat(), "until": upper.isoformat()})
        if since_event_id is None:
            if verify_fixed_frontier:
                # Freeze the discovery response at its native publication
                # frontier, then demand a byte-for-byte equivalent replay.
                # For an empty account there is no event id to name, so the
                # exact bounded empty query is repeated instead.  Neither
                # case claims that a later backfill cannot append after the
                # captured frontier.
                if snapshot:
                    replay = await request({
                        "until_id": str(snapshot[-1]["event_id"])})
                else:
                    replay = await request({
                        "since": floor.isoformat(),
                        "until": upper.isoformat(),
                    })
                if replay != snapshot:
                    raise alpaca.MalformedBrokerPayload(
                        "Activity SSE fixed-frontier replay disagreed with "
                        "its exhaustive discovery snapshot")
            return snapshot
        cursor = str(since_event_id).strip()
        if not cursor:
            raise alpaca.MalformedBrokerPayload(
                "Activity SSE since_event_id must be non-empty")
        if not snapshot:
            # A retained cursor proves at least one event was previously
            # visible.  An empty exhaustive discovery snapshot contradicts
            # that retained source; treating it as "no changes" would hide
            # source truncation, account drift, or a vendor regression.
            raise alpaca.MalformedBrokerPayload(
                "Activity SSE exhaustive discovery omitted the retained "
                "event cursor")
        upper_event_id = str(snapshot[-1]["event_id"])
        if upper_event_id < cursor:
            raise alpaca.MalformedBrokerPayload(
                "Activity SSE bounded upper event_id regressed")
        if upper_event_id == cursor:
            return ()

        replay = await request({
            "since_id": cursor, "until_id": upper_event_id})
        if not replay or str(replay[-1]["event_id"]) != upper_event_id:
            raise alpaca.MalformedBrokerPayload(
                "Activity SSE cursor replay did not reach its bounded upper id")
        if str(replay[0]["event_id"]) < cursor:
            raise alpaca.MalformedBrokerPayload(
                "Activity SSE cursor replay crossed behind its durable id")
        return replay

    async def account_cash_activities(
            self, *, after: datetime,
            through: datetime,
            since_event_id: Optional[str] = None
            ) -> broker_cash.BrokerCashActivityBatch:
        requested_floor = alpaca._required_aware_ts(
            after, where="cash activity lower boundary")
        upper = alpaca._required_aware_ts(
            through, where="cash activity upper boundary")
        if requested_floor > upper:
            raise alpaca.MalformedBrokerPayload(
                "cash activity lower boundary exceeds upper boundary")
        events = await self._bounded_activity_events(
            # Never use the caller's business-time baseline for discovery.
            # Publication-order replay begins only after this exhaustive
            # snapshot has captured the current upper event_id.
            after=_ACTIVITY_BUSINESS_TIME_FLOOR, through=through,
            since_event_id=since_event_id)
        activities: list[broker_cash.BrokerCashActivity] = []
        last_ref: Optional[str] = None
        for event in events:
            previous_id = str(event.get("previous_id") or "").strip()
            details = event["details"]
            execution_type = str(details.get("execution_type") or "").lower()
            if previous_id or execution_type in {"trade_correct", "trade_bust"}:
                # Correction/bust arithmetic must reverse the prior ref_id.
                # Until that reversal is represented in the durable ledger,
                # treating the new event as another positive fill is unsafe.
                raise ActivityCorrectionRequiresRecovery(
                    "Activity SSE reported a correction/bust; cash/fill "
                    "authority is fenced until the prior ref_id is reversed")
            activity_type = str(event.get("activity_type") or "").upper()
            activity_subtype = str(
                event.get("activity_subtype") or "").upper()
            if activity_type == "TRD":
                # Sentinel's exact durable fill ledger already applies
                # trade notional to plan cash. Adding the Activity-SSE TRD
                # net_amount here would book the same purchase/sale twice.
                # The enclosing batch still advances its event_id cursor;
                # corrections/busts were refused above.
                continue
            if activity_type in {"ACATS", "FOPT", "JNLS"}:
                # These move securities across the owned account boundary.
                # A cash-only ledger cannot value or time-weight that
                # external in-kind flow, so it must never be silently
                # treated as strategy performance.
                raise broker_cash.BrokerCashAuthorityRefused(
                    "Activity SSE reported an unweighted external "
                    f"securities transfer ({activity_type})")
            if activity_type not in broker_cash.RECOGNIZED_ACTIVITY_TYPES:
                # Missing net_amount is not evidence that a newly added
                # vendor activity type has no economic effect. Refuse the
                # unknown taxonomy before any field-based filtering.
                raise alpaca.MalformedBrokerPayload(
                    "unrecognized Activity SSE cash/economic type "
                    f"{activity_type!r}")
            raw_amount = event.get("net_amount")
            if raw_amount is None:
                cash_amount_required = (
                    activity_type in (
                        broker_cash.EXTERNAL_ACTIVITY_TYPES
                        | frozenset({
                            "FEE", "CFEE", "INT", "INTNRA", "INTTW",
                            "WH", "CGD", "PTC", "PTR", "FIMAT",
                            "OPASN", "OPEXC", "OPTRD", "OPCSH",
                        }))
                    or (activity_type.startswith("DIV")
                        and activity_subtype != "SDIV")
                    or (activity_type == "MA"
                        and activity_subtype in {"CMA", "SCMA"})
                    or (activity_type == "OPCA"
                        and (activity_subtype.endswith("CMA")
                             or activity_subtype == "DIV.CDIV")))
                if cash_amount_required:
                    raise alpaca.MalformedBrokerPayload(
                        "Activity SSE cash event "
                        f"{event.get('event_id')} ({activity_type}) "
                        "omitted net_amount")
                continue
            amount = alpaca._required_dec(
                raw_amount,
                where=f"Activity SSE {event.get('event_id')} net_amount",
                allow_negative=True)
            if amount == 0:
                continue
            # The common-envelope validator above has already established
            # that this is the broker's required exact settlement date.
            # Execution time is not a substitute: changing which session
            # owns an external flow changes time-weighted performance.
            activity_date = date.fromisoformat(event["settle_date"])
            ref_id = str(event["ref_id"])
            activities.append(broker_cash.BrokerCashActivity(
                activity_id=ref_id,
                activity_type=activity_type,
                activity_date=activity_date,
                net_amount=amount,
                raw=event,
            ))
            last_ref = ref_id
        return broker_cash.BrokerCashActivityBatch(
            activities=tuple(activities),
            processed_through=upper,
            completeness=contract.Completeness.COMPLETE,
            last_activity_id=last_ref,
            last_event_id=(str(events[-1]["event_id"])
                           if events else since_event_id),
        )

    async def account_fill_interval_evidence(
            self, *, session: date,
            interval_start: datetime
            ) -> contract.BrokerFillIntervalEvidence:
        """Return a fixed-frontier, account-wide NAS acceptance candidate.

        ``Completeness.COMPLETE`` describes the terminated, exhaustively
        replayed snapshot through the captured boundary.  It is not cash or
        late-publication finality: the deliberately non-certified semantics
        and false capability bit prevent trial persistence until the paper
        endpoint and its correction/finality behavior pass NAS acceptance.
        """
        if type(session) is not date:
            raise alpaca.MalformedBrokerPayload(
                "fill interval requested session must be a date")
        requested_floor = alpaca._required_aware_ts(
            interval_start, where="fill interval lower boundary")
        from sentinel.feed import calendar  # noqa: PLC0415

        _opened, official_close = calendar.session_window(session)
        close_utc = official_close.astimezone(timezone.utc)
        if requested_floor > close_utc:
            raise alpaca.MalformedBrokerPayload(
                "fill interval begins after the requested official XNYS "
                "close")

        request_started_at = self._now()
        processed_through = request_started_at
        if processed_through < close_utc:
            raise alpaca.MalformedBrokerPayload(
                "fill interval cannot be observed before the requested "
                "official XNYS close")

        identity_before = await self.identify_account()
        native_before = str(
            identity_before.raw.get("id") or "").strip()
        if not native_before:
            raise alpaca.MalformedBrokerPayload(
                "Alpaca account payload has no UUID for fill-interval "
                "identity bracketing")
        events = await self._bounded_activity_events(
            after=_ACTIVITY_BUSINESS_TIME_FLOOR,
            through=processed_through,
            verify_fixed_frontier=True)
        identity_after = await self.identify_account()
        native_after = str(identity_after.raw.get("id") or "").strip()
        request_completed_at = self._now()
        if request_completed_at < request_started_at:
            raise alpaca.MalformedBrokerPayload(
                "Alpaca observation clock regressed during fill interval")
        if ((identity_before.broker, identity_before.account_id,
             native_before)
                != (identity_after.broker, identity_after.account_id,
                    native_after)):
            raise alpaca.MalformedBrokerPayload(
                "Alpaca account identity changed around Activity SSE "
                "fill-interval read")

        fills: list[contract.BrokerAccountFill] = []
        for event in events:
            details = event["details"]
            previous_id = str(event.get("previous_id") or "").strip()
            execution_type = str(
                details.get("execution_type") or "").strip().lower()
            if (previous_id
                    or execution_type in {"trade_correct", "trade_bust"}):
                raise ActivityCorrectionRequiresRecovery(
                    "Activity SSE reported a correction/bust inside the "
                    "account history; append-only fill evidence is refused")
            if str(event.get("activity_type") or "").upper() != "TRD":
                continue
            if execution_type != "fill":
                raise alpaca.MalformedBrokerPayload(
                    "TRD Activity SSE event has an unsupported or missing "
                    f"execution_type {execution_type or '<missing>'!r}")

            event_id = str(event["event_id"])
            ref_id = str(event["ref_id"])
            order_id = str(details.get("order_id") or "").strip()
            asset_id = str(details.get("asset_id") or "").strip()
            symbol = str(details.get("symbol") or "").strip()
            side = str(details.get("side") or "").strip().lower()
            if not order_id:
                raise alpaca.MalformedBrokerPayload(
                    f"TRD Activity SSE {event_id} omitted details.order_id")
            if not asset_id or not symbol or side not in {"buy", "sell"}:
                raise alpaca.MalformedBrokerPayload(
                    f"TRD Activity SSE {event_id} omitted native asset/"
                    "symbol/side identity")
            client_value = details.get("client_order_id")
            client_key = (None if client_value is None else
                          str(client_value).strip())
            if client_value is not None and not client_key:
                raise alpaca.MalformedBrokerPayload(
                    f"TRD Activity SSE {event_id} has an empty "
                    "details.client_order_id")

            quantity = alpaca._required_dec(
                event.get("qty"), where=f"TRD {event_id} qty")
            price = alpaca._required_dec(
                event.get("price"), where=f"TRD {event_id} price")
            if quantity <= 0 or price <= 0:
                raise alpaca.MalformedBrokerPayload(
                    f"TRD Activity SSE {event_id} quantity and price must "
                    "be positive")
            executed_at = alpaca._required_aware_ts(
                event.get("executed_at"),
                where=f"TRD {event_id} executed_at")
            if executed_at > processed_through:
                raise alpaca.MalformedBrokerPayload(
                    f"TRD Activity SSE {event_id} executes after the "
                    "fixed processed-through boundary")
            if executed_at < requested_floor:
                continue
            fills.append(contract.BrokerAccountFill(
                activity_id=ref_id,
                broker_order_id=order_id,
                client_key=client_key,
                quantity=quantity,
                price=price,
                filled_at=executed_at,
                raw=dict(event),
            ))

        fills.sort(key=lambda fill: (fill.filled_at, fill.activity_id))
        upper_event_id = (
            str(events[-1]["event_id"]) if events else "<EMPTY>")
        return contract.BrokerFillIntervalEvidence(
            identity=identity_before,
            requested_session=session,
            interval_start=requested_floor,
            processed_through=processed_through,
            fills=tuple(fills),
            completeness=contract.Completeness.COMPLETE,
            source=ACTIVITY_FILL_INTERVAL_SOURCE,
            semantics=ACTIVITY_FILL_INTERVAL_SEMANTICS,
            request_started_at=request_started_at,
            request_completed_at=request_completed_at,
            query=(
                ("endpoint", "/v2beta1/events/activities"),
                ("since", _ACTIVITY_BUSINESS_TIME_FLOOR.isoformat()),
                ("until", processed_through.isoformat()),
                ("upper_event_id", upper_event_id),
            ),
            raw={
                "events": [dict(event) for event in events],
                "upper_event_id": upper_event_id,
                "fixed_frontier_replayed": True,
                "late_publication_finality": False,
                "nas_acceptance_required": True,
            },
        )

    async def candidate_fill_interval_evidence(
            self, *, session: date,
            interval_start: datetime
            ) -> contract.BrokerFillIntervalEvidence:
        """Explicit acceptance-harness spelling for the guarded method."""
        return await self.account_fill_interval_evidence(
            session=session, interval_start=interval_start)

    async def _recent_fills_bounded(
            self, since: datetime,
            through: Optional[datetime]) -> Sequence[contract.BrokerFill]:
        upper = through or datetime.now(timezone.utc)
        requested_floor = alpaca._required_aware_ts(
            since, where="fill activity lower boundary")
        if requested_floor > upper:
            raise alpaca.MalformedBrokerPayload(
                "fill activity lower boundary exceeds upper boundary")
        # Terminal recovery cannot resume fill publication by business
        # timestamp: a fill may be backfilled after the durable terminal
        # watermark with an older ``at``/``executed_at``. Until fill
        # recovery owns its own durable event_id cursor, a bounded recovery
        # read deliberately traverses the complete Activity-SSE lifetime.
        # The unbounded diagnostic method retains its caller's time filter.
        event_floor = (
            _ACTIVITY_BUSINESS_TIME_FLOOR
            if through is not None else requested_floor)
        events = await self._bounded_activity_events(
            after=event_floor, through=upper)
        fills: list[contract.BrokerFill] = []
        for event in events:
            if str(event.get("activity_type") or "").upper() != "TRD":
                continue
            details = event["details"]
            execution_type = str(details.get("execution_type") or "fill").lower()
            if (event.get("previous_id")
                    or execution_type in {"trade_correct", "trade_bust"}):
                raise ActivityCorrectionRequiresRecovery(
                    "trade correction/bust cannot be flattened into an "
                    "append-only fill history")
            order_id = str(details.get("order_id") or "").strip()
            if not order_id:
                raise alpaca.MalformedBrokerPayload(
                    "TRD Activity SSE event omitted details.order_id")
            fills.append(NativeBrokerFill(
                activity_id=str(event["ref_id"]),
                client_key=(str(details.get("client_order_id"))
                            if details.get("client_order_id") else None),
                broker_order_id=order_id,
                quantity=alpaca._required_dec(
                    event.get("qty"),
                    where=f"TRD {event.get('event_id')} qty"),
                price=alpaca._required_dec(
                    event.get("price"),
                    where=f"TRD {event.get('event_id')} price"),
                filled_at=alpaca._required_aware_ts(
                    event.get("executed_at"),
                    where=f"TRD {event.get('event_id')} executed_at"),
            ))
        return tuple(fills)

    async def recent_fills(
            self, since: datetime) -> Sequence[contract.BrokerFill]:
        # Method remains available for diagnostics/reconciliation, but the
        # capability flag is intentionally false because a correction/bust
        # produces an explicit refusal rather than a lossy accounting row.
        return await self._recent_fills_bounded(
            since, datetime.now(timezone.utc))

    async def legacy_rest_recent_fills_probe(
            self, since: datetime) -> Sequence[contract.BrokerFill]:
        """Raw Account Activities REST fallback, diagnostic only."""
        return await super().recent_fills(since)

# Public adapter identity. Existing importers continue to ask for
# AlpacaExecutionBroker and receive the complete final class directly.
AlpacaExecutionBroker = FinancialGradeAlpacaExecutionBroker

def database_incarnation(conn, *, initialize: bool = True):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT (pg_control_system()).system_identifier::text,"
            " (pg_control_checkpoint()).timeline_id")
        system_identifier, timeline_id = cur.fetchone()
        cur.execute(
            "SELECT takeover_epoch,updated_at,broker,broker_account_id"
            " FROM sentinel_account_binding WHERE id=1")
        binding_row = cur.fetchone()
    if binding_row is None:
        raise RuntimeError("database incarnation check has no account binding")
    current = {
        "kind": "broker-recovery-db-incarnation/v1",
        "system_identifier": str(system_identifier),
        "timeline_id": int(timeline_id),
        "takeover_epoch": int(binding_row[0]),
    }
    with conn.cursor() as cur:
        cur.execute(
            "SELECT state FROM sentinel_processed_sessions"
            " WHERE cursor_name=%s",
            (_DB_INCARCERATION_CURSOR,),
        )
        row = cur.fetchone()
    if row is None:
        if not initialize:
            return None, current, binding_row
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO sentinel_processed_sessions"
                " (cursor_name,session,state) VALUES (%s,CURRENT_DATE,%s::jsonb)",
                (_DB_INCARCERATION_CURSOR,
                 json.dumps(current, sort_keys=True)),
            )
        conn.commit()
        return current, current, binding_row
    prior = _loads_state(row[0], where="database incarnation cursor")
    expected_keys = {"kind", "system_identifier", "timeline_id", "takeover_epoch"}
    if (set(prior) != expected_keys
            or prior.get("kind") != "broker-recovery-db-incarnation/v1"):
        raise RuntimeError("database incarnation cursor has unknown shape")
    return prior, current, binding_row

def _base_restore_increase_fence_reason(conn, deployment, today: date) -> str:
    prior, current, binding_row = database_incarnation(conn)
    assert prior is not None
    bound_epoch = int(binding_row[0])
    updated_at = binding_row[1]
    if not isinstance(updated_at, datetime) or updated_at.tzinfo is None:
        return "durable account binding has no trustworthy takeover timestamp"
    if (str(binding_row[2]) != deployment.broker
            or str(binding_row[3]) != deployment.broker_account_id
            or bound_epoch != deployment.takeover_epoch):
        return "execution deployment does not match the durable account binding"

    changed = (
        prior["system_identifier"] != current["system_identifier"]
        or int(prior["timeline_id"]) != int(current["timeline_id"])
    )
    if changed:
        if bound_epoch <= int(prior["takeover_epoch"]):
            return (
                "PostgreSQL incarnation/timeline changed since the last "
                "broker-recovery anchor. An explicit adopt-restored-account "
                "takeover is required before any exposure increase")
        # The operator acknowledged this new physical DB incarnation by
        # advancing the takeover epoch. Bind the new anchor to that epoch.
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE sentinel_processed_sessions SET session=CURRENT_DATE,"
                " state=%s::jsonb,updated_at=NOW() WHERE cursor_name=%s",
                (json.dumps(current, sort_keys=True),
                 _DB_INCARCERATION_CURSOR),
            )
        conn.commit()

    # The predecessor can still have an omitted working order after an
    # acknowledged takeover. Sentinel submits DAY orders only. Refuse BUYs
    # through the adoption calendar date; the next XNYS session is therefore
    # after every predecessor DAY order's contractual expiry boundary.
    if bound_epoch > 1 and today <= updated_at.date():
        return (
            "restored-account takeover occurred on "
            f"{updated_at.date().isoformat()}; exposure increases wait "
            "until a later session so predecessor DAY orders cannot remain "
            "executable even if Alpaca open-order enumeration omitted one")
    return ""

def upgrade_restore_reason(conn) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT state FROM sentinel_processed_sessions"
            " WHERE cursor_name=%s",
            (_DB_CURSOR,),
        )
        anchor = cur.fetchone()
        cur.execute(
            "SELECT takeover_epoch FROM sentinel_account_binding WHERE id=1")
        bound = cur.fetchone()
        cur.execute(
            "SELECT to_regclass('public.sentinel_backup_recovery_markers')")
        marker_relation = cur.fetchone()[0]
        marker_count = 0
        if marker_relation is not None:
            cur.execute("SELECT COUNT(*) FROM sentinel_backup_recovery_markers")
            marker_count = int(cur.fetchone()[0])
    if bound is None:
        return "restore-grade recovery has no durable account binding"
    if anchor is None and marker_count > 0 and int(bound[0]) <= 1:
        return (
            "backup-capable behavioral database predates the physical "
            "incarnation anchor. One explicit adopt-restored-account "
            "takeover is required before exposure increases; this prevents "
            "an already-restored database from silently self-certifying")
    return ""

def postmaster_day_order_fence_reason(conn, today) -> str:
    try:
        opened, closed = calendar.session_window(today)
    except Exception:
        # Non-session dates are already non-executable at the paper gateway;
        # this fence does not manufacture a calendar answer.
        return ""
    with conn.cursor() as cur:
        cur.execute("SELECT pg_postmaster_start_time()")
        row = cur.fetchone()
    if row is None or row[0] is None:
        return (
            "PostgreSQL start time is unavailable; restore-grade unknown "
            "DAY-order recovery cannot authorize exposure increases")
    started = row[0]
    if started.tzinfo is None:
        return (
            "PostgreSQL start time is timezone-naive; restore-grade unknown "
            "DAY-order recovery cannot authorize exposure increases")
    started = started.astimezone(opened.tzinfo)
    if opened <= started < closed:
        return (
            "PostgreSQL restarted during XNYS session "
            f"{today.isoformat()} at {started.isoformat()}. Exposure "
            "increases wait for a later session so any broker DAY order "
            "missing from a restored journal must have expired")
    return ""

def provenance_name(seq: int) -> str:
    return f"{_PROVENANCE_PREFIX}{int(seq)}"

def witness_name(broker_name: str, account_id: str) -> str:
    return f"{_WITNESS_PREFIX}{broker_name}:{account_id}"

def load_provenance(conn, seq: int) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT state FROM sentinel_processed_sessions"
            " WHERE cursor_name=%s",
            (provenance_name(seq),),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError(
            f"broker observation {seq} has no account/asset provenance")
    state = _json(row[0], where=f"broker observation {seq} provenance")
    if (state.get("kind") != "broker-observation/v2"
            or state.get("observation_seq") != int(seq)):
        raise RuntimeError(
            f"broker observation {seq} provenance shape is invalid")
    return state

def durable_covers_observed(*, command_row, observed_order: dict) -> bool:
    state = CommandState(str(command_row[5]))
    observed_state = CommandState(str(observed_order.get("state")))
    durable_filled = Decimal(str(command_row[7]))
    observed_filled = Decimal(
        str(observed_order.get("filled_quantity") or "0"))
    if durable_filled < observed_filled:
        return False
    # Terminal broker evidence must have been synchronized exactly. A
    # terminal command cannot legitimately move again later, so this check
    # remains stable forever.
    if observed_state in TERMINAL and state is not observed_state:
        return False
    # Nonterminal positive broker evidence cannot still be represented as a
    # local pre-transport state. Any later broker-facing/UNKNOWN state is a
    # processed state and may legitimately progress after this witness.
    if state in {CommandState.PLANNED, CommandState.SEND_PENDING}:
        return False
    return True

def completion_proof(conn, through: datetime):
    through = journal._aware_utc(through, "terminal recovery witness")
    broker_name, account_id, _ = journal._terminal_recovery_binding(conn)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT seq,observed_at FROM sentinel_observations"
            " WHERE terminal_recovery_through=%s AND completeness='COMPLETE'"
            " ORDER BY seq DESC",
            (through,),
        )
        candidates = cur.fetchall()

    for seq_raw, observed_at in candidates:
        seq = int(seq_raw)
        try:
            provenance = load_provenance(conn, seq)
        except RuntimeError:
            continue
        if (provenance.get("broker") != broker_name
                or provenance.get("account_id") != account_id
                or provenance.get("terminal_recovery_through")
                != through.isoformat()
                or provenance.get("completeness") != "COMPLETE"):
            continue

        immutable_commands = []
        complete = True
        for order in provenance.get("orders", []):
            key = order.get("client_key")
            if not is_sentinel_key(key):
                continue
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT security_id,symbol,broker_instrument_id,side,"
                    " quantity,state,broker_order_id,filled_quantity,"
                    " filled_average_price FROM sentinel_commands"
                    " WHERE client_key=%s",
                    (key,),
                )
                command = cur.fetchone()
            if command is None:
                complete = False
                break
            immutable = {
                "client_key": str(key),
                "security_id": str(command[0]),
                "symbol": str(command[1]),
                "broker_id": None if command[2] is None else str(command[2]),
                "side": str(command[3]),
                "quantity": str(command[4]),
                "broker_order_id": (
                    None if command[6] is None else str(command[6])),
            }
            observed_immutable = {
                "client_key": str(key),
                "security_id": str(order.get("security_id")),
                "symbol": str(order.get("symbol")),
                "broker_id": order.get("broker_id"),
                "side": str(order.get("side")),
                "quantity": str(order.get("quantity")),
                "broker_order_id": str(order.get("broker_order_id")),
            }
            if immutable != observed_immutable:
                complete = False
                break
            if not durable_covers_observed(
                    command_row=command, observed_order=order):
                complete = False
                break
            immutable_commands.append(immutable)
        if not complete:
            continue

        evidence = {
            "kind": "terminal-recovery-completion/v3",
            "observation_seq": seq,
            "observed_at": journal._aware_utc(
                observed_at, "broker observation").isoformat(),
            "processed_through": through.isoformat(),
            "provenance": provenance,
            "immutable_commands": sorted(
                immutable_commands, key=lambda item: item["client_key"]),
        }
        digest = hashlib.sha256(json.dumps(
            evidence, sort_keys=True, separators=(",", ":"),
            default=str).encode("utf-8")).hexdigest()
        return seq, digest
    return None

def strict_checkpoint(conn) -> datetime:
    broker_name, account_id, established_at = (
        journal._terminal_recovery_binding(conn))
    with conn.cursor() as cur:
        cur.execute(
            "SELECT broker,broker_account_id,processed_through"
            " FROM sentinel_terminal_recovery_watermark WHERE id=1")
        row = cur.fetchone()
    if row is None:
        return established_at
    if str(row[0]) != broker_name or str(row[1]) != account_id:
        raise RuntimeError(
            "terminal recovery watermark belongs to another account")
    processed = journal._aware_utc(
        row[2], "terminal recovery checkpoint")
    with conn.cursor() as cur:
        cur.execute(
            "SELECT state FROM sentinel_processed_sessions"
            " WHERE cursor_name=%s",
            (witness_name(broker_name, account_id),),
        )
        witness_row = cur.fetchone()
    if witness_row is None:
        # v1/v2/naked timestamps are not completion authority. Replay from
        # binding establishment once and earn a v3 witness.
        return established_at
    state = _json(
        witness_row[0], where="terminal recovery completion witness")
    proof = completion_proof(conn, processed)
    if proof is None:
        raise RuntimeError(
            "terminal recovery witness has no completed broker observation")
    seq, digest = proof
    expected = {
        "kind": "terminal-recovery-witness/v3",
        "broker": broker_name,
        "account_id": account_id,
        "processed_through": processed.isoformat(),
        "observation_seq": seq,
        "completion_sha256": digest,
    }
    if state != expected:
        raise RuntimeError(
            "terminal recovery watermark/completion witness disagree")
    return processed

def strict_floor(conn) -> datetime:
    return strict_checkpoint(conn) - journal.TERMINAL_RECOVERY_OVERLAP

def strict_advance(conn, through: datetime) -> datetime:
    candidate = journal._aware_utc(
        through, "terminal recovery upper boundary")
    current = strict_checkpoint(conn)
    processed = max(current, candidate)
    broker_name, account_id, _ = journal._terminal_recovery_binding(conn)
    proof = completion_proof(conn, processed)
    if proof is None:
        raise RuntimeError(
            "terminal recovery cannot advance: every Sentinel order in "
            "the exact COMPLETE observation is not yet durably reconciled")
    seq, digest = proof
    state = {
        "kind": "terminal-recovery-witness/v3",
        "broker": broker_name,
        "account_id": account_id,
        "processed_through": processed.isoformat(),
        "observation_seq": seq,
        "completion_sha256": digest,
    }
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sentinel_terminal_recovery_watermark"
            " (id,broker,broker_account_id,processed_through)"
            " VALUES (1,%s,%s,%s)"
            " ON CONFLICT (id) DO UPDATE SET"
            " broker=EXCLUDED.broker,broker_account_id=EXCLUDED.broker_account_id,"
            " processed_through=EXCLUDED.processed_through,updated_at=NOW()",
            (broker_name, account_id, processed),
        )
        cur.execute(
            "INSERT INTO sentinel_processed_sessions"
            " (cursor_name,session,state) VALUES (%s,%s,%s::jsonb)"
            " ON CONFLICT (cursor_name) DO UPDATE SET"
            " session=EXCLUDED.session,state=EXCLUDED.state,updated_at=NOW()",
            (witness_name(broker_name, account_id),
             processed.date().isoformat(),
             json.dumps(state, sort_keys=True)),
        )
    conn.commit()
    return processed

def execution_increase_fence_reason(*, conn, deployment, today) -> str:
    """Return the first Alpaca increase fence in certified execution order."""
    if deployment.broker != "alpaca":
        return ""
    return (
        _base_restore_increase_fence_reason(conn, deployment, today)
        or upgrade_restore_reason(conn)
        or postmaster_day_order_fence_reason(conn, today)
    )


def restore_increase_fence_reason(conn, deployment, today) -> str:
    """Operator diagnostic preserving the prior public precedence."""
    return (
        postmaster_day_order_fence_reason(conn, today)
        or upgrade_restore_reason(conn)
        or _base_restore_increase_fence_reason(conn, deployment, today)
    )

__all__ = [
    "AccountBoundObservation",
    "ActivityCorrectionRequiresRecovery",
    "AlpacaExecutionBroker",
    "FinancialGradeAlpacaExecutionBroker",
    "NativeBrokerFill",
    "RestoreGradeIncreaseDeferred",
    "database_incarnation",
    "execution_increase_fence_reason",
    "postmaster_day_order_fence_reason",
    "restore_increase_fence_reason",
    "strict_advance",
    "strict_checkpoint",
    "strict_floor",
]
