"""Operational source timing, independent of installation and broker transport.

An exchange close permits acquisition. It does not prove that a provider has
finished its daily data: content, coverage and corroboration still do that.
"""
from datetime import datetime, timezone

from sentinel.feed import calendar

POLICY = "ALPACA_OPENFIGI_VALIDATED_CLOSED_SESSION_V2"


def acquisition_not_before(session: str) -> datetime:
    """The actual XNYS close, including holidays, half-days and DST."""
    return calendar.session_window(session)[1].astimezone(timezone.utc)


def latest_acquirable_session(now: datetime) -> str:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("source clock must be timezone-aware")
    return calendar.latest_closed_session(now.astimezone(timezone.utc))
