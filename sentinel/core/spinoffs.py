"""Typed, non-cash spin-off evidence at the canonical ownership boundary."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sentinel.core.terminal import SPINOFF_ACTIONS, vendor_symbol


class SpinoffTermsRequired(ValueError):
    """An entitled holding requires reviewed child ownership/valuation terms."""


@dataclass(frozen=True)
class SpinoffDistribution:
    session: str
    parent_ticker: str
    parent_security_id: str | None
    child_ticker: str | None
    child_security_id: str | None
    source_row_id: str
    value_evidence: str | None
    # ACTIONS does not contain these terms. Source value cannot supply either.
    child_shares_per_parent: str | None = None
    child_price: str | None = None
    policy: str = "REQUIRE_REVIEWED_CHILD_OWNERSHIP"


def require_supported_entitlements(state, distributions) -> None:
    episodes = (state.wealth_core.get("episodes") or {}).values()
    held = [item for item in episodes
            if Decimal(str(item.get("current_shares", 0))) > 0]
    for event in distributions:
        if not isinstance(event, SpinoffDistribution) or not event.source_row_id:
            raise SpinoffTermsRequired("invalid typed spin-off source evidence")
        if any(item.get("security_id") == event.parent_security_id
               or str(item.get("ticker", "")).upper() == event.parent_ticker.upper()
               for item in held):
            # Complete terms need a separately reviewed canonical child-book
            # implementation; even caller-supplied values cannot invent it.
            raise SpinoffTermsRequired(
                f"SPINOFF_CHILD_OWNERSHIP_REQUIRED: {event.parent_ticker} "
                f"on {event.session}, source {event.source_row_id}; "
                "canonical state is unchanged pending reviewed child terms")


def load_distributions(conn, *, session: str) -> tuple[SpinoffDistribution, ...]:
    from sentinel.feed import calendar
    from sentinel.feed.universe import load_resolver

    lo, hi = calendar.action_date_window(session, session)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT session,ticker,contraticker,source_row_id,value"
            " FROM sentinel_active_actions WHERE session BETWEEN %s AND %s"
            " AND LOWER(action)=ANY(%s) ORDER BY session,source_row_id",
            (lo, hi, sorted(SPINOFF_ACTIONS)))
        rows = cur.fetchall()
    if not rows:
        return ()
    resolver = load_resolver(conn)
    result = []
    for day, ticker, child, source, value in rows:
        effective = calendar.session_on_or_after(str(day))
        if effective != session:
            continue
        parent_id, _ = resolver.resolve_with_reason(str(ticker), effective)
        child_ticker = vendor_symbol(child)
        child_id = (resolver.resolve_with_reason(child_ticker, effective)[0]
                    if child_ticker else None)
        result.append(SpinoffDistribution(
            session=effective, parent_ticker=str(ticker),
            parent_security_id=parent_id, child_ticker=child_ticker,
            child_security_id=child_id, source_row_id=str(source),
            value_evidence=None if value is None else str(value)))
    return tuple(result)
