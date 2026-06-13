"""
Regression tests for the cash_reserve drift-basis bug.

The portfolio-builder scales persisted target weights DOWN by (1 - cash_reserve)
so the book holds a cash buffer (e.g. a fully-invested book targets sum to ~0.975
at cash_reserve=0.025). The delta engine, however, computes actual broker weights
as market_value / account_value, which for a fully-invested book sum to ~1.0.

Diffing those two directly reads every held name as structurally overweight by
~cash_reserve/N — a uniform positive drift bias. Below the rebalance drift
threshold it is masked, but raise cash_reserve or concentrate the book and it
crosses the threshold → phantom sell_trim intents every run that bleed the book
toward cash.

The fix: evaluate_target_vs_live takes a cash_fraction argument and grosses the
COMPARISON target up to the sum-to-1 basis the actual weights live on, for the
drift comparison only (current_weight, which the executor sizes against, is left
as the persisted cash-scaled target). These tests prove:
  - a fully-invested, on-target book at cash_reserve 0.025 and 0.10 produces NO
    sell_trim from the cash bias alone (drift ~0 after the fix),
  - a GENUINE overweight still trips sell_trim,
  - a genuine underweight still trips buy_add,
  - the persisted current_weight is unchanged,
  - cash_fraction=0/None is a strict no-op (back-compat with the raw diff).
"""
from datetime import date, timedelta

import pytest

from app.engine import RankObservation, evaluate_target_vs_live

BASE_DATE = date(2026, 5, 17)


def _history(*ranks):
    return [
        RankObservation(run_date=BASE_DATE - timedelta(days=i), rank=r, composite_score=1.0)
        for i, r in enumerate(ranks)
    ]


def _fully_invested_book(n: int, cash_reserve: float):
    """An equal-weight, perfectly-on-target, fully-invested book of n names.

    Returns (target_portfolio, live_positions, universe, actual_weights).
    - target weights are the builder's cash-scaled weights: each (1-cash)/n,
      summing to (1 - cash_reserve).
    - actual broker weights are market_value/account_value for a fully-invested
      book: each 1/n, summing to 1.0 (cash sits in the account, not a position).
    The book is exactly on target — the ONLY discrepancy is the cash-reserve
    basis mismatch, which must NOT generate any sell_trim after the fix.
    """
    tickers = [f"T{i:02d}" for i in range(n)]
    target = {t: (1.0 - cash_reserve) / n for t in tickers}
    actual = {t: 1.0 / n for t in tickers}
    live = set(tickers)
    universe = {t: _history(10, 10, 10) for t in tickers}
    return target, live, universe, actual


@pytest.mark.parametrize("cash_reserve", [0.025, 0.10])
def test_no_sell_trim_from_cash_reserve_bias(cash_reserve):
    """Fully-invested equal-weight book, on target: the cash-reserve basis gap
    alone must NOT produce a sell_trim. Concentrated enough (n=8) that the raw
    per-name bias (cash_reserve/n) would otherwise exceed a typical threshold."""
    n = 8
    target, live, universe, actual = _fully_invested_book(n, cash_reserve)

    # Sanity: WITHOUT the fix this book IS biased overweight. At n=8, cash 0.10,
    # the raw per-name drift is 1/8 - 0.9/8 = 0.0125; cash 0.025 → 0.003125.
    raw_bias = 1.0 / n - (1.0 - cash_reserve) / n
    assert raw_bias > 0

    decisions = evaluate_target_vs_live(
        target_portfolio=target,
        live_positions=live,
        universe=universe,
        confirmation_days=3,
        max_positions=30,
        actual_weights=actual,
        drift_threshold=0.002,           # tight threshold: raw bias would trip it
        cash_fraction=cash_reserve,
    )

    actions = {t: d.action for t, d in decisions.items()}
    assert all(a == "hold" for a in actions.values()), (
        f"cash_reserve={cash_reserve}: expected all holds, got {actions}"
    )
    # Drift is ~0 on the common basis (every held name).
    for t, d in decisions.items():
        assert d.weight_drift == pytest.approx(0.0, abs=1e-9), (
            f"{t} drift {d.weight_drift} should be ~0 after basis correction"
        )
        # Persisted target weight (executor sizes against this) is UNCHANGED.
        assert d.current_weight == pytest.approx((1.0 - cash_reserve) / n)


def test_raw_bias_would_trip_without_fix():
    """Control: the SAME book with cash_fraction unset (raw diff) DOES produce
    spurious sell_trims — proving the test book genuinely exercises the bug and
    the fix is what suppresses them."""
    n = 8
    cash_reserve = 0.10
    target, live, universe, actual = _fully_invested_book(n, cash_reserve)

    decisions = evaluate_target_vs_live(
        target_portfolio=target,
        live_positions=live,
        universe=universe,
        confirmation_days=3,
        max_positions=30,
        actual_weights=actual,
        drift_threshold=0.002,
        # cash_fraction omitted → raw apples-to-oranges diff (the old behavior)
    )
    trims = [t for t, d in decisions.items() if d.action == "sell_trim"]
    assert trims, "expected the unfixed raw diff to emit phantom sell_trims"


@pytest.mark.parametrize("cash_reserve", [0.025, 0.10])
def test_genuine_overweight_still_trims_with_cash_reserve(cash_reserve):
    """A position that genuinely drifted UP (beyond the cash-reserve basis gap)
    must still trip sell_trim even with the cash_fraction correction applied."""
    n = 8
    target, live, universe, actual = _fully_invested_book(n, cash_reserve)

    # Make T00 genuinely overweight: bump its actual share well above its
    # grossed-up target. Grossed-up target = (1-cash)/n / (1-cash) = 1/n.
    grossed_up = 1.0 / n
    actual["T00"] = grossed_up + 0.05        # +5pp genuine overweight

    decisions = evaluate_target_vs_live(
        target_portfolio=target,
        live_positions=live,
        universe=universe,
        confirmation_days=3,
        max_positions=30,
        actual_weights=actual,
        drift_threshold=0.02,
        cash_fraction=cash_reserve,
    )

    assert decisions["T00"].action == "sell_trim"
    assert decisions["T00"].weight_drift == pytest.approx(0.05, abs=1e-9)
    # All other names remain holds (no phantom trims).
    for t, d in decisions.items():
        if t == "T00":
            continue
        assert d.action == "hold", f"{t} should hold, got {d.action}"


@pytest.mark.parametrize("cash_reserve", [0.025, 0.10])
def test_genuine_underweight_still_buy_adds_with_cash_reserve(cash_reserve):
    """A position that genuinely drifted DOWN must still trip buy_add even with
    the cash_fraction correction applied."""
    n = 8
    target, live, universe, actual = _fully_invested_book(n, cash_reserve)

    grossed_up = 1.0 / n
    actual["T00"] = grossed_up - 0.05        # -5pp genuine underweight

    decisions = evaluate_target_vs_live(
        target_portfolio=target,
        live_positions=live,
        universe=universe,
        confirmation_days=3,
        max_positions=30,
        actual_weights=actual,
        drift_threshold=0.02,
        cash_fraction=cash_reserve,
        # supply funding so the buy_add isn't demoted by the cash gate
        account_value=100000.0,
        buying_power=100000.0,
    )

    assert decisions["T00"].action == "buy_add"
    assert decisions["T00"].weight_drift == pytest.approx(-0.05, abs=1e-9)


def test_cash_fraction_none_is_noop():
    """cash_fraction=None (default) reproduces the exact raw actual−target diff —
    backward compatible with every existing caller."""
    target = {"AAPL": 0.05}
    live = {"AAPL"}
    universe = {"AAPL": _history(20, 20, 20)}

    d_none = evaluate_target_vs_live(
        target_portfolio=target, live_positions=live, universe=universe,
        confirmation_days=3, max_positions=30,
        actual_weights={"AAPL": 0.09}, drift_threshold=0.02,
        cash_fraction=None,
    )
    d_zero = evaluate_target_vs_live(
        target_portfolio=target, live_positions=live, universe=universe,
        confirmation_days=3, max_positions=30,
        actual_weights={"AAPL": 0.09}, drift_threshold=0.02,
        cash_fraction=0.0,
    )
    assert d_none["AAPL"].action == "sell_trim"
    assert d_none["AAPL"].weight_drift == pytest.approx(0.09 - 0.05)
    # 0.0 and None behave identically (no rescale).
    assert d_zero["AAPL"].action == d_none["AAPL"].action
    assert d_zero["AAPL"].weight_drift == pytest.approx(d_none["AAPL"].weight_drift)


def test_cash_fraction_out_of_range_falls_back_to_no_rescale():
    """A defensive guard: an out-of-range cash_fraction (>=1 or <0 or NaN) must
    not divide-by-zero or invert the basis — it falls back to no rescale."""
    target = {"AAPL": 0.05}
    live = {"AAPL"}
    universe = {"AAPL": _history(20, 20, 20)}

    for bad in (1.0, 1.5, -0.1, float("nan")):
        d = evaluate_target_vs_live(
            target_portfolio=target, live_positions=live, universe=universe,
            confirmation_days=3, max_positions=30,
            actual_weights={"AAPL": 0.09}, drift_threshold=0.02,
            cash_fraction=bad,
        )
        # No rescale → raw diff 0.04 → sell_trim, no crash.
        assert d["AAPL"].action == "sell_trim"
        assert d["AAPL"].weight_drift == pytest.approx(0.04)
