"""Offline property fuzzing for Sentinel's money-facing boundaries.

NO NETWORK.  Every target here is a pure function or an in-process value.
Nothing constructs a real broker client and nothing holds credentials.

The point is not random coverage for its own sake.  Each property names an
invariant whose violation can change economics: leverage, NaN propagation,
non-deterministic identity, silent side coercion, or incorrect exact-delta
arithmetic.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from hypothesis import given, settings, strategies as st

from sentinel import config as CFG
from sentinel.execution import commands as C
from sentinel.execution import projection as PJ
from sentinel.execution.alpaca import (
    MalformedBrokerPayload,
    _required_dec,
    _side,
)
from sentinel.execution.contract import (
    BrokerInstrument,
    BrokerObservation,
    BrokerOrder,
    BrokerPosition,
    Side,
)
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.states import CommandState as S

D = Decimal

# Keep examples numerous enough to find boundary mistakes while keeping the
# suite practical in the certified image.
FUZZ = settings(max_examples=500, deadline=None)

finite_nonnegative = st.decimals(
    min_value=D("0"), max_value=D("1000000000000"),
    allow_nan=False, allow_infinity=False, places=6)
unit_decimal = st.decimals(
    min_value=D("0"), max_value=D("1"),
    allow_nan=False, allow_infinity=False, places=8)
positive_price = st.decimals(
    min_value=D("0.000001"), max_value=D("1000000"),
    allow_nan=False, allow_infinity=False, places=6)
positive_lot = st.decimals(
    min_value=D("0.000001"), max_value=D("1000"),
    allow_nan=False, allow_infinity=False, places=6)


@FUZZ
@given(nav=finite_nonnegative, exposure=unit_decimal,
       price=positive_price, lot=positive_lot)
def test_projection_never_spends_more_than_nav(nav, exposure, price, lot):
    p = PJ.project(
        shadow_weights={"SEC-A": D("1")}, exposure=exposure, nav=nav,
        marks={"SEC-A": price}, lot=lot)
    assert p.invested_notional <= nav
    assert p.cash_residual >= 0
    assert all(q >= 0 for q in p.quantities.values())


@FUZZ
@given(weights=st.lists(unit_decimal, min_size=1, max_size=20))
def test_projection_refuses_every_overweight_book(weights):
    total = sum(weights, D(0))
    book = {f"SEC-{i}": w for i, w in enumerate(weights)}
    if total > 1:
        with pytest.raises(PJ.ProjectionRefused):
            PJ.project(shadow_weights=book, exposure=D(1), nav=D(100000),
                       marks={sid: D(100) for sid in book})
    else:
        p = PJ.project(shadow_weights=book, exposure=D(1), nav=D(100000),
                       marks={sid: D(100) for sid in book})
        assert p.invested_notional <= p.nav


@pytest.mark.parametrize("bad", [D("NaN"), D("sNaN"), D("Infinity"), D("-Infinity")])
def test_projection_refuses_nonfinite_primary_inputs(bad):
    for field in ("exposure", "nav", "lot"):
        kw = dict(shadow_weights={"SEC-A": D(1)}, exposure=D(1), nav=D(100),
                  marks={"SEC-A": D(10)}, lot=D(1))
        kw[field] = bad
        with pytest.raises(PJ.ProjectionRefused):
            PJ.project(**kw)


@pytest.mark.parametrize("bad", [D("NaN"), D("sNaN"), D("Infinity"), D("-Infinity")])
def test_nonfinite_core_marks_are_named_unpriced(bad):
    p = PJ.project(shadow_weights={"SEC-A": D(1)}, exposure=D(1), nav=D(100),
                   marks={"SEC-A": bad})
    assert p.quantities == {}
    assert p.unpriced == ("SEC-A",)


@pytest.mark.parametrize("bad", [D("NaN"), D("sNaN"), D("Infinity"), D("-Infinity")])
def test_nonfinite_defensive_marks_are_named_unpriced_not_compared(bad):
    """The defensive sleeve must obey the same no-mark/no-target rule as core."""
    p = PJ.project(shadow_weights={}, exposure=D(0), nav=D(100),
                   marks={"SEC-BIL": bad}, defensive_security="SEC-BIL")
    assert p.defensive_quantity == 0
    assert p.unpriced == ("SEC-BIL",)
    assert p.cash_residual == D(100)


@FUZZ
@given(exposure=unit_decimal, nav=finite_nonnegative,
       qty_a=finite_nonnegative, qty_b=finite_nonnegative)
def test_plan_fingerprint_is_mapping_order_independent(exposure, nav, qty_a, qty_b):
    # nav is deliberately included in the generated corpus even though plans do
    # not carry it; it varies the Hypothesis examples without entering identity.
    del nav
    common = dict(
        plan_id="p", decision_session=date(2026, 8, 11),
        effective_session=date(2026, 8, 12), target_exposure=exposure,
        data_version=7, shadow_snapshot_hash="shadow",
        sentinel_transition_hash="transition", strategy_fingerprint="strategy")
    a = ExecutionPlan(target_basket={"A": qty_a, "B": qty_b}, **common)
    b = ExecutionPlan(target_basket={"B": qty_b, "A": qty_a}, **common)
    assert a.fingerprint() == b.fingerprint()


@FUZZ
@given(qty=st.decimals(min_value=D("0"), max_value=D("1000000"),
                       allow_nan=False, allow_infinity=False, places=8))
def test_broker_required_decimal_round_trips_finite_quantities(qty):
    assert _required_dec(str(qty), where="fuzz") == qty


@pytest.mark.parametrize("bad", [None, "", "garbage", "NaN", "sNaN", "Infinity", "-Infinity"])
def test_broker_required_decimal_refuses_absence_and_non_numbers(bad):
    with pytest.raises(MalformedBrokerPayload):
        _required_dec(bad, where="fuzz")


@FUZZ
@given(raw=st.text(max_size=40))
def test_broker_side_parser_never_defaults_unknown_text_to_sell(raw):
    normal = raw.strip().lower()
    if normal in {"buy", "sell"}:
        assert _side(raw, where="fuzz") is (Side.BUY if normal == "buy" else Side.SELL)
    else:
        with pytest.raises(MalformedBrokerPayload):
            _side(raw, where="fuzz")


@FUZZ
@given(desired=finite_nonnegative, held=finite_nonnegative,
       committed_qty=finite_nonnegative, committed_side=st.sampled_from([Side.BUY, Side.SELL]))
def test_exact_delta_is_desired_minus_held_minus_signed_commitment(
        desired, held, committed_qty, committed_side):
    instrument = BrokerInstrument("SEC-A", "A", "broker-A")
    positions = () if held == 0 else (BrokerPosition(instrument, held),)
    orders = ()
    signed = D(0)
    if committed_qty > 0:
        order = BrokerOrder(
            broker_order_id="o", client_key="sntl-fuzz", instrument=instrument,
            side=committed_side, state=S.ACKNOWLEDGED,
            quantity=committed_qty, filled_quantity=D(0))
        orders = (order,)
        signed = committed_qty if committed_side is Side.BUY else -committed_qty
    obs = BrokerObservation(
        observed_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
        orders=orders, positions=positions)
    delta = C.compute_delta(security_id="SEC-A", desired=desired,
                            observation=obs, min_increment=D("0.00000001"))
    assert delta.remaining == desired - held - signed


@FUZZ
@given(prefix=st.text(max_size=30), suffix=st.text(max_size=30))
def test_paper_allowlist_never_accepts_arbitrary_prefix_or_suffix(prefix, suffix):
    canonical = CFG.DEFAULT_BASE_URL
    candidate = prefix + canonical + suffix
    # The exact canonical URL, optional path, host case, root dot and :443 are
    # intentionally covered by the existing allowlist suite.  This property is
    # the complement: arbitrary text surrounding the canonical spelling must
    # not turn a different authority into an allowed endpoint.
    if candidate == canonical:
        assert CFG.is_paper_url(candidate)
    elif CFG.is_paper_url(candidate):
        parsed_host = CFG.SentinelConfig(
            alpaca_key="k", alpaca_secret="s", base_url=candidate,
            state_dir=__import__("pathlib").Path("/tmp"), max_cycles=1,
            poll_seconds=1).endpoint_host
        assert parsed_host == "paper-api.alpaca.markets"
        assert candidate.startswith("https://")
