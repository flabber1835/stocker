"""Fixed dollar allocations and share reductions, using the existing RAW references."""
from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from fractions import Fraction

from sentinel.execution.fractional_progress import is_fractional
from sentinel.execution.market_buy_policy import FRACTIONAL_MODE, MarketBuyPolicy
from sentinel.execution.numeric import decimal_text, exact_decimal
from sentinel.execution.protected_limits import (
    PriorCloseReferences, _action_identity, _retained_quantities,
)
from sentinel.execution.target_reprojection import TargetProjectionRefused


def cents(value):
    return exact_decimal(Fraction(Fraction(value) // Fraction("0.01"), 100))


def _allocate(*, raw_targets, retained, baseline, carry, references, intents,
              nav, exposure, shadow_equity):
    from sentinel.core.decision import DEFENSIVE_SECURITY_ID
    desired = {**raw_targets, **retained}
    holdings = {sid: Decimal(qty) for sid, qty in baseline["holdings"].items()}
    prices = {sid: Fraction(price) / Fraction(references.unit_factors[sid])
              for sid, price in references.prices.items()}
    opening = {item["security_id"] for item in intents}
    core_budget = Fraction(nav) * Fraction(exposure)
    missing = [sid for sid, qty in desired.items() if qty > 0 and sid not in opening
               and sid != DEFENSIVE_SECURITY_ID and sid not in prices]
    held_value = sum((Fraction(qty) * prices[sid] for sid, qty in desired.items()
                      if sid not in opening and sid != DEFENSIVE_SECURITY_ID and sid in prices), Fraction(0))
    available = max(Fraction(0), core_budget - held_value)
    purchases, blocked = {}, {}
    for sid, raw in sorted(carry.items()):
        if sid not in retained or sid not in desired:
            raise TargetProjectionRefused("unfinished dollars cannot resurrect a departed episode")
        budget = Decimal(raw)
        if not budget.is_finite() or budget < 0 or cents(budget) != budget:
            raise TargetProjectionRefused("unfinished dollar allocation is malformed")
        purchases[sid] = {"budget": decimal_text(budget), "origin": "CONTINUING"}
        available = max(Fraction(0), available - Fraction(budget))
        desired[sid] = holdings.get(sid, Decimal(0))
    for sid, qty in sorted(desired.copy().items()):
        if sid in opening or sid in purchases:
            continue
        held = holdings.get(sid, Decimal(0))
        if qty <= held:
            continue
        if sid not in prices:
            desired[sid] = held
            blocked[sid] = "REFERENCE_UNAVAILABLE"
            continue
        budget = cents((Fraction(qty) - Fraction(held)) * prices[sid])
        purchases[sid] = {"budget": decimal_text(budget), "origin": "ALLOCATION_CHANGE"}
        desired[sid] = held
    scale = core_budget / Fraction(shadow_equity)
    for item in intents:
        sid = item["security_id"]
        if sid in retained or sid in purchases:
            continue
        if holdings.get(sid, Decimal(0)) != 0:
            raise TargetProjectionRefused("new dollar entry intersects an existing owned holding")
        if missing:
            blocked[sid] = "CORE_REFERENCE_UNAVAILABLE"
            continue
        raw = min(scale * Fraction(item["intended_dollars"]), available)
        available -= raw
        budget = cents(raw)
        if sid not in prices:
            blocked[sid] = "REFERENCE_UNAVAILABLE"
            continue
        if budget > 0:
            purchases[sid] = {"budget": decimal_text(budget), "origin": "ENTRY"}
        desired[sid] = Decimal(0)
    return dict(sorted(desired.items())), dict(sorted(purchases.items())), dict(sorted(blocked.items()))


def resolve(state, plan, projection, references, policy, *, baseline,
            retained_targets, carried_budgets=None):
    from sentinel.core.decision import _shadow_equity, shadow_target
    if not policy.fractional or state.state_hash != plan.shadow_snapshot_hash:
        raise TargetProjectionRefused("fractional allocation requires the selected canonical plan")
    if shadow_target(state).opening_intents != plan.opening_intents:
        raise TargetProjectionRefused("fractional allocation changed canonical opening eligibility")
    retained = _retained_quantities(projection, retained_targets)
    evidence = {
        "mode": FRACTIONAL_MODE, "policy": policy.to_dict(), "policy_sha256": policy.fingerprint(),
        "references": references.to_dict(), "baseline": baseline,
        "raw_targets": {sid: decimal_text(qty) for sid, qty in sorted(projection.target_basket.items())},
        "retained_targets": {sid: decimal_text(qty) for sid, qty in sorted(retained.items())},
        "carried_budgets": dict(sorted((carried_budgets or {}).items())),
        "intents": [item.to_dict() for item in plan.opening_intents],
        "nav": decimal_text(plan.account_nav), "exposure": decimal_text(plan.target_exposure),
        "shadow_equity": decimal_text(_shadow_equity(state)),
    }
    basket, purchases, blocked = _allocate(
        raw_targets=projection.target_basket, retained=retained, baseline=baseline,
        carry=evidence["carried_budgets"], references=references, intents=evidence["intents"],
        nav=plan.account_nav, exposure=plan.target_exposure, shadow_equity=_shadow_equity(state))
    result = replace(projection, target_basket=basket,
        opening_sizing={**evidence, "purchases": purchases, "blocked": blocked})
    validate_projection(result, plan=plan)
    return result


def validate_projection(projection, *, require_current_policy=False, plan=None):
    if not is_fractional(projection):
        raise TargetProjectionRefused("fractional allocation projection is absent")
    evidence = projection.opening_sizing
    if set(evidence) != {"mode", "policy", "policy_sha256", "references", "baseline",
                        "raw_targets", "retained_targets", "carried_budgets", "intents",
                        "nav", "exposure", "shadow_equity", "purchases", "blocked"}:
        raise TargetProjectionRefused("fractional allocation projection has an unknown shape")
    try:
        policy = MarketBuyPolicy.from_dict(evidence["policy"])
        if not policy.fractional or evidence["policy_sha256"] != policy.fingerprint():
            raise ValueError("fractional policy identity differs")
        if require_current_policy and MarketBuyPolicy.from_env() != policy:
            raise ValueError("fractional policy selection differs")
        refs = PriorCloseReferences.from_dict(evidence["references"])
        if (refs.plan_fingerprint != projection.plan_fingerprint
                or refs.effective_session != projection.through_session
                or refs.action_evidence_sha256 != _action_identity(projection)):
            raise ValueError("fractional RAW references differ from the unit projection")
        if plan is not None and (
                plan.plan_id != projection.plan_id or plan.fingerprint() != projection.plan_fingerprint
                or refs.publication_fingerprint != plan.publication_fingerprint
                or evidence["intents"] != [item.to_dict() for item in plan.opening_intents]
                or Decimal(evidence["nav"]) != plan.account_nav
                or Decimal(evidence["exposure"]) != plan.target_exposure):
            raise ValueError("fractional allocation differs from original plan")
        targets, purchases, blocked = _allocate(
            raw_targets={sid: Decimal(qty) for sid, qty in evidence["raw_targets"].items()},
            retained={sid: Decimal(qty) for sid, qty in evidence["retained_targets"].items()},
            baseline=evidence["baseline"], carry=evidence["carried_budgets"], references=refs,
            intents=evidence["intents"], nav=Decimal(evidence["nav"]),
            exposure=Decimal(evidence["exposure"]), shadow_equity=Decimal(evidence["shadow_equity"]))
        if (targets != projection.target_basket or purchases != evidence["purchases"]
                or blocked != evidence["blocked"]):
            raise ValueError("fractional budget does not rederive")
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise TargetProjectionRefused("fractional allocation is malformed: " + str(exc)) from exc
    return policy
