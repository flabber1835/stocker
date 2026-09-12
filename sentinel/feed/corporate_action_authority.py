"""Point-in-time exceptional cash-action adjudication.

Sharadar remains the ordinary corporate-action source. This module handles only
explicitly flagged disputes where an independent final source has been reviewed
and committed as immutable evidence.
"""
from __future__ import annotations

import bisect
import datetime as dt
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping, Sequence

from sentinel.core.terminal import DIVIDEND_ACTIONS
from sentinel.feed import calendar
from stock_strategy_shared.wealth_core.sharadar_domains import AdjudicatedCashDistribution
from sentinel.feed.source_authority.corporate_action_data import (
    CASH_ADJUDICATION_AUTHORITIES,
    DISPUTED_CASH_EVENTS,
)

_SCHEMA = "sentinel.corporate-action-adjudication/2"
_RECORD_FIELDS = {
    "schema", "authority_id", "event_id", "ticker", "source_action_date",
    "effective_session", "source_action", "security_mapping",
    "stale_source_amount", "final_cash_amount", "currency",
    "primary_source_kind", "source_url", "source_published_at",
    "source_evidence_text", "source_content_sha256",
    "corroborating_sources", "source_priority", "record_sha256",
    "cash_entitlement_basis", "new_shares_per_old_share",
}
_FLAG_FIELDS = {
    "event_id", "ticker", "source_action_date", "effective_session",
    "source_action",
}


class CorporateActionAuthorityRefused(RuntimeError):
    """A flagged corporate action lacks complete point-in-time authority."""


@dataclass(frozen=True)
class CashAdjudication:
    event_id: str
    authority_id: str
    ticker: str
    source_action_date: str
    effective_session: str
    disposition: str
    source_amount: str
    final_cash_amount: str
    currency: str
    source_published_at: str
    source_url: str
    source_content_sha256: str
    record_sha256: str
    source_priority: str
    cash_entitlement_basis: str
    new_shares_per_old_share: str

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "authority_id": self.authority_id,
            "ticker": self.ticker,
            "source_action_date": self.source_action_date,
            "effective_session": self.effective_session,
            "disposition": self.disposition,
            "source_amount": self.source_amount,
            "final_cash_amount": self.final_cash_amount,
            "currency": self.currency,
            "source_published_at": self.source_published_at,
            "source_url": self.source_url,
            "source_content_sha256": self.source_content_sha256,
            "record_sha256": self.record_sha256,
            "source_priority": self.source_priority,
            "cash_entitlement_basis": self.cash_entitlement_basis,
            "new_shares_per_old_share": self.new_shares_per_old_share,
        }


@dataclass(frozen=True)
class CashResolution:
    dividends: dict[tuple[str, str], Decimal | AdjudicatedCashDistribution]
    adjudications: tuple[CashAdjudication, ...]


def _positive_decimal(value) -> Decimal | None:
    try:
        amount = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not amount.is_finite() or amount <= 0:
        return None
    return amount


def _snap_to_session(day: str, sessions_sorted: Sequence[str]) -> str | None:
    i = bisect.bisect_left(sessions_sorted, str(day))
    return sessions_sorted[i] if i < len(sessions_sorted) else None


def authority_record_sha256(record: Mapping) -> str:
    body = {key: record[key] for key in sorted(record)
            if key != "record_sha256"}
    payload = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _parse_timestamp(value: object) -> dt.datetime:
    try:
        parsed = dt.datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise CorporateActionAuthorityRefused(
            f"corporate-action source timestamp {value!r} is not ISO-8601"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CorporateActionAuthorityRefused(
            f"corporate-action source timestamp {value!r} has no UTC offset"
        )
    return parsed


def validate_authority(record: Mapping) -> Mapping:
    if set(record) != _RECORD_FIELDS:
        raise CorporateActionAuthorityRefused(
            "corporate-action authority record has an unknown field set")
    if record.get("schema") != _SCHEMA:
        raise CorporateActionAuthorityRefused(
            "unsupported corporate-action authority schema "
            f"{record.get('schema')!r}")
    expected_digest = authority_record_sha256(record)
    actual_digest = str(record.get("record_sha256") or "")
    if actual_digest != expected_digest:
        raise CorporateActionAuthorityRefused(
            f"corporate-action authority {record.get('authority_id')!r} failed "
            "its immutable record SHA-256")

    ticker = str(record.get("ticker") or "").strip().upper()
    action = str(record.get("source_action") or "").strip().lower()
    source_day = str(record.get("source_action_date") or "")
    effective = str(record.get("effective_session") or "")
    expected_event_id = f"{ticker}:{effective}:{action}"
    if not ticker or action not in DIVIDEND_ACTIONS:
        raise CorporateActionAuthorityRefused(
            f"corporate-action authority {actual_digest[:12]} has invalid "
            "event identity")
    if str(record.get("event_id")) != expected_event_id:
        raise CorporateActionAuthorityRefused(
            f"corporate-action authority {record.get('authority_id')!r} has "
            "incoherent canonical event identity")
    try:
        dt.date.fromisoformat(source_day)
        dt.date.fromisoformat(effective)
    except ValueError as exc:
        raise CorporateActionAuthorityRefused(
            f"corporate-action authority {record.get('authority_id')!r} has "
            "an invalid source/effective date") from exc
    if calendar.session_on_or_after(source_day) != effective:
        raise CorporateActionAuthorityRefused(
            f"corporate-action authority {record.get('authority_id')!r} maps "
            f"{source_day} to {effective}, which is not its XNYS effective "
            "session")

    stale = _positive_decimal(record.get("stale_source_amount"))
    final = _positive_decimal(record.get("final_cash_amount"))
    if stale is None or final is None or stale == final:
        raise CorporateActionAuthorityRefused(
            f"corporate-action authority {record.get('authority_id')!r} has "
            "invalid stale/final cash economics")
    if (record.get("cash_entitlement_basis") != "RAW_PRE_CONSOLIDATION_SHARE"
            or _positive_decimal(record.get("new_shares_per_old_share")) is None):
        raise CorporateActionAuthorityRefused(
            "corporate-action authority requires a raw old-share cash basis "
            "and positive new-shares-per-old-share terms")
    if record.get("currency") != "USD":
        raise CorporateActionAuthorityRefused(
            f"corporate-action authority {record.get('authority_id')!r} has "
            f"unsupported currency {record.get('currency')!r}")
    if record.get("security_mapping") != "sharadar-ticker-at-effective-session":
        raise CorporateActionAuthorityRefused(
            f"corporate-action authority {record.get('authority_id')!r} has "
            "an unknown canonical security-mapping rule")
    if record.get("primary_source_kind") != "issuer-final-terms":
        raise CorporateActionAuthorityRefused(
            f"corporate-action authority {record.get('authority_id')!r} lacks "
            "issuer-final-terms priority")
    if not str(record.get("source_url") or "").startswith("https://"):
        raise CorporateActionAuthorityRefused(
            f"corporate-action authority {record.get('authority_id')!r} has "
            "no HTTPS source identity")
    corroborating = record.get("corroborating_sources")
    if (not isinstance(corroborating, list) or len(corroborating) < 2
            or any(not str(url).startswith("https://")
                   for url in corroborating)):
        raise CorporateActionAuthorityRefused(
            f"corporate-action authority {record.get('authority_id')!r} lacks "
            "the reviewed independent corroboration set")

    evidence = str(record.get("source_evidence_text") or "")
    evidence_digest = hashlib.sha256(evidence.encode("utf-8")).hexdigest()
    if evidence_digest != str(record.get("source_content_sha256") or ""):
        raise CorporateActionAuthorityRefused(
            f"corporate-action authority {record.get('authority_id')!r} failed "
            "its retained source-content SHA-256")

    published = _parse_timestamp(record.get("source_published_at"))
    opened, _closed = calendar.session_window(effective)
    if published > opened:
        raise CorporateActionAuthorityRefused(
            f"corporate-action authority {record.get('authority_id')!r} was "
            f"published at {published.isoformat()}, after the {effective} XNYS "
            f"open {opened.isoformat()}; it has no PIT authority for that "
            "session")
    return record


def _validated_registry(
        disputed_events: Sequence[Mapping],
        authorities: Sequence[Mapping]) -> dict[str, Mapping]:
    flags: dict[str, Mapping] = {}
    for flag in disputed_events:
        if set(flag) != _FLAG_FIELDS:
            raise CorporateActionAuthorityRefused(
                "disputed cash-event registry has an unknown field set")
        event_id = str(flag.get("event_id") or "")
        if not event_id or event_id in flags:
            raise CorporateActionAuthorityRefused(
                f"disputed cash-event registry has duplicate/empty id "
                f"{event_id!r}")
        ticker = str(flag.get("ticker") or "").upper()
        action = str(flag.get("source_action") or "").lower()
        expected = f"{ticker}:{flag.get('effective_session')}:{action}"
        if event_id != expected:
            raise CorporateActionAuthorityRefused(
                f"disputed cash-event {event_id!r} has incoherent event "
                "identity")
        flags[event_id] = flag

    authority_by_event: dict[str, list[Mapping]] = {}
    for record in authorities:
        validate_authority(record)
        authority_by_event.setdefault(str(record["event_id"]), []).append(record)

    out: dict[str, Mapping] = {}
    for event_id, flag in flags.items():
        matches = authority_by_event.get(event_id, [])
        if len(matches) != 1:
            raise CorporateActionAuthorityRefused(
                f"flagged cash event {event_id} requires exactly one reviewed "
                f"authority record; found {len(matches)}")
        record = matches[0]
        for key in _FLAG_FIELDS:
            if key == "ticker":
                left, right = str(flag[key]).upper(), str(record[key]).upper()
            elif key == "source_action":
                left, right = str(flag[key]).lower(), str(record[key]).lower()
            else:
                left, right = str(flag[key]), str(record[key])
            if left != right:
                raise CorporateActionAuthorityRefused(
                    f"flagged cash event {event_id} disagrees with reviewed "
                    f"authority on {key}")
        out[event_id] = record

    extras = set(authority_by_event) - set(flags)
    if extras:
        raise CorporateActionAuthorityRefused(
            f"unflagged cash authorities are forbidden: {sorted(extras)}")
    return out


def resolve_dividends(
        rows: Iterable[Mapping],
        sessions_sorted: Sequence[str],
        *,
        disputed_events: Sequence[Mapping] = DISPUTED_CASH_EVENTS,
        authorities: Sequence[Mapping] = CASH_ADJUDICATION_AUTHORITIES,
        ) -> CashResolution:
    """Resolve ordinary Sharadar dividends plus reviewed exceptional overrides."""
    materialized = list(rows)
    sessions = {str(value) for value in sessions_sorted}
    out: dict[tuple[str, str], Decimal | AdjudicatedCashDistribution] = {}
    for row in materialized:
        if str(row.get("action") or "").lower() not in DIVIDEND_ACTIONS:
            continue
        amount = _positive_decimal(row.get("value"))
        if amount is None:
            continue
        session = _snap_to_session(str(row["date"]), sessions_sorted)
        if session is None:
            continue
        key = (str(row["ticker"]), session)
        out[key] = out.get(key, Decimal(0)) + amount

    registry = _validated_registry(disputed_events, authorities)
    audits: list[CashAdjudication] = []
    for event_id, record in sorted(registry.items()):
        effective = str(record["effective_session"])
        if effective not in sessions:
            continue
        ticker = str(record["ticker"]).upper()
        action = str(record["source_action"]).lower()
        source_day = str(record["source_action_date"])
        matching = [
            row for row in materialized
            if str(row.get("ticker") or "").upper() == ticker
            and str(row.get("action") or "").lower() == action
            and str(row.get("date") or "") == source_day
        ]
        if len(matching) != 1:
            raise CorporateActionAuthorityRefused(
                f"flagged cash event {event_id} requires exactly one matching "
                f"Sharadar source row; found {len(matching)}")
        source_amount = _positive_decimal(matching[0].get("value"))
        if source_amount is None:
            raise CorporateActionAuthorityRefused(
                f"flagged cash event {event_id} has no usable Sharadar cash "
                "amount")
        stale = Decimal(str(record["stale_source_amount"]))
        final = Decimal(str(record["final_cash_amount"]))
        key = (str(matching[0]["ticker"]), effective)
        if isinstance(out.get(key), AdjudicatedCashDistribution):
            raise CorporateActionAuthorityRefused(
                f"multiple adjudicated share bases at {key}")
        if source_amount == stale:
            if key not in out or out[key] < stale:
                raise CorporateActionAuthorityRefused(
                    f"flagged cash event {event_id} cannot identify its stale "
                    "component inside the ordinary dividend total")
            disposition = "APPLIED"
        elif source_amount == final:
            disposition = "SOURCE_CONVERGED"
        else:
            # The effective SEP row owns the cumulative vendor adjustment.
            # Normalization must prove this is an equivalent source rebase.
            disposition = "REQUIRES_DOMAIN_VALIDATION"
        out[key] = AdjudicatedCashDistribution(
            ordinary_split_adjusted_per_share=out[key] - source_amount,
            source_per_share=source_amount, stale_raw_per_share=stale,
            cash_per_old_share=final,
            new_shares_per_old_share=Decimal(str(record["new_shares_per_old_share"])))
        audits.append(CashAdjudication(
            event_id=event_id,
            authority_id=str(record["authority_id"]),
            ticker=ticker,
            source_action_date=source_day,
            effective_session=effective,
            disposition=disposition,
            source_amount=str(source_amount),
            final_cash_amount=str(final),
            currency=str(record["currency"]),
            source_published_at=str(record["source_published_at"]),
            source_url=str(record["source_url"]),
            source_content_sha256=str(record["source_content_sha256"]),
            record_sha256=str(record["record_sha256"]),
            source_priority=str(record["source_priority"]),
            cash_entitlement_basis=str(record["cash_entitlement_basis"]),
            new_shares_per_old_share=str(record["new_shares_per_old_share"]),
        ))
    return CashResolution(dividends=out, adjudications=tuple(audits))


def semantic_replay_dates(
        *, market_start: str, market_end: str,
        disputed_events: Sequence[Mapping] = DISPUTED_CASH_EVENTS,
        authorities: Sequence[Mapping] = CASH_ADJUDICATION_AUTHORITIES,
        ) -> list[str]:
    """Raw ACTIONS dates that must be replayed when this authority epoch lands."""
    registry = _validated_registry(disputed_events, authorities)
    dates = []
    for record in registry.values():
        effective = str(record["effective_session"])
        if str(market_start) <= effective <= str(market_end):
            dates.append(str(record["source_action_date"]))
    return sorted(set(dates))


def authority_manifest(
        authorities: Sequence[Mapping] = CASH_ADJUDICATION_AUTHORITIES,
        ) -> list[dict]:
    """Bounded publication evidence for the reviewed authority set."""
    for record in authorities:
        validate_authority(record)
    return [{
        "authority_id": str(record["authority_id"]),
        "event_id": str(record["event_id"]),
        "record_sha256": str(record["record_sha256"]),
        "source_content_sha256": str(record["source_content_sha256"]),
    } for record in sorted(
        authorities, key=lambda item: str(item["authority_id"]))]


__all__ = [
    "CashAdjudication", "CashResolution", "CorporateActionAuthorityRefused",
    "authority_manifest", "authority_record_sha256", "resolve_dividends",
    "semantic_replay_dates", "validate_authority",
]
