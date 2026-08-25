"""Strict SEP update dates and canonical source keys."""
from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Mapping, Optional


class SourceAuthorityRefused(RuntimeError):
    """A complete source observation cannot become candidate authority."""


class CanonicalSourceDuplicate(SourceAuthorityRefused):
    """SEP/SFP repeated one canonical (ticker,date) source key."""


class SepUpdateEnvelopeViolation(SourceAuthorityRefused):
    """SEP lastupdated evidence lies outside the operation's causal envelope."""


@dataclass(frozen=True)
class SepUpdateEnvelope:
    upper: dt.date
    lower: Optional[dt.date] = None
    require_present: bool = False
    context: str = "SEP observation"

    @classmethod
    def through(cls, upper: dt.date | str, *,
                context: str = "complete SEP observation") -> "SepUpdateEnvelope":
        return cls(upper=_strict_date(upper, field="update ceiling"),
                   context=context)

    @classmethod
    def interval(cls, lower: dt.date | str, upper: dt.date | str, *,
                 context: str = "bounded SEP CDC observation"
                 ) -> "SepUpdateEnvelope":
        lo = _strict_date(lower, field="update lower bound")
        hi = _strict_date(upper, field="update upper bound")
        if lo > hi:
            raise ValueError(f"reversed SEP update envelope {lo}..{hi}")
        return cls(lower=lo, upper=hi, require_present=True, context=context)

    def validate(self, value, *, ticker: str, session: str) -> Optional[dt.date]:
        if value in (None, ""):
            if self.require_present:
                self._refuse(ticker=ticker, session=session, value=value,
                             reason="lastupdated is required for a bounded CDC row")
            return None
        try:
            observed = _strict_date(value, field="lastupdated")
        except (TypeError, ValueError) as exc:
            self._refuse(ticker=ticker, session=session, value=value,
                         reason=f"lastupdated is not a strict ISO date ({exc})")
        if observed > self.upper:
            self._refuse(ticker=ticker, session=session, value=value,
                         reason=f"lastupdated exceeds causal ceiling {self.upper}")
        if self.lower is not None and observed < self.lower:
            self._refuse(ticker=ticker, session=session, value=value,
                         reason=f"lastupdated precedes causal floor {self.lower}")
        return observed

    def _refuse(self, *, ticker: str, session: str, value, reason: str) -> None:
        evidence = {
            "context": self.context,
            "key": {"ticker": ticker, "date": session},
            "lastupdated": _canonical(value),
            "lower": None if self.lower is None else self.lower.isoformat(),
            "upper": self.upper.isoformat(),
            "reason": reason,
        }
        raise SepUpdateEnvelopeViolation(
            "Sharadar SEP update envelope refused: "
            + json.dumps(evidence, sort_keys=True, separators=(",", ":")))


def _strict_date(value, *, field: str) -> dt.date:
    if isinstance(value, dt.datetime):
        raise ValueError(f"{field} must be a calendar date, not a timestamp")
    if isinstance(value, dt.date):
        return value
    text = str(value)
    parsed = dt.date.fromisoformat(text)
    if text != parsed.isoformat():
        raise ValueError(f"{field} must use YYYY-MM-DD")
    return parsed


def _canonical(value):
    if value is None:
        return None
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, Decimal)):
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return str(value)
        if not number.is_finite():
            return str(value)
        if number == 0:
            return "0"
        return format(number.normalize(), "f")
    return str(value)


def _canonical_row(row: Mapping) -> dict:
    return {str(key): _canonical(value)
            for key, value in sorted(row.items(), key=lambda item: str(item[0]))}


def _canonical_key(table: str, row: Mapping) -> tuple[str, str]:
    ticker = str(row.get("ticker") or "").strip().upper()
    if not ticker:
        raise SourceAuthorityRefused(
            f"Sharadar {table} source row has no non-empty ticker")
    raw_session = row.get("date")
    try:
        session = _strict_date(raw_session, field=f"{table} date").isoformat()
    except (TypeError, ValueError) as exc:
        raise SourceAuthorityRefused(
            f"Sharadar {table} source row {ticker!r} has invalid date "
            f"{raw_session!r}: {exc}") from exc
    return ticker, session
