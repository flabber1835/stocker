"""Broker-free candidate gross trade accounting; never execution authority.

Events are explicit local interpretations, not an accepted native wire parser.
The original wire evidence is retained independently. Production fill journals,
cash availability, broker capabilities and correction refusals do not use this
module. Fees, settlement and corporate actions are outside this subledger.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from fractions import Fraction
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from sentinel.execution.contract import Side
from sentinel.execution.native_activity import canonical_json, decode_canonical_json
from sentinel.execution.numeric import exact_decimal


MAX_EVENTS = 10_000
MAX_EVENT_BYTES = 64 * 1024
MAX_ENVELOPE_BYTES = 8 * 1024 * 1024
_SCHEMA = "sentinel.candidate-gross-trade-ledger/1"
_ULID = re.compile(r"[0-7][0-9A-HJKMNP-TV-Z]{25}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")


class TradeRebookingRefused(ValueError):
    pass


def _decode(encoded: str):
    """Keep malformed/deep caller evidence inside the candidate refusal API."""
    try:
        return decode_canonical_json(encoded)
    except (ValueError, RecursionError) as exc:
        raise TradeRebookingRefused(
            "invalid or excessively nested canonical evidence") from exc


class TradeKind(str, Enum):
    FILL = "FILL"
    CORRECTION = "CORRECTION"
    BUST = "BUST"


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


def _uuid(value: str) -> str:
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, TypeError, AttributeError) as exc:
        raise TradeRebookingRefused("canonical native UUID required") from exc
    return value


def _decimal(value: Decimal) -> None:
    if (not isinstance(value, Decimal) or not value.is_finite() or value <= 0
            or len(value.as_tuple().digits) > 64
            or abs(value.as_tuple().exponent) > 64
            or abs(value.adjusted()) > 30):
        raise TradeRebookingRefused("bounded positive Decimal required")


class TradeEvent(_Record):
    """An interpreted operation with immutable, separately retained evidence.

    BUST has no replacement quantity/price. A caller must interpret any native
    bust payload separately; this model makes no claim about its wire fields.
    Event IDs order publication, not execution time. Deltas may be negative;
    they are not account balances or permission to sell short.
    """

    interpretation: Literal["LOCAL_CANDIDATE_V1"] = "LOCAL_CANDIDATE_V1"
    account_id: str
    event_id: str
    activity_id: str
    broker_order_id: str
    asset_id: str
    side: Side
    kind: TradeKind
    executed_at: datetime
    native_evidence_json: str
    previous_activity_id: str | None = None
    quantity: Decimal | None = None
    price: Decimal | None = None

    @model_validator(mode="after")
    def validate_event(self):
        for value in (self.account_id, self.activity_id,
                      self.broker_order_id, self.asset_id):
            _uuid(value)
        if not _ULID.fullmatch(self.event_id):
            raise TradeRebookingRefused("native publication ULID required")
        if (self.executed_at.tzinfo is None
                or self.executed_at.utcoffset() is None):
            raise TradeRebookingRefused("aware execution time required")
        object.__setattr__(self, "executed_at", self.executed_at.astimezone(timezone.utc))
        if self.previous_activity_id is not None:
            _uuid(self.previous_activity_id)
            if self.previous_activity_id == self.activity_id:
                raise TradeRebookingRefused("activity cannot replace itself")
        if (self.kind is TradeKind.FILL) != (self.previous_activity_id is None):
            raise TradeRebookingRefused("correction/bust requires exactly one predecessor")
        if self.kind is TradeKind.BUST:
            if self.quantity is not None or self.price is not None:
                raise TradeRebookingRefused("bust cannot invent replacement economics")
        else:
            _decimal(self.quantity)
            _decimal(self.price)
        if len(self.native_evidence_json.encode("utf-8")) > MAX_EVENT_BYTES:
            raise TradeRebookingRefused("native evidence byte limit")
        _decode(self.native_evidence_json)
        return self


class PositionDelta(_Record):
    asset_id: str
    quantity: Decimal


class TradeProjection(_Record):
    account_id: str
    unique_events: int
    replayed_events: int
    active_activity_ids: tuple[str, ...]
    position_deltas: tuple[PositionDelta, ...]
    gross_trade_cash_delta: Decimal
    ledger_sha256: str
    provider_finality_proven: Literal[False] = False
    settlement_proven: Literal[False] = False
    live_authority_granted: Literal[False] = False


class SealedTradeLedger(_Record):
    """Integrity evidence only. A hash does not authenticate a broker source."""

    envelope_json: str
    sha256: str


def _event_json(event: TradeEvent) -> str:
    payload = event.model_dump()
    payload.update(side=event.side.value, kind=event.kind.value,
                   executed_at=event.executed_at.isoformat())
    return canonical_json(payload)


def _validated_event(event: TradeEvent) -> TradeEvent:
    if not isinstance(event, TradeEvent):
        raise TradeRebookingRefused("typed trade event required")
    # Frozen models can still be copied without validation. Revalidate at the
    # accounting boundary rather than trusting a caller's model instance.
    return TradeEvent.model_validate(event.model_dump())


def _require_account(event: TradeEvent, account_id: str) -> None:
    if event.account_id != account_id:
        raise TradeRebookingRefused("cross-account event")


def _require_same_trade(event: TradeEvent, prior: TradeEvent) -> None:
    if (event.broker_order_id, event.asset_id, event.side) != (
            prior.broker_order_id, prior.asset_id, prior.side):
        raise TradeRebookingRefused("predecessor order/asset/side changed")


def _legs(event: TradeEvent) -> tuple[Fraction, Fraction]:
    sign = 1 if event.side is Side.BUY else -1
    quantity = sign * Fraction(event.quantity)
    return quantity, -quantity * Fraction(event.price)


def replay(events: tuple[TradeEvent, ...], *, account_id: str) -> TradeProjection:
    """Replay a bounded publication-ordered sequence, including exact repeats."""
    _uuid(account_id)
    if not isinstance(events, tuple) or len(events) > MAX_EVENTS:
        raise TradeRebookingRefused("bounded event tuple required")
    seen, event_ids, active, positions = {}, {}, {}, {}
    cash, replayed, last_event_id, total_bytes = Fraction(0), 0, None, 0
    for supplied in events:
        event = _validated_event(supplied)
        _require_account(event, account_id)
        encoded = _event_json(event)
        total_bytes += len(encoded.encode("utf-8"))
        if total_bytes > MAX_ENVELOPE_BYTES:
            raise TradeRebookingRefused("trade ledger byte limit")
        previous = seen.get(event.activity_id)
        if previous is not None:
            if previous != encoded:
                raise TradeRebookingRefused("native activity identity changed")
            replayed += 1
            continue
        if event.event_id in event_ids:
            raise TradeRebookingRefused("native publication identity reused")
        if last_event_id is not None and event.event_id <= last_event_id:
            raise TradeRebookingRefused("publication order regressed")
        if event.kind is not TradeKind.FILL:
            prior = active.get(event.previous_activity_id)
            if prior is None:
                raise TradeRebookingRefused("missing or inactive predecessor")
            _require_same_trade(event, prior)
            quantity, gross_cash = _legs(prior)
            positions[prior.asset_id] -= quantity
            cash -= gross_cash
            del active[prior.activity_id]
        if event.kind is not TradeKind.BUST:
            quantity, gross_cash = _legs(event)
            positions[event.asset_id] = positions.get(event.asset_id, Fraction(0)) + quantity
            cash += gross_cash
            active[event.activity_id] = event
        seen[event.activity_id], event_ids[event.event_id] = encoded, event.activity_id
        last_event_id = event.event_id
    return TradeProjection(account_id=account_id, unique_events=len(seen),
        replayed_events=replayed, active_activity_ids=tuple(sorted(active)),
        position_deltas=tuple(PositionDelta(asset_id=asset, quantity=exact_decimal(quantity))
            for asset, quantity in sorted(positions.items()) if quantity),
        gross_trade_cash_delta=exact_decimal(cash),
        ledger_sha256=hashlib.sha256(canonical_json(list(seen.values())).encode()).hexdigest())


def seal(events: tuple[TradeEvent, ...], *, account_id: str) -> SealedTradeLedger:
    """Seal original interpreted event bytes; never serialize derived totals."""
    replay(events, account_id=account_id)
    encoded_events = [_event_json(_validated_event(event)) for event in events]
    encoded = canonical_json({"schema": _SCHEMA, "account_id": account_id,
        "events": encoded_events, "event_sha256": [hashlib.sha256(item.encode()).hexdigest()
            for item in encoded_events]})
    if len(encoded.encode("utf-8")) > MAX_ENVELOPE_BYTES:
        raise TradeRebookingRefused("trade envelope byte limit")
    return SealedTradeLedger(envelope_json=encoded,
        sha256=hashlib.sha256(encoded.encode()).hexdigest())


def recover(encoded: str, *, expected_sha256: str, account_id: str) -> TradeProjection:
    """Verify externally retained byte identity, decode, and recompute economics.

    The expected hash must come from the retained original envelope. It proves
    byte identity only, not provider completeness, authenticity or authority.
    """
    _uuid(account_id)
    if (not isinstance(encoded, str) or len(encoded.encode()) > MAX_ENVELOPE_BYTES
            or not isinstance(expected_sha256, str) or not _HASH.fullmatch(expected_sha256)
            or hashlib.sha256(encoded.encode()).hexdigest() != expected_sha256):
        raise TradeRebookingRefused("original envelope byte identity mismatch")
    payload = _decode(encoded)
    if (not isinstance(payload, dict)
            or set(payload) != {"schema", "account_id", "events", "event_sha256"}
            or payload["schema"] != _SCHEMA or payload["account_id"] != account_id):
        raise TradeRebookingRefused("trade envelope subject/schema mismatch")
    rows, hashes = payload["events"], payload["event_sha256"]
    if (not isinstance(rows, list) or not isinstance(hashes, list)
            or len(rows) != len(hashes) or len(rows) > MAX_EVENTS):
        raise TradeRebookingRefused("invalid bounded event envelope")
    events = []
    for row, digest in zip(rows, hashes):
        if (not isinstance(row, str) or not isinstance(digest, str)
                or hashlib.sha256(row.encode()).hexdigest() != digest):
            raise TradeRebookingRefused("original event byte identity mismatch")
        event = _decode(row)
        if not isinstance(event, dict):
            raise TradeRebookingRefused("invalid typed event envelope")
        try:
            event.update(side=Side(event["side"]), kind=TradeKind(event["kind"]),
                         executed_at=datetime.fromisoformat(event["executed_at"]))
            events.append(TradeEvent.model_validate(event))
        except (ValueError, TypeError, KeyError) as exc:
            raise TradeRebookingRefused("invalid typed event envelope") from exc
        if _event_json(events[-1]) != row:
            raise TradeRebookingRefused("noncanonical typed event envelope")
    return replay(tuple(events), account_id=account_id)
