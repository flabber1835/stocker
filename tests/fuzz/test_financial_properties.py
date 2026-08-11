"""Adversarial property fuzzing for certification-critical pure boundaries.

This suite intentionally uses deterministic pseudo-random generation instead of a
new runtime dependency. Every failure prints its seed/case and is therefore
replayable. It targets invariants, not coverage numbers.
"""
from __future__ import annotations

import math
import random
from datetime import date, timedelta
from decimal import Decimal

import pytest

from sentinel.execution.projection import ProjectionRefused, project as exec_project
from sentinel.core.catchup import project as catchup_project
from sentinel.execution.alpaca import map_status, UnmappedBrokerStatus
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.executor import _assert_executable, RiskEnvelopeViolation


SEEDS = range(200)
D = Decimal


def _rng(seed):
    return random.Random(0x5E471E1 + seed)


@pytest.mark.parametrize("seed", SEEDS)
def test_projection_never_invests_more_than_nav(seed):
    """A long-only unlevered projection may never create > NAV core notional."""
    r = _rng(seed)
    n = r.randint(1, 40)
    # Deliberately include malformed aggregate weights. The membrane must either
    # refuse them or preserve the unlevered invariant; silently leveraging fails.
    weights = {f"S{i}": D(str(r.uniform(0, .12))) for i in range(n)}
    marks = {k: D(str(r.uniform(1, 1000))) for k in weights}
    nav = D(str(r.uniform(1000, 1_000_000)))
    exposure = D(str(r.random()))
    try:
        p = exec_project(shadow_weights=weights, exposure=exposure, nav=nav, marks=marks)
    except (ProjectionRefused, ValueError):
        return
    assert p.invested_notional <= nav, (seed, sum(weights.values()), p.invested_notional, nav)


@pytest.mark.parametrize("seed", SEEDS)
def test_projection_never_accepts_negative_weights_as_normal(seed):
    r = _rng(seed)
    weights = {"GOOD": D("0.04"), "BAD": -D(str(r.uniform(.000001, 1)))}
    marks = {"GOOD": D("10"), "BAD": D("10")}
    try:
        p = exec_project(shadow_weights=weights, exposure=D("1"), nav=D("10000"), marks=marks)
    except (ProjectionRefused, ValueError):
        return
    # Accepting the input while simply disappearing BAD is dangerous because it
    # converts malformed economics into a plausible-looking valid basket.
    pytest.fail(f"seed={seed}: negative shadow weight accepted: {p}")


@pytest.mark.parametrize("seed", SEEDS)
def test_catchup_projection_is_unlevered_or_refuses(seed):
    r = _rng(seed)
    n = r.randint(2, 30)
    weights = {f"S{i}": D(str(r.uniform(.03, .15))) for i in range(n)}
    marks = {k: D(str(r.uniform(2, 500))) for k in weights}
    nav = D("100000")
    try:
        basket = catchup_project(weights=weights, nav=nav, exposure=D("1"), marks=marks)
    except (ValueError, ProjectionRefused):
        return
    notional = sum((basket[s] * marks[s] for s in basket), D(0))
    assert notional <= nav, (seed, sum(weights.values()), notional)


@pytest.mark.parametrize("seed", SEEDS)
def test_execution_membrane_rejects_negative_target_quantity(seed):
    r = _rng(seed)
    q = -D(str(r.randint(1, 1_000_000)))
    plan = ExecutionPlan(
        plan_id=f"fuzz-{seed}", decision_session=date(2026, 1, 2),
        effective_session=date(2026, 1, 5), target_exposure=D(str(r.random())),
        target_basket={"FUZZ": q},
    )
    with pytest.raises(RiskEnvelopeViolation):
        _assert_executable(plan)


@pytest.mark.parametrize("seed", SEEDS)
def test_execution_membrane_rejects_scalar_outside_unit_interval(seed):
    r = _rng(seed)
    x = D(str(r.uniform(1.000001, 1000))) if seed % 2 else -D(str(r.uniform(.000001, 1000)))
    plan = ExecutionPlan(
        plan_id=f"scalar-{seed}", decision_session=date(2026, 1, 2),
        effective_session=date(2026, 1, 5), target_exposure=x,
        target_basket={},
    )
    with pytest.raises(RiskEnvelopeViolation):
        _assert_executable(plan)


def test_unknown_broker_statuses_fail_closed_fuzz():
    known = {"new", "accepted", "pending_new", "accepted_for_bidding", "held",
             "suspended", "stopped", "calculated", "done_for_day",
             "pending_replace", "replaced", "partially_filled", "filled",
             "canceled", "cancelled", "expired", "pending_cancel", "rejected"}
    r = random.Random(0xB20CE2)
    alphabet = "abcdefghijklmnopqrstuvwxyz_-0123456789"
    checked = 0
    for _ in range(5000):
        s = "".join(r.choice(alphabet) for _ in range(r.randint(0, 30)))
        if s.lower() in known:
            continue
        checked += 1
        with pytest.raises(UnmappedBrokerStatus):
            map_status(s)
    assert checked > 4900
