"""Offline execution accounting candidate; no broker transport or authority.

Native wire bytes and explicit local interpretations are separate commitments.
The existing gross-trade ledger owns fill correction/bust arithmetic. This
module does not supply strategy holdings, settled cash or production balances.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal
from enum import Enum
from fractions import Fraction
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from sentinel.execution import trade_rebooking
from sentinel.execution.native_activity import (
    NativeActivityEvidence, decode_canonical_json,
    normalize_activity, validate_evidence,
)
from sentinel.execution.native_readonly import ExecutionSubject
from sentinel.execution.numeric import exact_decimal


MAX_ENTRIES = 10_000
MAX_BYTES = 8 * 1024 * 1024
MAX_ENTRY_BYTES = 64 * 1024
MAX_LEGS = 64
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,256}\Z")
_ULID = re.compile(r"[0-7][0-9A-HJKMNP-TV-Z]{25}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_SCHEMA = "sentinel.candidate-account-events/1"


class AccountEventRefused(ValueError):
    pass


class EntryKind(str, Enum):
    TRADE = "TRADE"
    CASH = "CASH"
    CORPORATE_ACTION = "CORPORATE_ACTION"


class Operation(str, Enum):
    POST = "POST"
    CORRECTION = "CORRECTION"
    BUST = "BUST"


class CashKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    DIVIDEND = "DIVIDEND"
    FEE = "FEE"
    WITHHOLDING = "WITHHOLDING"
    INTEREST = "INTEREST"
    MERGER_CASH = "MERGER_CASH"
    CASH_IN_LIEU = "CASH_IN_LIEU"


class ActionKind(str, Enum):
    STOCK_DIVIDEND = "STOCK_DIVIDEND"
    SPLIT = "SPLIT"
    SPINOFF = "SPINOFF"
    STOCK_MERGER = "STOCK_MERGER"
    MIXED_MERGER = "MIXED_MERGER"
    CASH_IN_LIEU = "CASH_IN_LIEU"


class _Record(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


def _identifier(value: str) -> None:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise AccountEventRefused("bounded native identity required")


def _uuid(value: str) -> None:
    try:
        if not isinstance(value, str) or str(UUID(value)) != value:
            raise ValueError
    except (ValueError, AttributeError, TypeError) as exc:
        raise AccountEventRefused("canonical native UUID required") from exc


def _decimal(value: Decimal, *, nonzero: bool = True) -> None:
    if (not isinstance(value, Decimal) or not value.is_finite()
            or (nonzero and value == 0)
            or len(value.as_tuple().digits) > 64
            or abs(value.as_tuple().exponent) > 64
            or (value and abs(value.adjusted()) > 30)):
        raise AccountEventRefused("bounded exact Decimal required")


def _native_json(value: str):
    if not isinstance(value, str) or len(value.encode()) > MAX_ENTRY_BYTES:
        raise AccountEventRefused("native evidence byte limit")
    try:
        return decode_canonical_json(value)
    except (ValueError, RecursionError) as exc:
        raise AccountEventRefused("invalid bounded native evidence") from exc


class CashLeg(_Record):
    native_id: str
    kind: CashKind
    net_amount: Decimal
    evidence: NativeActivityEvidence
    related_trade_activity_id: str | None = None

    @model_validator(mode="after")
    def exact_cash(self):
        _identifier(self.native_id)
        _decimal(self.net_amount)
        if self.related_trade_activity_id is not None:
            _uuid(self.related_trade_activity_id)
            if self.kind not in {CashKind.FEE, CashKind.WITHHOLDING}:
                raise AccountEventRefused("only separate fees/withholding link a trade")
        positive = {CashKind.DEPOSIT, CashKind.DIVIDEND,
                    CashKind.MERGER_CASH, CashKind.CASH_IN_LIEU}
        negative = {CashKind.WITHDRAWAL, CashKind.FEE, CashKind.WITHHOLDING}
        if ((self.kind in positive and self.net_amount <= 0)
                or (self.kind in negative and self.net_amount >= 0)):
            raise AccountEventRefused("cash classification sign mismatch")
        return self


class SecurityLeg(_Record):
    native_id: str
    asset_id: str
    quantity: Decimal
    evidence: NativeActivityEvidence

    @model_validator(mode="after")
    def exact_security(self):
        _identifier(self.native_id)
        _uuid(self.asset_id)
        _decimal(self.quantity)
        return self


class AccountEntry(_Record):
    interpretation: Literal["LOCAL_ACCOUNT_CANDIDATE_V1"] = "LOCAL_ACCOUNT_CANDIDATE_V1"
    subject: ExecutionSubject
    entry_id: str
    publication_id: str
    kind: EntryKind
    operation: Operation = Operation.POST
    previous_entry_id: str | None = None
    native_evidence_json: str
    trade: trade_rebooking.TradeEvent | None = None
    cash_kind: CashKind | None = None
    cash_legs: tuple[CashLeg, ...] = ()
    security_legs: tuple[SecurityLeg, ...] = ()
    expected_leg_ids: tuple[str, ...] = ()
    action_kind: ActionKind | None = None
    action_id: str | None = None
    source_asset_id: str | None = None
    split_before: Decimal | None = None
    split_after: Decimal | None = None

    @model_validator(mode="after")
    def entry_shape(self):
        _identifier(self.entry_id)
        if not _ULID.fullmatch(self.publication_id):
            raise AccountEventRefused("publication ULID required")
        _native_json(self.native_evidence_json)
        if self.previous_entry_id is not None:
            _identifier(self.previous_entry_id)
            if self.previous_entry_id == self.entry_id:
                raise AccountEventRefused("entry cannot replace itself")
        if (self.operation is Operation.POST) != (self.previous_entry_id is None):
            raise AccountEventRefused("revision requires exactly one predecessor")
        if self.kind is EntryKind.TRADE:
            if (self.trade is None or self.operation is not Operation.POST
                    or self.trade.account_id != self.subject.account_id
                    or self.entry_id != self.trade.activity_id
                    or self.publication_id != self.trade.event_id
                    or self.native_evidence_json != self.trade.native_evidence_json
                    or self.cash_kind is not None or self.cash_legs
                    or self.security_legs or self.expected_leg_ids
                    or any(value is not None for value in (
                        self.action_kind, self.action_id, self.source_asset_id,
                        self.split_before, self.split_after))):
                raise AccountEventRefused("trade principal belongs only to gross trade replay")
            return self
        if self.trade is not None:
            raise AccountEventRefused("nontrade entry cannot contain a fill")
        if self.kind is EntryKind.CASH:
            if (self.cash_kind is None or self.security_legs
                    or any(value is not None for value in (
                        self.action_kind, self.action_id, self.source_asset_id,
                        self.split_before, self.split_after))):
                raise AccountEventRefused("cash entry shape mismatch")
        else:
            if (self.cash_kind is not None or self.action_kind is None
                    or self.action_id is None or self.source_asset_id is None):
                raise AccountEventRefused("corporate action identity required")
            _uuid(self.action_id)
            _uuid(self.source_asset_id)
        if self.operation is Operation.BUST:
            if self.cash_legs or self.security_legs or self.expected_leg_ids:
                raise AccountEventRefused("bust cannot invent replacement legs")
            if self.split_before is not None or self.split_after is not None:
                raise AccountEventRefused("bust cannot invent split terms")
            return self
        _complete_legs(self)
        if self.kind is EntryKind.CASH:
            if (len(self.cash_legs) != 1 or self.cash_legs[0].kind is not self.cash_kind
                    or self.cash_legs[0].native_id != self.entry_id):
                raise AccountEventRefused("cash entry must retain its single native activity")
        else:
            _action_shape(self)
        return self


def _complete_legs(entry: AccountEntry) -> None:
    ids = tuple(leg.native_id for leg in (*entry.cash_legs, *entry.security_legs))
    if (not ids or len(ids) > MAX_LEGS or len(entry.expected_leg_ids) > MAX_LEGS
            or len(set(ids)) != len(ids)
            or len(set(entry.expected_leg_ids)) != len(entry.expected_leg_ids)
            or set(ids) != set(entry.expected_leg_ids)):
        raise AccountEventRefused("complete unique corporate/cash leg manifest required")
    for value in entry.expected_leg_ids:
        _identifier(value)


def _action_shape(entry: AccountEntry) -> None:
    legs, cash, source = entry.security_legs, entry.cash_legs, entry.source_asset_id
    removed = [leg for leg in legs if leg.quantity < 0]
    received = [leg for leg in legs if leg.quantity > 0]
    principal_cash = [leg for leg in cash if leg.kind in {
        CashKind.MERGER_CASH, CashKind.CASH_IN_LIEU}]
    if any(leg.kind not in {CashKind.MERGER_CASH, CashKind.CASH_IN_LIEU,
                           CashKind.FEE, CashKind.WITHHOLDING} for leg in cash):
        raise AccountEventRefused("corporate cash classification mismatch")
    if entry.action_kind is ActionKind.STOCK_DIVIDEND:
        valid = bool(received) and not removed and all(
            leg.asset_id == source for leg in received) and all(
                leg.kind is CashKind.CASH_IN_LIEU for leg in cash)
    elif entry.action_kind is ActionKind.SPINOFF:
        valid = bool(received) and not removed and all(
            leg.asset_id != source for leg in received) and all(
                leg.kind is CashKind.CASH_IN_LIEU for leg in cash)
    elif entry.action_kind in {ActionKind.STOCK_MERGER, ActionKind.MIXED_MERGER}:
        valid = (bool(removed) and bool(received)
            and all(leg.asset_id == source for leg in removed)
            and all(leg.asset_id != source for leg in received))
        if entry.action_kind is ActionKind.MIXED_MERGER:
            valid = valid and any(leg.kind is CashKind.MERGER_CASH for leg in principal_cash)
        else:
            valid = valid and all(leg.kind is CashKind.CASH_IN_LIEU for leg in principal_cash)
    elif entry.action_kind is ActionKind.CASH_IN_LIEU:
        valid = (bool(principal_cash) and all(leg.kind is CashKind.CASH_IN_LIEU
            for leg in principal_cash) and not received
            and all(leg.asset_id == source and abs(leg.quantity) < 1 for leg in removed))
    else:
        valid = bool(legs) and all(leg.asset_id == source for leg in legs) and all(
            leg.kind is CashKind.CASH_IN_LIEU for leg in cash)
    if not valid:
        raise AccountEventRefused("corporate action leg shape mismatch")
    if entry.action_kind is ActionKind.SPLIT:
        _decimal(entry.split_before)
        _decimal(entry.split_after)
        if (entry.split_before <= 0 or entry.split_after <= 0
                or sum((Fraction(leg.quantity) for leg in legs), Fraction(0))
                != Fraction(entry.split_after) - Fraction(entry.split_before)):
            raise AccountEventRefused("split before/after/net share terms mismatch")
    elif entry.split_before is not None or entry.split_after is not None:
        raise AccountEventRefused("non-split entry cannot supply split terms")


class CandidatePosition(_Record):
    asset_id: str
    quantity: Decimal
    action_origins: tuple[str, ...]
    disposition: Literal["RESTRICTED_PENDING_POLICY", "TRADE_HISTORY_ONLY"]


class AccountProjection(_Record):
    subject: ExecutionSubject
    unique_entries: int
    replayed_entries: int
    positions: tuple[CandidatePosition, ...]
    explained_cash_delta: Decimal
    gross_trade_cash_delta: Decimal
    nontrade_cash_delta: Decimal
    active_entry_ids: tuple[str, ...]
    ledger_sha256: str
    spendable_cash: Literal[Decimal("0")] = Decimal("0")
    order_authority: Literal["NONE"] = "NONE"
    provider_finality_proven: Literal[False] = False
    settlement_proven: Literal[False] = False
    live_authority_granted: Literal[False] = False
    strategy_inputs_supplied: Literal[False] = False
    corporate_action_entitlements_proven: Literal[False] = False


def _entry_json(entry: AccountEntry) -> str:
    return entry.model_dump_json()


def _validated(entry: AccountEntry) -> AccountEntry:
    if not isinstance(entry, AccountEntry):
        raise AccountEventRefused("typed account entry required")
    # Revalidate every nested frozen copy, including the existing subject and
    # gross-trade models. model_copy/model_construct confer no validation.
    try:
        encoded = _entry_json(entry)
        if len(encoded.encode()) > MAX_ENTRY_BYTES:
            raise AccountEventRefused("account entry byte limit")
        result = AccountEntry.model_validate_json(encoded)
    except (ValueError, TypeError, RecursionError) as exc:
        raise AccountEventRefused("invalid typed account entry") from exc
    if len(_entry_json(result).encode()) > MAX_ENTRY_BYTES:
        raise AccountEventRefused("account entry byte limit")
    return result


def _evidence(entry: AccountEntry, subject: ExecutionSubject) -> None:
    payload = _native_json(entry.native_evidence_json)
    if isinstance(payload, dict) and payload.get("account_id", subject.account_id) != subject.account_id:
        raise AccountEventRefused("cross-account native entry")
    for leg in (*entry.cash_legs, *entry.security_legs):
        validate_evidence(leg.evidence, subject_sha256=subject.sha256)
        if leg.evidence.native_id != leg.native_id:
            raise AccountEventRefused("native leg identity/evidence mismatch")
        raw = _native_json(leg.evidence.payload_json)
        if not isinstance(raw, dict) or raw.get("account_id", subject.account_id) != subject.account_id:
            raise AccountEventRefused("cross-account native leg")
        if str(raw.get("activity_type", "")).upper() in {"FILL", "TRD"}:
            raise AccountEventRefused("fill principal cannot be a second account leg")
        if isinstance(leg, CashLeg):
            if entry.kind is EntryKind.CASH or raw.get("activity_type") in _RETAIL_CASH:
                _require_ordinary_cash(leg, raw, subject)
            if entry.kind is EntryKind.CASH and entry.native_evidence_json != leg.evidence.payload_json:
                raise AccountEventRefused("cash entry native evidence differs from its leg")


def _require_ordinary_cash(leg: CashLeg, raw: dict, subject: ExecutionSubject) -> None:
    result = normalize_activity(raw, subject_sha256=subject.sha256, account_id=subject.account_id)
    if (result.disposition != "ACCEPTED" or result.cash is None
            or _RETAIL_CASH.get(result.cash.activity_type) is not leg.kind
            or result.cash.activity_id != leg.native_id
            or result.cash.net_amount != leg.net_amount):
        raise AccountEventRefused("ordinary cash interpretation contradicts native evidence")


def _same_lineage(entry: AccountEntry, prior: AccountEntry) -> None:
    keys = ("kind", "cash_kind", "action_kind", "action_id", "source_asset_id")
    if any(getattr(entry, key) != getattr(prior, key) for key in keys):
        raise AccountEventRefused("predecessor accounting identity changed")
    if entry.operation is not Operation.BUST:
        if {leg.asset_id for leg in entry.security_legs} != {leg.asset_id for leg in prior.security_legs}:
            raise AccountEventRefused("predecessor securities identity changed")
        if (entry.kind is EntryKind.CASH and entry.cash_legs[0].related_trade_activity_id
                != prior.cash_legs[0].related_trade_activity_id):
            raise AccountEventRefused("predecessor linked trade changed")


def _contribution(entry: AccountEntry):
    positions: dict[str, Fraction] = {}
    for leg in entry.security_legs:
        positions[leg.asset_id] = positions.get(leg.asset_id, Fraction(0)) + Fraction(leg.quantity)
    return positions, sum((Fraction(leg.net_amount) for leg in entry.cash_legs), Fraction(0))


def _apply(positions: dict[str, Fraction], deltas: dict[str, Fraction], factor: int) -> None:
    for asset, quantity in deltas.items():
        positions[asset] = positions.get(asset, Fraction(0)) + factor * quantity


def _nonnegative(positions: dict[str, Fraction], cash: Fraction) -> None:
    if cash < 0 or any(quantity < 0 for quantity in positions.values()):
        raise AccountEventRefused("negative explained cash or inventory; history incomplete or contradictory")


def _require_subject(entry: AccountEntry, subject: ExecutionSubject) -> None:
    if entry.subject != subject:
        raise AccountEventRefused("cross-subject account entry")


def _require_unbooked(native_ids: set[str], owners: dict[str, str]) -> None:
    if any(identity in owners for identity in native_ids):
        raise AccountEventRefused("native activity booked in another entry")


def _action_assets(entry: AccountEntry) -> set[str]:
    return {entry.source_asset_id, *(leg.asset_id for leg in entry.security_legs)}


def _require_action_chain(entry: AccountEntry, heads: dict[str, str | None]) -> None:
    if entry.operation is Operation.POST:
        if entry.action_id in heads:
            raise AccountEventRefused("corporate action already owns an entry chain")
    elif heads.get(entry.action_id) != entry.previous_entry_id:
        raise AccountEventRefused("corporate action revision must name its active head")


def _require_no_dependent_actions(prior: AccountEntry, barriers: dict[str, str]) -> None:
    assets = ({prior.trade.asset_id} if prior.kind is EntryKind.TRADE else _action_assets(prior))
    if any(barriers.get(asset, "") > prior.publication_id for asset in assets):
        raise AccountEventRefused("revision crosses a dependent corporate action; authoritative rebasing required")


def replay(entries: tuple[AccountEntry, ...], *, subject: ExecutionSubject) -> AccountProjection:
    """Replay a complete supplied history; never infer unexplained balances."""
    if not isinstance(subject, ExecutionSubject):
        raise AccountEventRefused("typed execution subject required")
    subject = ExecutionSubject.model_validate_json(subject.model_dump_json())
    if not isinstance(entries, tuple) or len(entries) > MAX_ENTRIES:
        raise AccountEventRefused("bounded entry tuple required")
    seen, publications, native_owners, active, positions = {}, {}, {}, {}, {}
    action_heads, action_barriers = {}, {}
    trades, trade_ids = [], set()
    trade_projection = trade_rebooking.replay((), account_id=subject.account_id)
    cash, gross, nontrade, replayed, byte_count = Fraction(0), Fraction(0), Fraction(0), 0, 0
    last_publication = None
    for supplied in entries:
        entry = _validated(supplied)
        _require_subject(entry, subject)
        _evidence(entry, subject)
        encoded = _entry_json(entry)
        byte_count += len(encoded.encode())
        if byte_count > MAX_BYTES:
            raise AccountEventRefused("account ledger byte limit")
        if entry.entry_id in seen:
            if seen[entry.entry_id] != encoded:
                raise AccountEventRefused("account entry identity changed")
            replayed += 1
            continue
        if entry.publication_id in publications:
            raise AccountEventRefused("publication identity reused")
        if last_publication is not None and entry.publication_id <= last_publication:
            raise AccountEventRefused("publication order regressed")
        native_ids = {entry.entry_id, *entry.expected_leg_ids}
        _require_unbooked(native_ids, native_owners)
        if entry.kind is EntryKind.TRADE:
            if entry.trade.kind is not trade_rebooking.TradeKind.FILL:
                prior = active.get(entry.trade.previous_activity_id)
                if prior is not None:
                    _require_no_dependent_actions(prior, action_barriers)
            before = trade_projection
            trades.append(entry.trade)
            after = trade_rebooking.replay(tuple(trades), account_id=subject.account_id)
            trade_projection = after
            _apply(positions, {item.asset_id: Fraction(item.quantity) for item in before.position_deltas}, -1)
            _apply(positions, {item.asset_id: Fraction(item.quantity) for item in after.position_deltas}, 1)
            delta = Fraction(after.gross_trade_cash_delta) - Fraction(before.gross_trade_cash_delta)
            cash += delta
            gross += delta
            trade_ids.add(entry.trade.activity_id)
            if entry.trade.kind is not trade_rebooking.TradeKind.FILL:
                del active[entry.trade.previous_activity_id]
            if entry.trade.kind is not trade_rebooking.TradeKind.BUST:
                active[entry.entry_id] = entry
        else:
            if entry.kind is EntryKind.CORPORATE_ACTION and entry.operation is Operation.POST:
                _require_action_chain(entry, action_heads)
            for leg in entry.cash_legs:
                if leg.related_trade_activity_id is not None and leg.related_trade_activity_id not in trade_ids:
                    raise AccountEventRefused("linked trade activity missing")
            if entry.operation is not Operation.POST:
                prior = active.get(entry.previous_entry_id)
                if prior is None:
                    raise AccountEventRefused("missing or inactive accounting predecessor")
                _same_lineage(entry, prior)
                if entry.kind is EntryKind.CORPORATE_ACTION:
                    _require_action_chain(entry, action_heads)
                    _require_no_dependent_actions(prior, action_barriers)
                old_positions, old_cash = _contribution(prior)
                _apply(positions, old_positions, -1)
                cash -= old_cash
                nontrade -= old_cash
                del active[prior.entry_id]
            if entry.operation is not Operation.BUST:
                if (entry.action_kind is ActionKind.SPLIT
                        and positions.get(entry.source_asset_id, Fraction(0)) != Fraction(entry.split_before)):
                    raise AccountEventRefused("split opening inventory mismatch")
                new_positions, new_cash = _contribution(entry)
                _apply(positions, new_positions, 1)
                cash += new_cash
                nontrade += new_cash
                active[entry.entry_id] = entry
            if entry.kind is EntryKind.CORPORATE_ACTION:
                action_heads[entry.action_id] = None if entry.operation is Operation.BUST else entry.entry_id
                assets = _action_assets(prior) if entry.operation is Operation.BUST else _action_assets(entry)
                action_barriers.update({asset: entry.publication_id for asset in assets})
        # Reversal and replacement/group application is atomic. No transient
        # predecessor reversal is interpreted as a short position or cash loan.
        _nonnegative(positions, cash)
        seen[entry.entry_id] = encoded
        publications[entry.publication_id] = entry.entry_id
        native_owners.update({identity: entry.entry_id for identity in native_ids})
        last_publication = entry.publication_id
    origins: dict[str, set[str]] = {}
    for entry in active.values():
        if entry.kind is EntryKind.CORPORATE_ACTION:
            for leg in entry.security_legs:
                origins.setdefault(leg.asset_id, set()).add(entry.action_id)
    rendered = tuple(CandidatePosition(asset_id=asset, quantity=exact_decimal(quantity),
        action_origins=tuple(sorted(origins.get(asset, ()))),
        disposition="RESTRICTED_PENDING_POLICY" if origins.get(asset) else "TRADE_HISTORY_ONLY")
        for asset, quantity in sorted(positions.items()) if quantity)
    digest = hashlib.sha256(json.dumps({"subject": subject.to_dict(),
        "entries": list(seen.values())}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return AccountProjection(subject=subject, unique_entries=len(seen), replayed_entries=replayed,
        positions=rendered, explained_cash_delta=exact_decimal(cash),
        gross_trade_cash_delta=exact_decimal(gross), nontrade_cash_delta=exact_decimal(nontrade),
        active_entry_ids=tuple(sorted(active)), ledger_sha256=digest)


class SealedAccountLedger(_Record):
    envelope_json: str
    sha256: str


def seal(entries: tuple[AccountEntry, ...], *, subject: ExecutionSubject) -> SealedAccountLedger:
    replay(entries, subject=subject)
    rows = [_entry_json(_validated(entry)) for entry in entries]
    encoded = json.dumps({"schema": _SCHEMA, "subject": subject.to_dict(), "entries": rows,
        "entry_sha256": [hashlib.sha256(row.encode()).hexdigest() for row in rows]},
        sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode()) > MAX_BYTES:
        raise AccountEventRefused("account envelope byte limit")
    return SealedAccountLedger(envelope_json=encoded,
        sha256=hashlib.sha256(encoded.encode()).hexdigest())


def recover(encoded: str, *, expected_sha256: str, subject: ExecutionSubject) -> AccountProjection:
    """Verify original byte identity and recompute; a hash is not authentication."""
    if (not isinstance(encoded, str) or len(encoded.encode()) > MAX_BYTES
            or not isinstance(expected_sha256, str) or not _HASH.fullmatch(expected_sha256)
            or hashlib.sha256(encoded.encode()).hexdigest() != expected_sha256):
        raise AccountEventRefused("original account envelope byte identity mismatch")
    try:
        payload = json.loads(encoded)
        if json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False) != encoded:
            raise AccountEventRefused("noncanonical account envelope")
        if (not isinstance(payload, dict) or set(payload) != {
                "schema", "subject", "entries", "entry_sha256"}
                or payload["schema"] != _SCHEMA
                or payload["subject"] != subject.to_dict()):
            raise AccountEventRefused("account envelope subject/schema mismatch")
        rows, hashes = payload["entries"], payload["entry_sha256"]
        if (not isinstance(rows, list) or not isinstance(hashes, list)
                or len(rows) != len(hashes) or len(rows) > MAX_ENTRIES):
            raise AccountEventRefused("invalid bounded account envelope")
        entries = []
        for row, digest in zip(rows, hashes):
            if (not isinstance(row, str) or len(row.encode()) > MAX_ENTRY_BYTES
                    or not isinstance(digest, str)
                    or hashlib.sha256(row.encode()).hexdigest() != digest):
                raise AccountEventRefused("original account entry byte identity mismatch")
            entry = AccountEntry.model_validate_json(row)
            if _entry_json(entry) != row:
                raise AccountEventRefused("noncanonical account entry")
            entries.append(entry)
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        raise AccountEventRefused("invalid account envelope") from exc
    return replay(tuple(entries), subject=subject)


_RETAIL_CASH = {
    "CSD": CashKind.DEPOSIT, "CSW": CashKind.WITHDRAWAL,
    "DIV": CashKind.DIVIDEND, "CGD": CashKind.DIVIDEND,
    "FEE": CashKind.FEE, "CFEE": CashKind.FEE, "DIVFEE": CashKind.FEE,
    "DIVNRA": CashKind.WITHHOLDING, "DIVTW": CashKind.WITHHOLDING,
    "INTNRA": CashKind.WITHHOLDING, "INTTW": CashKind.WITHHOLDING,
    "WH": CashKind.WITHHOLDING, "INT": CashKind.INTEREST,
}


def cash_entry_from_native(payload: dict, *, subject: ExecutionSubject,
                           publication_id: str) -> AccountEntry:
    """Reuse current normalizer for its narrow ordinary-cash subset only.

    Publication ULID is an explicit supplied interpretation; the retail payload
    does not prove one, settlement, completeness or live authority. Ambiguous
    journals/transfers and all security/revision events retain their refusals.
    """
    result = normalize_activity(payload, subject_sha256=subject.sha256,
                                account_id=subject.account_id)
    if result.disposition != "ACCEPTED" or result.cash is None:
        raise AccountEventRefused("native cash normalization refused")
    kind = _RETAIL_CASH.get(result.cash.activity_type)
    if kind is None:
        raise AccountEventRefused("native cash classification requires separate interpretation")
    leg = CashLeg(native_id=result.cash.activity_id, kind=kind,
                  net_amount=result.cash.net_amount, evidence=result.evidence)
    return AccountEntry(subject=subject, entry_id=leg.native_id,
        publication_id=publication_id, kind=EntryKind.CASH, cash_kind=kind,
        native_evidence_json=result.evidence.payload_json,
        cash_legs=(leg,), expected_leg_ids=(leg.native_id,))
