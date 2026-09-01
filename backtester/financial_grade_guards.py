"""Fail-closed financial-grade guards for historical production replay.

These guards do not reimplement the production strategy. They constrain the
historical simulation at boundaries where the retained market data cannot
support an economically defensible certified result:

* financially certified NAV must be resolved, never a stale estimate;
* missing next-close leadership returns are unresolved, never zero;
* dividend receivables become spendable only after a declared conservative lag;
* an executable pending order may not exceed a causal participation ceiling
  derived only from prior sessions' reported volume.
"""
from __future__ import annotations

import math
from typing import Mapping

from stock_strategy_shared.wealth_core.engine import WealthCoreConfig

DIVIDEND_SETTLEMENT_LAG_SESSIONS = 15
MAX_TRAILING_VOLUME_PARTICIPATION = 0.10
MIN_TRAILING_VOLUME_SESSIONS = 20


class FinancialGradeGuardError(RuntimeError):
    """The replay reached an observation that cannot be financially certified."""


def _positive(value) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0.0


def _mapping(value) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _pending(prior):
    if hasattr(prior, "pending"):
        return list(getattr(prior, "pending") or ())
    return list(_mapping(prior).get("pending") or ())


def _feed(prior) -> Mapping:
    if hasattr(prior, "feed"):
        return _mapping(getattr(prior, "feed"))
    return _mapping(_mapping(prior).get("feed"))


def _order_value(order, key, default=None):
    if isinstance(order, Mapping):
        return order.get(key, default)
    return getattr(order, key, default)


def _capacity_guard(prior, published) -> None:
    """Reject full-open fills larger than 10% of prior 20-session share volume.

    The current session's completed volume is deliberately excluded. Using it to
    decide what could fill at the opening auction would leak information from
    later in the same session.
    """
    bars = {
        str(getattr(bar, "security_id")): bar
        for bar in (getattr(published, "bars", None) or ())
    }
    series_by_security = _mapping(_feed(prior).get("series"))
    for order in _pending(prior):
        sid = str(_order_value(order, "security_id", "") or "")
        if not sid:
            continue
        bar = bars.get(sid)
        if bar is None:
            continue
        if not bool(getattr(bar, "tradeable", False)) or not _positive(
            getattr(bar, "raw_open", None)
        ):
            continue
        shares = _order_value(order, "shares", 0)
        if not _positive(shares):
            continue
        series = _mapping(series_by_security.get(sid))
        prior_volumes = [
            float(value)
            for value in list(series.get("volumes") or ())[-MIN_TRAILING_VOLUME_SESSIONS:]
            if _positive(value)
        ]
        if len(prior_volumes) < MIN_TRAILING_VOLUME_SESSIONS:
            raise FinancialGradeGuardError(
                f"capacity authority incomplete for executable order {sid}: "
                f"have {len(prior_volumes)} prior volume sessions, require "
                f"{MIN_TRAILING_VOLUME_SESSIONS}"
            )
        average_volume = sum(prior_volumes) / len(prior_volumes)
        participation = float(shares) / average_volume
        if participation > MAX_TRAILING_VOLUME_PARTICIPATION + 1e-15:
            raise FinancialGradeGuardError(
                f"capacity ceiling exceeded on {getattr(published, 'session', '?')} "
                f"{sid}: shares={float(shares):.8g} prior20_avg_volume="
                f"{average_volume:.8g} participation={participation:.4%} > "
                f"{MAX_TRAILING_VOLUME_PARTICIPATION:.2%}"
            )


def _resolved_nav_guard(result, session: str) -> None:
    evidence = _mapping(getattr(result, "last_evidence", None))
    wealth = _mapping(evidence.get("wealth_core"))
    if not wealth:
        raise FinancialGradeGuardError(
            f"production session {session} emitted no Wealth Core valuation evidence"
        )
    if bool(wealth.get("blocked")) or not _positive(wealth.get("resolved_equity")):
        unresolved = wealth.get("open_unresolved_security_ids") or ()
        raise FinancialGradeGuardError(
            f"financial-grade NAV unresolved on {session}: "
            f"blocked={wealth.get('blocked')} resolved_equity="
            f"{wealth.get('resolved_equity')!r} unresolved={list(unresolved)!r}"
        )


def install(strategy_production) -> None:
    """Install guards once around the exact pinned production transition."""
    if getattr(strategy_production, "_financial_grade_guards_installed", False):
        return

    import sentinel.controller.concordance as concordance

    original_equal_weight = concordance.equal_weight_next_close_return

    def strict_equal_weight(selected_security_ids, previous_close, current_close):
        missing = []
        for security_id in tuple(selected_security_ids):
            p0 = previous_close.get(security_id)
            p1 = current_close.get(security_id)
            if not (_positive(p0) and _positive(p1)):
                missing.append(str(security_id))
        if missing:
            raise FinancialGradeGuardError(
                "recent-leadership next-close return is unresolved for: "
                + ", ".join(sorted(missing))
            )
        return original_equal_weight(
            selected_security_ids, previous_close, current_close
        )

    concordance.equal_weight_next_close_return = strict_equal_weight

    original_advance_state = strategy_production.advance_state
    financial_config = WealthCoreConfig(
        dividend_settlement_lag_sessions=DIVIDEND_SETTLEMENT_LAG_SESSIONS
    )

    def guarded_advance_state(prior, published, *args, **kwargs):
        _capacity_guard(prior, published)
        configured = kwargs.get("wealth_config")
        if configured is None:
            kwargs["wealth_config"] = financial_config
        elif (
            getattr(configured, "dividend_settlement_lag_sessions", None)
            != DIVIDEND_SETTLEMENT_LAG_SESSIONS
        ):
            raise FinancialGradeGuardError(
                "production replay requested a dividend cash lag inconsistent "
                f"with financial certification: "
                f"{getattr(configured, 'dividend_settlement_lag_sessions', None)} "
                f"!= {DIVIDEND_SETTLEMENT_LAG_SESSIONS}"
            )
        result = original_advance_state(prior, published, *args, **kwargs)
        _resolved_nav_guard(result, str(getattr(published, "session", "?")))
        return result

    strategy_production.advance_state = guarded_advance_state
    strategy_production._financial_grade_guards_installed = True


__all__ = [
    "DIVIDEND_SETTLEMENT_LAG_SESSIONS",
    "FinancialGradeGuardError",
    "MAX_TRAILING_VOLUME_PARTICIPATION",
    "MIN_TRAILING_VOLUME_SESSIONS",
    "install",
]
