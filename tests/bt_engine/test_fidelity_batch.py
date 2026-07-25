"""The eleven-defect fidelity batch.

Every one of these had the same shape: the simulator SUBSTITUTED something
plausible where it could not model the real thing, and a number came out. A
number is indistinguishable from an answer, which is why none of them were
visible for months.

So each test below asserts the SUBSTITUTION is gone — not merely that the new
code path exists.
"""
import numpy as np
import pandas as pd
import pytest

from app.sim import (
    DEFAULT_DELIST_RECOVERY_PCT,
    DELIST_GAP_DAYS,
    SimParams,
    TargetStatus,
    build_target,
    eligible_on,
    run_simulation,
)

from .test_sim import _cfg
from .test_plausibility import _rising


def _hold_all_cfg():
    """max_positions large enough to hold every fixture ticker, so a test that
    gaps one name is guaranteed to be gapping a HELD one. With the default cap
    of 3 out of 6 names the delist tests silently skipped."""
    # 0.5, not 1.0: the schema refuses a per-position cap above 50% when
    # max_positions > 1 (a cap that permits a single-name book).
    return _cfg(max_positions=6, max_position_weight=0.5)


def _run(prices, fnd, days, **over):
    kw = dict(start=days[60].date(), end=days[-1].date(), tx_cost_bps=10,
              fill_timing="next_open", rebalance_every=5)
    kw.update({k: v for k, v in over.items() if k != "listing_windows"})
    return run_simulation(prices, fnd, {}, over.get("cfg") or _cfg(),
                          SimParams(**{k: v for k, v in kw.items() if k != "cfg"}),
                          listing_windows=over.get("listing_windows"))


# ── item 3: no fill without a print ─────────────────────────────────────────

def test_a_trade_is_not_filled_when_the_security_has_no_print_that_day():
    """The fallback to last_px executed trades against a security with no market
    — buying at a frozen (usually lower) price and exiting positions that could
    not have been exited. Not conservative in either direction."""
    prices, fnd, days = _rising(n_days=520)
    # Blank one ticker entirely for the back half: a halt/delisting/vendor gap.
    gap_from = days[300]
    mask = (prices["ticker"] == "AAA") & (prices["date"] >= gap_from)
    prices.loc[mask, ["open", "close", "adjusted_close"]] = np.nan

    r = _run(prices, fnd, days)
    filled_after_gap = [t for t in r.trades
                        if t["ticker"] == "AAA" and pd.Timestamp(t["date"]) >= gap_from
                        and "delisted" not in (t.get("reason") or "")]
    assert not filled_after_gap, (
        f"filled {len(filled_after_gap)} AAA trade(s) on days with no price")


def test_unfilled_orders_are_reported_rather_than_silently_dropped():
    """A silent drop is its own substitution — the run looks like one where the
    strategy simply chose not to trade."""
    prices, fnd, days = _rising(n_days=520)
    mask = (prices["ticker"] == "AAA") & (prices["date"] >= days[300])
    prices.loc[mask, ["open", "close", "adjusted_close"]] = np.nan
    r = _run(prices, fnd, days)
    assert "unfilled_orders" in r.summary
    if r.summary["unfilled_orders"]:
        s = r.summary["unfilled_sample"][0]
        assert "no price" in s["reason"] and s["ticker"]


def test_a_phantom_fill_cannot_refresh_the_delisting_timer():
    """The compounding failure. The -96% fix made every fill stamp last_seen (a
    fill is proof of a print) — correct for real fills, but a phantom fill then
    reset the delist countdown, keeping a dead name alive indefinitely at a
    frozen price. With no-print-no-fill there is no phantom to stamp."""
    prices, fnd, days = _rising(n_days=520)
    mask = (prices["ticker"] == "AAA") & (prices["date"] >= days[300])
    prices.loc[mask, ["open", "close", "adjusted_close"]] = np.nan
    r = _run(prices, fnd, days)
    held_at_end = {p["ticker"] for p in r.positions
                   if p["date"] == r.positions[-1]["date"]} if r.positions else set()
    assert "AAA" not in held_at_end, (
        "a name with no prints for ~200 sessions was still held at the end")


# ── item 4: delisting recovery ──────────────────────────────────────────────

def test_delist_exit_books_the_configured_recovery_not_the_full_mark():
    prices, fnd, days = _rising(n_days=520)
    mask = (prices["ticker"] == "AAA") & (prices["date"] >= days[300])
    prices.loc[mask, ["open", "close", "adjusted_close"]] = np.nan

    full = _run(prices.copy(), fnd, days, delist_recovery_pct=1.0, cfg=_hold_all_cfg())
    hair = _run(prices.copy(), fnd, days, delist_recovery_pct=0.5, cfg=_hold_all_cfg())

    def _delist_prices(res):
        return [t["price"] for t in res.trades
                if "delisted" in (t.get("reason") or "")]
    fp, hp = _delist_prices(full), _delist_prices(hair)
    assert fp, "the gapped ticker was held but never delist-exited"
    assert hp and hp[0] == pytest.approx(fp[0] * 0.5, rel=1e-6)


def test_delist_exit_charges_transaction_cost():
    """It used to write tx_cost: 0.0 as a literal — a free liquidation."""
    prices, fnd, days = _rising(n_days=520)
    mask = (prices["ticker"] == "AAA") & (prices["date"] >= days[300])
    prices.loc[mask, ["open", "close", "adjusted_close"]] = np.nan
    r = _run(prices, fnd, days, cfg=_hold_all_cfg())
    delist = [t for t in r.trades if "delisted" in (t.get("reason") or "")]
    assert delist, "the gapped ticker was held but never delist-exited"
    assert delist[0]["tx_cost"] > 0


def test_the_default_recovery_is_a_haircut_and_is_reported():
    assert 0 < DEFAULT_DELIST_RECOVERY_PCT < 1
    prices, fnd, days = _rising(n_days=520)
    r = _run(prices, fnd, days)
    assert r.summary["delist_recovery_pct"] == DEFAULT_DELIST_RECOVERY_PCT


# ── item 5: sessions, not calendar days ─────────────────────────────────────

def test_delist_gap_is_measured_in_real_sessions():
    """`(D - last_seen).days > DELIST_GAP_DAYS * 2` was a calendar approximation
    landing nearer 10 sessions than 7, and drifting with holidays. The sim walks
    an explicit session list, so the exact count is available."""
    import inspect

    import app.sim as sim
    src = inspect.getsource(sim.run_simulation)
    assert "DELIST_GAP_DAYS * 2" not in src, "calendar approximation is back"
    assert "last_seen_i" in src and "day_index" in src


def test_a_name_absent_for_fewer_than_the_gap_is_not_delisted():
    """Boundary: the threshold must not fire early. A gap of exactly
    DELIST_GAP_DAYS sessions is NOT more than the gap."""
    prices, fnd, days = _rising(n_days=520)
    gap_start = 300
    mask = ((prices["ticker"] == "AAA")
            & (prices["date"] >= days[gap_start])
            & (prices["date"] < days[gap_start + DELIST_GAP_DAYS]))
    prices.loc[mask, ["open", "close", "adjusted_close"]] = np.nan
    r = _run(prices, fnd, days)
    delist = [t for t in r.trades
              if t["ticker"] == "AAA" and "delisted" in (t.get("reason") or "")]
    assert not delist, "delisted a name that resumed printing within the gap"


# ── item 9: explicit target status ──────────────────────────────────────────

def test_build_target_returns_a_status_not_just_truthiness():
    prices, fnd, days = _rising(n_days=520)
    day_prices = prices[prices["date"] <= days[400]]
    out = build_target(day_prices[day_prices["ticker"] != "SPY"],
                       fnd.drop(columns=["as_of_date"], errors="ignore"),
                       {}, _cfg(), "bull_calm",
                       {"backstop_pct": 0.25, "window_days": 21, "excess_pct": 0.15,
                        "beta_lookback": 120, "vol_scaling": True, "vol_anchor": 0.35,
                        "excess_min": 0.10, "excess_max": 0.30},
                       [100.0] * 300)
    assert len(out) == 3
    assert out[2] in TargetStatus.ALL


def test_degraded_and_failed_hold_the_book_but_success_empty_does_not():
    """The whole point of the distinction: both used to be an empty dict."""
    assert TargetStatus.DEGRADED in TargetStatus.HOLD
    assert TargetStatus.FAILED in TargetStatus.HOLD
    assert TargetStatus.SUCCESS_EMPTY_TARGET not in TargetStatus.HOLD, (
        "a deliberate risk-off target must be obeyed, not overridden")
    assert TargetStatus.SUCCESS_WITH_TARGET not in TargetStatus.HOLD


def test_status_counts_are_reported_so_a_degraded_run_is_visible():
    prices, fnd, days = _rising(n_days=520)
    r = _run(prices, fnd, days)
    counts = r.summary["target_status_counts"]
    assert counts and all(k in TargetStatus.ALL for k in counts)
    assert sum(counts.values()) == r.summary["n_rebalances"]


# ── items 10/11: counters that mean what they say ───────────────────────────

def test_n_rebalances_counts_evaluations_not_just_days_that_traded():
    """It used to be len(turnover_samples), appended only when trades existed —
    so it silently meant 'rebalance dates that produced trades'."""
    prices, fnd, days = _rising(n_days=520)
    r = _run(prices, fnd, days, rebalance_every=5)
    n_eval = r.summary["n_rebalances"]
    expected = len([i for i in range(len(days) - 60) if i % 5 == 0])
    assert n_eval == pytest.approx(expected, abs=2)
    assert n_eval >= r.summary["n_rebalances_with_trades"]


def test_turnover_is_measured_from_realized_fills():
    """It was summed from decision-time intended notional at last_px, BEFORE
    fills, so it could never reconcile with the costs that hit equity — nor with
    orders that never filled at all."""
    import inspect

    import app.sim as sim
    src = inspect.getsource(sim.run_simulation)
    assert "filled_notional_today" in src
    # the old decision-time computation is gone
    assert 'notional = sum((t.get("notional")' not in src


def test_zero_turnover_cycles_are_counted_in_the_average():
    """Averaging only over cycles that traded overstates turnover for a strategy
    that mostly sits still — precisely the comparison the evaluator makes."""
    prices, fnd, days = _rising(n_days=520)
    r = _run(prices, fnd, days)
    s = r.summary
    if s["n_rebalances"] and s["total_turnover"]:
        # Both fields are rounded to 4dp on the way out, so compare at that
        # resolution — the RELATION is the assertion, not the last digit.
        assert s["avg_turnover"] == pytest.approx(
            s["total_turnover"] / s["n_rebalances"], abs=1e-4)


# ── item 7: point-in-time eligibility ───────────────────────────────────────

from datetime import date as _date  # noqa: E402


@pytest.mark.parametrize("as_of,window,expected", [
    (_date(2020, 6, 1), None, True),                                   # no data
    (_date(2020, 6, 1), (None, None), True),                           # both unknown
    (_date(2020, 6, 1), (_date(2019, 1, 1), None), True),              # still trading
    (_date(2020, 6, 1), (_date(2021, 1, 1), None), False),             # not listed yet
    (_date(2020, 6, 1), (_date(2019, 1, 1), _date(2019, 12, 1)), False),  # already gone
    (_date(2020, 6, 1), (_date(2019, 1, 1), _date(2020, 6, 1)), True),    # last day inclusive
    (_date(2020, 6, 1), (_date(2020, 6, 1), None), True),                 # first day inclusive
])
def test_eligibility_windows(as_of, window, expected):
    assert eligible_on(as_of, window) is expected


def test_an_unknown_bound_is_not_a_constraint():
    """A missing first_price_date must not erase a ticker from all of history —
    the failure mode that would quietly shrink the universe on a partial corpus."""
    assert eligible_on(_date(1990, 1, 1), (None, _date(2020, 1, 1))) is True
    assert eligible_on(_date(2099, 1, 1), (_date(2020, 1, 1), None)) is True


def test_a_ticker_outside_its_listing_window_is_never_selected():
    prices, fnd, days = _rising(n_days=520)
    # AAA has prices throughout, but claims it did not list until after the run.
    windows = {"AAA": (days[-1].date(), None)}
    r = _run(prices, fnd, days, listing_windows=windows)
    assert not any(t["ticker"] == "AAA" for t in r.trades), (
        "traded a ticker that was not listed on any simulated date")


def test_absent_listing_windows_change_nothing():
    """A pre-migration corpus must behave exactly as before, not silently lose
    its universe."""
    prices, fnd, days = _rising(n_days=520)
    a = _run(prices.copy(), fnd.copy(), days, listing_windows=None)
    b = _run(prices.copy(), fnd.copy(), days, listing_windows={})
    assert a.summary["total_return"] == b.summary["total_return"]
