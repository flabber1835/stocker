"""Typed, non-cash spin-off evidence at the canonical ownership boundary."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
import math

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
    cash_in_lieu_price: str | None = None
    policy: str = "REQUIRE_REVIEWED_CHILD_OWNERSHIP"


LIQUIDATE_CHILD_AT_OPEN = "LIQUIDATE_CHILD_AT_OPEN"


def _positive_fraction(value, label: str) -> Fraction:
    try:
        parsed = Fraction(str(value))
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise SpinoffTermsRequired(f"invalid {label}") from exc
    if parsed <= 0:
        raise SpinoffTermsRequired(f"invalid {label}")
    return parsed


def apply_supported_entitlements(state, distributions, *, bars, ledger,
                                 config) -> tuple[dict, ...]:
    """Liquidate reviewed involuntary child shares without changing the parent.

    Every event is preflighted before any mutation.  The holder-level child
    quantity is rounded once across all episodes that own the parent.
    """
    from stock_strategy_shared.wealth_core.engine import exit_proceeds
    from stock_strategy_shared.wealth_core.ledger import EventType
    from stock_strategy_shared.wealth_core.shares import as_json

    held = [item for _, item in sorted(state.episodes.items())
            if Decimal(str(item.current_shares)) > 0]
    by_security = {}
    by_ticker = {}
    for item in held:
        by_security.setdefault(item.security_id, []).append(item)
        by_ticker.setdefault(item.ticker.upper(), []).append(item)
    bar_by_security = {item.security_id: item for item in bars}
    plans = []
    seen = set()
    for event in distributions:
        if (not isinstance(event, SpinoffDistribution)
                or not event.source_row_id or not event.parent_ticker):
            raise SpinoffTermsRequired("invalid typed spin-off source evidence")
        parents = by_security.get(event.parent_security_id or "", ())
        ticker_parents = by_ticker.get(event.parent_ticker.upper(), ())
        if not parents:
            if ticker_parents:
                raise SpinoffTermsRequired(
                    "held spin-off parent identity is unresolved or conflicts")
            continue
        if any(item.ticker.upper() != event.parent_ticker.upper()
               for item in parents):
            raise SpinoffTermsRequired(
                "held spin-off parent ticker conflicts with permanent identity")
        key = (event.session, event.parent_security_id,
               event.child_security_id, event.source_row_id)
        if key in seen:
            raise SpinoffTermsRequired("duplicate held spin-off child terms")
        seen.add(key)
        if (event.policy != LIQUIDATE_CHILD_AT_OPEN
                or not event.child_security_id or not event.child_ticker
                or event.child_security_id == event.parent_security_id):
            raise SpinoffTermsRequired(
                f"SPINOFF_CHILD_OWNERSHIP_REQUIRED: {event.parent_ticker} "
                f"on {event.session}, source {event.source_row_id}; "
                "canonical state is unchanged pending reviewed child terms")
        ratio = _positive_fraction(
            event.child_shares_per_parent, "child shares per parent")
        parent_bar = bar_by_security.get(event.parent_security_id)
        child_bar = bar_by_security.get(event.child_security_id)
        if (parent_bar is None or child_bar is None
                or parent_bar.session != event.session
                or child_bar.session != event.session
                or not getattr(child_bar, "tradeable", False)):
            raise SpinoffTermsRequired("held spin-off lacks tradable opening bars")
        parent_open = float(parent_bar.raw_open)
        child_open = float(child_bar.raw_open)
        if (not math.isfinite(parent_open) or parent_open <= 0
                or not math.isfinite(child_open) or child_open <= 0):
            raise SpinoffTermsRequired("held spin-off opening price is invalid")
        parent_shares = sum(
            (Fraction(str(item.current_shares)) for item in parents),
            Fraction(0))
        entitlement = parent_shares * ratio
        whole = entitlement.numerator // entitlement.denominator
        fractional = entitlement - whole
        cil = None
        if fractional:
            cil = _positive_fraction(
                event.cash_in_lieu_price, "cash-in-lieu price")
        whole_proceeds = exit_proceeds(float(whole), child_open, config)
        cil_proceeds = float(fractional * cil) if cil is not None else 0.0
        proceeds = whole_proceeds + cil_proceeds
        gross_child_value = float(entitlement * Fraction(str(child_open)))
        if (not math.isfinite(proceeds) or proceeds < 0
                or not math.isfinite(gross_child_value)
                or gross_child_value <= 0):
            raise SpinoffTermsRequired("held spin-off economics are invalid")
        plans.append({
            "event": event, "parents": parents, "ratio": ratio,
            "whole": whole, "fractional": fractional,
            "child_open": child_open, "proceeds": proceeds,
            "whole_proceeds": whole_proceeds,
            "gross_child_value": gross_child_value,
        })

    # A parent may distribute several child classes in one event.  Rebase its
    # reference price once against their aggregate value; multiplying separate
    # per-child scales would overstate the retained parent basis.
    groups = {}
    for plan in plans:
        event = plan["event"]
        key = (event.session, event.parent_security_id)
        group = groups.setdefault(key, {
            "parents": plan["parents"], "parent_open": float(
                bar_by_security[event.parent_security_id].raw_open),
            "child_value": 0.0,
        })
        if group["parents"] != plan["parents"]:
            raise SpinoffTermsRequired("conflicting held spin-off parent terms")
        group["child_value"] += plan["gross_child_value"] / sum(
            float(item.current_shares) for item in plan["parents"])
    for group in groups.values():
        scale = group["parent_open"] / (
            group["parent_open"] + group["child_value"])
        if not math.isfinite(scale) or not 0 < scale < 1:
            raise SpinoffTermsRequired("held spin-off economics are invalid")
        group["reference_scale"] = scale

    audit = []
    for plan in plans:
        event = plan["event"]
        reference_scale = groups[(event.session, event.parent_security_id)][
            "reference_scale"]
        before = state.cash
        ledger.post(
            session=event.session, event_type=EventType.SPINOFF_RECEIPT,
            cash_before=before, security_id=event.child_security_id,
            ticker=event.child_ticker, shares_delta=as_json(plan["whole"]),
            reason="SPINOFF_CHILD_RECEIVED",
            detail={"parent_security_id": event.parent_security_id,
                    "source_row_id": event.source_row_id,
                    "fractional_entitlement": str(plan["fractional"]),
                    "child_shares_per_parent": str(plan["ratio"])})
        fees = (float(plan["whole"]) * plan["child_open"]
                - plan["whole_proceeds"])
        sale = ledger.post(
            session=event.session, event_type=EventType.SPINOFF_LIQUIDATION,
            cash_before=before, cash_delta=plan["proceeds"],
            security_id=event.child_security_id, ticker=event.child_ticker,
            shares_delta=as_json(-plan["whole"]), price=plan["child_open"],
            fees=fees, reason="INVOLUNTARY_SPINOFF_CHILD_LIQUIDATED",
            detail={"parent_security_id": event.parent_security_id,
                    "source_row_id": event.source_row_id,
                    "cash_in_lieu": plan["proceeds"]-plan["whole_proceeds"],
                    "reference_scale": reference_scale})
        state.cash = sale.cash_after
        for parent in plan["parents"]:
            parent.source_lots = list(parent.source_lots) + [{
                "kind": "SPINOFF_CHILD_LIQUIDATION",
                "session": event.session,
                "source_row_id": event.source_row_id,
                "parent_security_id": event.parent_security_id,
                "child_security_id": event.child_security_id,
                "child_ticker": event.child_ticker,
                "child_shares_per_parent": str(plan["ratio"]),
                "child_open": plan["child_open"],
                "reference_scale": reference_scale,
            }]
        audit.append({
            "parent_security_id": event.parent_security_id,
            "child_security_id": event.child_security_id,
            "whole_child_shares": as_json(plan["whole"]),
            "fractional_child_shares": str(plan["fractional"]),
            "cash_proceeds": plan["proceeds"],
            "gross_child_value": plan["gross_child_value"],
            "reference_scale": reference_scale,
            "source_row_id": event.source_row_id,
        })
    for group in groups.values():
        for parent in group["parents"]:
            parent.entry_split_adjusted_price *= group["reference_scale"]
            if parent.episode_peak_split_adjusted_close is not None:
                parent.episode_peak_split_adjusted_close *= group["reference_scale"]
    return tuple(audit)


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
    return map_distributions(rows, session=session,
                             resolve_with_reason=resolver.resolve_with_reason)


def map_distributions(rows, *, session: str, resolve_with_reason):
    """Map explicit same-generation source rows; never infer child terms."""
    from sentinel.feed import calendar

    result = []
    for day, ticker, child, source, value in rows:
        effective = calendar.session_on_or_after(str(day))
        if effective != session:
            continue
        parent_id, _ = resolve_with_reason(str(ticker), effective)
        child_ticker = vendor_symbol(child)
        child_id = (resolve_with_reason(child_ticker, effective)[0]
                    if child_ticker else None)
        result.append(SpinoffDistribution(
            session=effective, parent_ticker=str(ticker),
            parent_security_id=parent_id, child_ticker=child_ticker,
            child_security_id=child_id, source_row_id=str(source),
            value_evidence=None if value is None else str(value)))
    return tuple(result)
