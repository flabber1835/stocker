"""Immutable whole-share sizing evidence for the explicit PAPER market policy."""

from dataclasses import replace
from decimal import Decimal
from fractions import Fraction
from typing import Mapping

from sentinel.execution.market_buy_policy import (
    MARKET_BUY_HEADROOM,
    MARKET_MODE,
    MarketBuyPolicy,
    estimated_market_buy_cost,
)
from sentinel.execution.numeric import decimal_text
from sentinel.execution.opening_prices import (
    QUOTE_SOURCE, OpeningPrices, OpeningPriceUnavailable, RegularQuotes,
)
from sentinel.execution.target_reprojection import TargetProjectionRefused


def is_market_projection(projection) -> bool:
    from sentinel.execution.fractional_progress import is_fractional
    evidence = None if projection is None else projection.opening_sizing
    return is_fractional(projection) or isinstance(evidence, Mapping) and evidence.get("mode") == MARKET_MODE


def _entry_shares(row, ask, scale):
    budget = Fraction(row["budget"]) * scale
    if budget < 0:
        raise TargetProjectionRefused("market entry has a negative allocation")
    unit_estimate = Fraction(estimated_market_buy_cost(Decimal(1), ask)) - Fraction(MARKET_BUY_HEADROOM)
    affordable = max(Fraction(0), budget - Fraction(MARKET_BUY_HEADROOM)) // unit_estimate
    return min(Decimal(row["account_shares"]), Decimal(affordable))


def original_prices(projection):
    """Read the original quote snapshot, including explicit unavailability."""
    if not is_market_projection(projection):
        return None
    from sentinel.execution.fractional_progress import is_fractional
    if is_fractional(projection):
        return None
    opening = projection.opening_sizing["opening"]
    if opening.get("prices") is None:
        return None
    return OpeningPrices.from_dict(opening["prices"])


def resolve(state, plan, projection, prices, policy, *, retained_targets):
    from sentinel.core.decision import _shadow_equity
    from sentinel.execution import opening_sizing
    from sentinel.execution.protected_limits import _retained_quantities

    retained = _retained_quantities(projection, retained_targets)
    if not plan.opening_intents:
        return replace(projection, target_basket={**projection.target_basket, **retained})
    if isinstance(prices, OpeningPrices) and (
            not isinstance(prices, RegularQuotes) or prices.source != QUOTE_SOURCE):
        raise TargetProjectionRefused("market BUY sizing requires native IEX regular quotes")
    projection = opening_sizing.resolve(state, plan, projection, prices)
    opening = projection.opening_sizing
    scale = None
    if opening["mode"] == opening_sizing.FINAL_MODE:
        scale = Fraction(plan.target_exposure) * Fraction(plan.account_nav) / Fraction(_shadow_equity(state))

    basket = {**projection.target_basket, **retained}
    if scale is not None:
        for row in opening["entries"]:
            security_id = row["security_id"]
            if security_id not in retained and security_id in prices.prices:
                basket[security_id] = _entry_shares(row, prices.prices[security_id], scale)
    projection = replace(projection, target_basket=basket, opening_sizing={
        "mode": MARKET_MODE,
        "policy": policy.to_dict(),
        "policy_sha256": policy.fingerprint(),
        "opening": opening,
        "account_scale": str(scale) if scale is not None else None,
        "retained_targets": {sid: decimal_text(quantity) for sid, quantity in sorted(retained.items())},
    })
    validate_projection(projection, plan=plan)
    return projection


def validate_projection(projection, *, require_current_policy=False, plan=None):
    from sentinel.execution import fractional_sizing
    if fractional_sizing.is_fractional(projection):
        return fractional_sizing.validate_projection(projection,
            require_current_policy=require_current_policy, plan=plan)
    from sentinel.execution.opening_sizing import FINAL_MODE, UNAVAILABLE_MODE, ZERO_MODE

    if not is_market_projection(projection):
        if (plan is None or projection is None or plan.opening_intents
                or projection.opening_sizing is not None or projection.plan_id != plan.plan_id
                or projection.plan_fingerprint != plan.fingerprint()
                or projection.through_session != plan.effective_session):
            raise TargetProjectionRefused("market BUY projection is absent")
        # Fixed targets use the existing unit projection. The caller separately
        # authenticates the policy in the plan's durable sizing authority.
        policy = MarketBuyPolicy()
        if require_current_policy and MarketBuyPolicy.from_env() != policy:
            raise TargetProjectionRefused("market BUY projection differs from current policy")
        return policy
    evidence = projection.opening_sizing
    if set(evidence) != {
        "mode", "policy", "policy_sha256", "opening", "account_scale", "retained_targets",
    }:
        raise TargetProjectionRefused("market BUY projection shape differs")
    try:
        policy = MarketBuyPolicy.from_dict(evidence["policy"])
        if evidence["policy_sha256"] != policy.fingerprint():
            raise TargetProjectionRefused("market BUY projection policy hash differs")
        if require_current_policy and MarketBuyPolicy.from_env() != policy:
            raise TargetProjectionRefused("market BUY projection differs from current policy")
        retained = evidence["retained_targets"]
        if not isinstance(retained, dict):
            raise TargetProjectionRefused("market BUY projection retained quantities differ")
        for sid, raw in retained.items():
            quantity = Decimal(raw)
            if (not isinstance(raw, str) or not quantity.is_finite() or quantity < 0
                    or quantity != projection.target_basket.get(sid)):
                raise TargetProjectionRefused("market BUY projection retained quantities differ")
        opening = evidence["opening"]
        if not isinstance(opening, dict) or not opening.get("intents"):
            raise TargetProjectionRefused("market BUY opening intents are absent")
        if plan is not None and (
            projection.plan_id != plan.plan_id
            or projection.plan_fingerprint != plan.fingerprint()
            or projection.through_session != plan.effective_session
            or opening["intents"] != [intent.to_dict() for intent in plan.opening_intents]
        ):
            raise TargetProjectionRefused("market BUY projection differs from original plan")
        if opening["mode"] in {UNAVAILABLE_MODE, ZERO_MODE}:
            if evidence["account_scale"] is not None:
                raise TargetProjectionRefused("market BUY sizing scale requires a quote allocation")
            if any(
                projection.target_basket.get(intent["security_id"]) != 0
                for intent in opening["intents"] if intent["security_id"] not in retained
            ):
                raise TargetProjectionRefused("market BUY without opening quotes has a sized entry")
            return policy
        prices = original_prices(projection)
        if (opening["mode"] != FINAL_MODE or not isinstance(prices, RegularQuotes)
                or prices.source != QUOTE_SOURCE or prices.session != projection.through_session):
            raise TargetProjectionRefused("market BUY projection lacks effective-session IEX quotes")
        scale = Fraction(evidence["account_scale"])
        ids = [intent["security_id"] for intent in opening["intents"]]
        if (scale < 0 or len(ids) != len(set(ids))
                or [row["security_id"] for row in opening["entries"]] != ids):
            raise TargetProjectionRefused("market BUY priority sizing is malformed")
        for row in opening["entries"]:
            sid = row["security_id"]
            if sid in retained:
                continue
            quantity = (_entry_shares(row, prices.prices[sid], scale) if sid in prices.prices
                        else Decimal(0))
            if (not quantity.is_finite() or quantity < 0 or quantity != quantity.to_integral_value()
                    or projection.target_basket.get(sid) != quantity):
                raise TargetProjectionRefused("market BUY quantity differs from its quote allocation")
    except TargetProjectionRefused:
        raise
    except (ArithmeticError, KeyError, TypeError, ValueError, OpeningPriceUnavailable) as exc:
        raise TargetProjectionRefused("market BUY projection is malformed") from exc
    return policy


def entry_budget(projection, security_id):
    """Return the account-unit budget for a new entry, or None for a fixed target."""
    if not is_market_projection(projection):
        return None
    from sentinel.execution.fractional_progress import is_fractional
    if is_fractional(projection):
        row = projection.opening_sizing["purchases"].get(security_id)
        return None if row is None else Fraction(row["budget"])
    evidence = projection.opening_sizing
    if security_id in evidence["retained_targets"] or evidence["account_scale"] is None:
        return None
    for row in evidence["opening"]["entries"]:
        if row["security_id"] == security_id and "budget" in row:
            return Fraction(row["budget"]) * Fraction(evidence["account_scale"])
    return None


def unavailable_opening_intents(projection):
    validate_projection(projection)
    from sentinel.execution.fractional_progress import is_fractional
    if is_fractional(projection):
        return dict(projection.opening_sizing["blocked"])
    evidence = projection.opening_sizing
    opening = evidence["opening"]
    from sentinel.execution.opening_sizing import UNAVAILABLE_MODE

    if opening["mode"] == UNAVAILABLE_MODE:
        return {item["security_id"]: "PRICE_PENDING" for item in opening["intents"]
                if item["security_id"] not in evidence["retained_targets"]}
    return {row["security_id"]: "PRICE_PENDING" for row in opening["entries"]
            if row.get("status") == "PRICE_PENDING" and row["security_id"] not in evidence["retained_targets"]}
