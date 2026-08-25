"""Fail-closed session-envelope validation for date-bounded source reads.

A provider-side ``date.gte``/``date.lte`` filter is request intent, not proof
about the rows returned.  Every SEP/SFP row must therefore prove its own session
before it can participate in a source fingerprint, staging, normalization, or
publication evidence.

The validator is streaming and retains only one bounded evidence object on
failure.  It never filters an unexpected row: one malformed, off-window, or
non-XNYS session refuses the complete source observation.
"""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

from sentinel.feed import calendar

SCHEMA = "sentinel.source-session-envelope/1"
SESSION_TABLES = frozenset({"SEP", "SFP"})
_MAX_EVIDENCE_TEXT = 160


class SessionEnvelopeConfigurationInvalid(ValueError):
    """A caller requested envelope validation without a valid closed interval."""


@dataclass(frozen=True)
class SessionEnvelopeEvidence:
    """Bounded deterministic evidence for the first invalid source row."""

    source: str
    operation: str
    date_from: str
    date_to: str
    row_number: int
    ticker: str | None
    permaticker: str | None
    session: str | None
    reason: str
    schema: str = SCHEMA

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "source": self.source,
            "operation": self.operation,
            "request_interval": [self.date_from, self.date_to],
            "row_number": self.row_number,
            "ticker": self.ticker,
            "permaticker": self.permaticker,
            "session": self.session,
            "reason": self.reason,
        }


class SourceSessionEnvelopeViolation(RuntimeError):
    """A SEP/SFP source row is outside the exact request/session contract."""

    def __init__(self, evidence: SessionEnvelopeEvidence):
        self.evidence = evidence
        encoded = json.dumps(
            evidence.to_dict(), sort_keys=True, separators=(",", ":"))
        super().__init__(f"Sharadar source session envelope refused: {encoded}")


def _bounded_text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if len(text) > _MAX_EVIDENCE_TEXT:
        return text[:_MAX_EVIDENCE_TEXT] + "..."
    return text


def _bound(value, *, name: str) -> dt.date:
    text = _bounded_text(value)
    if text is None:
        raise SessionEnvelopeConfigurationInvalid(
            f"source session envelope requires explicit {name}")
    try:
        return dt.date.fromisoformat(text)
    except ValueError as exc:
        raise SessionEnvelopeConfigurationInvalid(
            f"source session envelope {name} is not an ISO date: {text!r}") from exc


def validate_rows(
        rows: Iterable[Mapping], *, source: str, date_from, date_to,
        operation: str = "stable_sharadar_fetch"):
    """Yield rows only after validating their own session against ``[lo, hi]``.

    Validation occurs immediately before each yield.  A consumer therefore
    cannot fingerprint, stage, normalize, or persist an invalid row.  XNYS
    membership is derived once from the pinned calendar and is bounded by the
    requested interval rather than by source row count.
    """
    source_name = str(source).strip().upper()
    operation_name = _bounded_text(operation) or "unspecified"
    lo = _bound(date_from, name="date.gte")
    hi = _bound(date_to, name="date.lte")
    if lo > hi:
        raise SessionEnvelopeConfigurationInvalid(
            f"source session envelope is reversed: {lo} is after {hi}")
    lo_text, hi_text = lo.isoformat(), hi.isoformat()
    expected_sessions = frozenset(calendar.sessions_in_range(lo_text, hi_text))

    def refuse(row_number: int, row, session, reason: str):
        mapping = row if isinstance(row, Mapping) else {}
        raise SourceSessionEnvelopeViolation(SessionEnvelopeEvidence(
            source=source_name,
            operation=operation_name,
            date_from=lo_text,
            date_to=hi_text,
            row_number=int(row_number),
            ticker=_bounded_text(mapping.get("ticker")),
            permaticker=_bounded_text(mapping.get("permaticker")),
            session=_bounded_text(session),
            reason=reason,
        ))

    for row_number, row in enumerate(rows, 1):
        if not isinstance(row, Mapping):
            refuse(row_number, row, None, "row_not_mapping")
        raw_session = row.get("date")
        session_text = _bounded_text(raw_session)
        if session_text is None:
            refuse(row_number, row, raw_session, "missing_session")
        try:
            session = dt.date.fromisoformat(session_text)
        except ValueError:
            refuse(row_number, row, raw_session, "malformed_session")
        if session < lo:
            refuse(row_number, row, session_text, "session_before_request")
        if session > hi:
            refuse(row_number, row, session_text, "session_after_request")
        if session_text not in expected_sessions:
            refuse(row_number, row, session_text, "non_xnys_session")
        yield row


def validate_requested_rows(
        rows: Iterable[Mapping], *, source: str, params: Mapping | None,
        operation: str = "stable_sharadar_fetch", require_bounds: bool = False):
    """Apply the contract when a request declares a closed date interval.

    CDC-style source reads may intentionally use a different axis and therefore
    omit one or both date bounds.  They are left unchanged unless the caller
    explicitly sets ``require_bounds``.  Every primary and reconciliation
    SEP/SFP call covered by issues #252/#253 supplies both bounds.
    """
    request = dict(params or {})
    date_from = request.get("date.gte")
    date_to = request.get("date.lte")
    has_from = date_from not in (None, "")
    has_to = date_to not in (None, "")
    if has_from and has_to:
        return validate_rows(
            rows, source=source, date_from=date_from, date_to=date_to,
            operation=operation)
    if require_bounds:
        missing = []
        if not has_from:
            missing.append("date.gte")
        if not has_to:
            missing.append("date.lte")
        raise SessionEnvelopeConfigurationInvalid(
            "date-bounded source operation lacks " + ", ".join(missing))
    return rows


class SessionEnvelopeFetch:
    """Transport decorator validating every date-bounded SEP/SFP traversal."""

    def __init__(self, fetch: Callable, *, operation: str):
        self._fetch = fetch
        self._operation = _bounded_text(operation) or "stable_sharadar_fetch"

    def __call__(self, table, params=None, **kwargs):
        rows = self._fetch(table, params, **kwargs)
        source = str(table).strip().upper()
        if source not in SESSION_TABLES:
            return rows
        return validate_requested_rows(
            rows, source=source, params=params, operation=self._operation)


__all__ = [
    "SCHEMA", "SESSION_TABLES", "SessionEnvelopeConfigurationInvalid",
    "SessionEnvelopeEvidence", "SessionEnvelopeFetch",
    "SourceSessionEnvelopeViolation", "validate_requested_rows",
    "validate_rows",
]
