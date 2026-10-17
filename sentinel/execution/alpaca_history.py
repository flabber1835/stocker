from __future__ import annotations

import hashlib
import math
import time
from datetime import datetime
from fractions import Fraction
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from sentinel.execution.broker_cash import BrokerCashActivity
from sentinel.execution.contract import BrokerAccountIdentity
from sentinel.execution.fill_integrity import (
    gross_matches_serialized_average, partial_gross_leaves_positive_notional,
)
from sentinel.execution.native_activity import (
    NativeActivityEvidence, NativeActivityRefused, NativeActivityResult, NativeFill,
    _decimal as native_decimal,
    activity_evidence, aware_time, canonical_json, decode_canonical_json,
    normalize_activity, validate_evidence,
)


class HistoryLimits(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)
    page_size: int = Field(default=100, ge=1, le=100)
    max_pages: int = Field(default=100, ge=1, le=1000)
    max_rows: int = Field(default=10000, ge=1, le=100000)
    max_bytes: int = Field(default=16 * 1024 * 1024, ge=1, le=64 * 1024 * 1024)
    max_seconds: float = Field(default=120.0, gt=0, le=600, allow_inf_nan=False)


class NativeReadEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    subject_sha256: str
    path: str
    params_json: str
    payload_sha256: str
    source_sha256: str


class NativeHistoryBatch(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)
    subject_sha256: str
    requested_after: datetime
    requested_through: datetime
    events: tuple[NativeActivityResult, ...]
    evidence: tuple[NativeActivityEvidence, ...]
    reads: tuple[NativeReadEvidence, ...]
    fills: tuple[NativeFill, ...]
    cash_activities: tuple[BrokerCashActivity, ...]
    quarantines: tuple[NativeActivityResult, ...]
    replayed_native_ids: tuple[str, ...]
    traversal_exhausted: bool
    termination: str
    projection_ready: bool
    provider_finality_proven: Literal[False] = False
    settlement_proven: Literal[False] = False
    restore_grade_recovery_proven: Literal[False] = False
    live_authority_granted: Literal[False] = False
    evidence_sha256: str


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


async def read_account_history(client, *, after: datetime, through: datetime,
                               limits: HistoryLimits | None = None,
                               prior_evidence: tuple[NativeActivityEvidence, ...] = (),
                               clock=time.monotonic) -> NativeHistoryBatch:
    limits = limits or HistoryLimits()
    if not isinstance(limits, HistoryLimits):
        raise NativeActivityRefused("INVALID_HISTORY_LIMITS")
    lower, upper = aware_time(after), aware_time(through)
    if lower > upper:
        raise NativeActivityRefused("INVALID_HISTORY_BOUNDS")
    subject = client.subject
    subject_hash = subject.sha256
    if not isinstance(prior_evidence, tuple) or len(prior_evidence) > limits.max_rows:
        raise NativeActivityRefused("INVALID_PRIOR_EVIDENCE_BOUND")
    prior_bytes = 0
    for item in prior_evidence:
        if not isinstance(item, NativeActivityEvidence):
            raise NativeActivityRefused("INVALID_PRIOR_EVIDENCE")
        prior_bytes += len(item.payload_json.encode())
        if prior_bytes > limits.max_bytes:
            raise NativeActivityRefused("PRIOR_EVIDENCE_BYTE_LIMIT")
        validate_evidence(item, subject_sha256=subject_hash)
    started = clock()
    if type(started) not in (int, float) or not math.isfinite(started):
        raise NativeActivityRefused("INVALID_HISTORY_CLOCK")
    last_clock = started
    reads: list[NativeReadEvidence] = []
    results: list[NativeActivityResult] = []
    evidence = list(prior_evidence)
    evidence_hashes = {item.source_sha256 for item in evidence}
    by_id: dict[str | None, list[NativeActivityEvidence]] = {}
    for item in evidence:
        by_id.setdefault(item.native_id, []).append(item)
    orders: dict[str, Any] = {}
    observed_ids: set[str] = set()
    token: str | None = None
    total_bytes = prior_bytes
    exhausted = False
    termination = "PAGE_LIMIT"
    native_account: str | None = None

    def check_time():
        nonlocal last_clock
        if client.subject.sha256 != subject_hash:
            raise NativeActivityRefused("SUBJECT_CHANGED_DURING_HISTORY")
        current = clock()
        if type(current) not in (int, float) or not math.isfinite(current):
            raise NativeActivityRefused("INVALID_HISTORY_CLOCK")
        if current < last_clock:
            raise NativeActivityRefused("HISTORY_CLOCK_REGRESSED")
        last_clock = current
        if current - started >= limits.max_seconds:
            raise NativeActivityRefused("HISTORY_DEADLINE")

    def record(path, params, payload):
        nonlocal total_bytes
        encoded = canonical_json(payload)
        total_bytes += len(encoded.encode())
        payload_hash = hashlib.sha256(encoded.encode()).hexdigest()
        binding = {"subject_sha256": subject_hash, "path": path,
                   "params_json": canonical_json(params), "payload_sha256": payload_hash}
        reads.append(NativeReadEvidence(**binding, source_sha256=_digest(binding)))
        if total_bytes > limits.max_bytes:
            raise NativeActivityRefused("HISTORY_BYTE_LIMIT")

    def account_native(identity):
        if (not isinstance(identity, BrokerAccountIdentity)
                or identity.broker != "alpaca" or identity.account_id != subject.account_id):
            raise NativeActivityRefused("CROSS_SUBJECT_ACCOUNT")
        try:
            native = str(UUID(identity.raw["id"]))
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise NativeActivityRefused("INVALID_NATIVE_ACCOUNT_ID") from exc
        if native != subject.account_id or identity.raw["id"] != native:
            raise NativeActivityRefused("CROSS_SUBJECT_NATIVE_ACCOUNT")
        return native

    def quarantine(payload, code):
        item = activity_evidence(payload, subject_sha256=subject_hash)
        result = NativeActivityResult(disposition="QUARANTINED", evidence=item, reason_code=code)
        results.append(result)
        if item.source_sha256 not in evidence_hashes:
            evidence.append(item)
            evidence_hashes.add(item.source_sha256)
            by_id.setdefault(item.native_id, []).append(item)

    async def normalize(payload, *, replaying=False):
        item = activity_evidence(payload, subject_sha256=subject_hash)
        previous = tuple(by_id.get(item.native_id, ()))
        order = None
        if isinstance(payload, dict) and payload.get("activity_type") == "FILL":
            raw_id = payload.get("order_id")
            try:
                order_id = str(UUID(raw_id))
            except (ValueError, TypeError, AttributeError):
                quarantine(payload, "INVALID_NATIVE_ORDER_ID")
                return
            if order_id not in orders:
                path = "/v2/orders/" + order_id
                check_time()
                try:
                    order = await client.get(path)
                except Exception:
                    quarantine(payload, "NATIVE_ORDER_READ_REFUSED")
                    raise
                check_time()
                record(path, {}, order)
                orders[order_id] = order
            order = orders[order_id]
        result = normalize_activity(payload, subject_sha256=subject_hash,
            account_id=native_account, order=order, prior_evidence=previous)
        if replaying and result.disposition == "ACCEPTED":
            result = result.model_copy(update={"disposition": "REPLAY"})
        results.append(result)
        item = result.evidence
        if item.source_sha256 not in evidence_hashes:
            evidence.append(item)
            evidence_hashes.add(item.source_sha256)
            by_id.setdefault(item.native_id, []).append(item)

    try:
        check_time()
        initial = await client.verify_account()
        native_account = account_native(initial)
        record("/v2/account", {}, initial.raw)
        for prior in prior_evidence:
            check_time()
            await normalize(decode_canonical_json(prior.payload_json), replaying=True)
        for _ in range(limits.max_pages):
            check_time()
            params = {"after": lower.isoformat(), "until": upper.isoformat(),
                      "direction": "asc", "page_size": limits.page_size}
            if token is not None:
                params["page_token"] = token
            page = await client.get("/v2/account/activities", params)
            check_time()
            record("/v2/account/activities", params, page)
            if not isinstance(page, list) or len(page) > limits.page_size:
                raise NativeActivityRefused("MALFORMED_ACTIVITY_PAGE")
            if not page:
                exhausted, termination = True, "EMPTY_PAGE"
                break
            if len(results) + len(page) > limits.max_rows:
                raise NativeActivityRefused("HISTORY_ROW_LIMIT")
            page_ids = []
            for payload in page:
                check_time()
                item = activity_evidence(payload, subject_sha256=subject_hash)
                if item.native_id is None:
                    quarantine(payload, "INVALID_NATIVE_ACTIVITY_ID")
                    continue
                page_ids.append(item.native_id)
                if isinstance(payload, dict) and payload.get("created_at") is not None:
                    try:
                        created = aware_time(payload["created_at"])
                    except NativeActivityRefused:
                        quarantine(payload, "INVALID_NATIVE_PUBLICATION_TIME")
                        continue
                    if not lower <= created <= upper:
                        quarantine(payload, "PUBLICATION_TIME_OUTSIDE_REQUEST")
                        continue
                await normalize(payload)
            if not page_ids or page_ids[-1] == token or any(item in observed_ids for item in page_ids):
                raise NativeActivityRefused("REPEATED_ACTIVITY_CURSOR")
            observed_ids.update(page_ids)
            if len(page_ids) != len(set(page_ids)):
                raise NativeActivityRefused("REPEATED_ACTIVITY_CURSOR")
            token = page_ids[-1]
            if len(page) < limits.page_size:
                exhausted, termination = True, "SHORT_PAGE"
                break
    except NativeActivityRefused as exc:
        termination = str(exc)
    except Exception:
        termination = "NATIVE_HISTORY_READ_REFUSED"
    finally:
        try:
            check_time()
            final = await client.verify_account()
            final_native = account_native(final)
            record("/v2/account", {}, final.raw)
            check_time()
            if native_account is None or final_native != native_account:
                raise NativeActivityRefused("ACCOUNT_CHANGED_DURING_HISTORY")
        except NativeActivityRefused as exc:
            termination, exhausted = str(exc), False
        except Exception:
            termination, exhausted = "FINAL_ACCOUNT_VERIFICATION_REFUSED", False
    unique_fills = {item.fill.activity_id: item for item in results if item.fill is not None}
    totals = {}
    for item in unique_fills.values():
        fill = item.fill
        quantity, gross = totals.get(fill.broker_order_id, (Fraction(0), Fraction(0)))
        totals[fill.broker_order_id] = (quantity + Fraction(fill.quantity), gross + Fraction(fill.quantity) * Fraction(fill.price))
    for order_id, (quantity, gross) in totals.items():
        order = orders[order_id]
        try:
            filled = Fraction(native_decimal(order["filled_qty"], positive=True))
            average = native_decimal(order["filled_avg_price"], positive=True)
            valid = (quantity <= filled and (
                gross_matches_serialized_average(filled, gross, average) if quantity == filled
                else partial_gross_leaves_positive_notional(filled, gross, average)))
        except (KeyError, TypeError, ValueError, ArithmeticError):
            valid = False
        if not valid:
            for item in unique_fills.values():
                if item.fill.broker_order_id == order_id:
                    quarantine(decode_canonical_json(item.evidence.payload_json), "FILL_ORDER_GROSS_MISMATCH")
    quarantines = tuple(item for item in results if item.disposition == "QUARANTINED")
    if exhausted:
        try:
            check_time()
        except NativeActivityRefused as exc:
            termination, exhausted = str(exc), False
        except Exception:
            termination, exhausted = "FINAL_HISTORY_CLOCK_REFUSED", False
    ready = exhausted and termination in {"EMPTY_PAGE", "SHORT_PAGE"} and not quarantines
    accepted = [item for item in results if item.disposition == "ACCEPTED"] if ready else []
    fills = tuple(item.fill for item in accepted if item.fill is not None)
    cash = tuple(item.cash for item in accepted if item.cash is not None)
    commitment = {"subject_sha256": subject_hash, "after": lower.isoformat(),
        "through": upper.isoformat(), "reads": [item.source_sha256 for item in reads],
        "events": [{"source": item.evidence.source_sha256, "disposition": item.disposition,
                    "reason_code": item.reason_code} for item in results],
        "evidence": [item.source_sha256 for item in evidence], "termination": termination,
        "traversal_exhausted": exhausted, "projection_ready": ready}
    return NativeHistoryBatch(subject_sha256=subject_hash, requested_after=lower,
        requested_through=upper, events=tuple(results), evidence=tuple(evidence), reads=tuple(reads),
        fills=fills, cash_activities=cash, quarantines=quarantines,
        replayed_native_ids=tuple(item.evidence.native_id for item in results if item.disposition == "REPLAY"),
        traversal_exhausted=exhausted, termination=termination, projection_ready=ready,
        evidence_sha256=_digest(commitment))
