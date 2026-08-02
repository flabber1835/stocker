"""The crash brake — a rare, coarse, book-level exposure cut.

It exists because the trailing stop cannot see the drawdown that actually hurts a
concentrated momentum book: twenty-five correlated names falling together, none
yet 30% off its own peak. By the time individual stops fire the damage is done.

Almost every test here is about the brake NOT firing. That is the design: a
control that halves the book must be wrong in the safe direction, and the two
conditions exist to make it rare rather than to make it sensitive. The one thing
worse than missing a crash is de-risking on a data gap every time the benchmark
feed hiccups.
"""
from __future__ import annotations

import pytest

from stock_strategy_shared.crash_brake import (CrashState, breadth_above_sma,
                                               evaluate_crash_state,
                                               market_window_return,
                                               scale_weights, target_exposure)


def _falling(n=200, start=100.0, daily=-0.004):
    px, out = start, []
    for _ in range(n):
        out.append(px)
        px *= 1 + daily
    return out


def _rising(n=200, start=100.0, daily=0.002):
    return _falling(n, start, daily)


def _universe(n_names=200, share_below=0.8, length=200):
    """A universe where `share_below` of names sit under their own SMA."""
    out = {}
    n_below = int(n_names * share_below)
    for i in range(n_names):
        out[f"T{i:03d}"] = _falling(length) if i < n_below else _rising(length)
    return out


def _call(**over):
    kw = dict(
        benchmark_closes=_falling(200),
        closes_by_ticker=_universe(),
        market_return_window_sessions=20,
        market_return_threshold=-0.06,
        breadth_sma_sessions=100,
        breadth_threshold=0.42,
    )
    kw.update(over)
    return evaluate_crash_state(**kw)


# ── the inputs ────────────────────────────────────────────────────────────────

class TestMarketWindowReturn:
    def test_it_measures_the_window_not_the_whole_series(self):
        closes = [100.0] * 180 + [100.0 * (1 - 0.001 * i) for i in range(1, 21)]
        r = market_window_return(closes, 20)
        assert r == pytest.approx(closes[-1] / closes[-21] - 1.0)

    def test_short_history_is_unknown_not_zero(self):
        """Zero would read as 'measured, market flat' and silently disarm the
        brake's first condition."""
        assert market_window_return([100.0] * 5, 20) is None

    def test_nonpositive_or_nan_prices_are_unknown(self):
        assert market_window_return([0.0] + [100.0] * 25, 20) is not None  # old zero is outside the window
        assert market_window_return([100.0] * 25 + [0.0], 20) is None
        assert market_window_return([float("nan")] * 25, 20) is None


class TestBreadth:
    def test_it_counts_names_above_their_own_average(self):
        share, n = breadth_above_sma(_universe(200, share_below=0.75), 100, min_names=50)
        assert n == 200
        assert share == pytest.approx(0.25, abs=0.02)

    def test_a_name_without_enough_history_is_excluded_from_BOTH_sides(self):
        """Counting it as 'below' would collapse breadth every time the universe
        refreshes — an ingestion event, not a market event."""
        uni = _universe(100, share_below=0.0)
        uni.update({f"NEW{i}": [100.0] * 5 for i in range(50)})
        share, n = breadth_above_sma(uni, 100, min_names=50)
        assert n == 100 and share == pytest.approx(1.0)

    def test_too_few_names_reads_as_unavailable(self):
        share, n = breadth_above_sma(_universe(10), 100, min_names=50)
        assert share is None and n == 10


# ── the switch ────────────────────────────────────────────────────────────────

class TestBothConditionsRequired:
    def test_engages_only_when_market_AND_breadth_are_bad(self):
        s = _call()
        assert s.engaged, s.reason
        assert s.market_return < -0.06 and s.breadth < 0.42

    def test_a_falling_index_with_healthy_breadth_does_NOT_engage(self):
        """Routinely a handful of mega-caps. Halving the book for that would make
        the brake a market-timing overlay nobody configured."""
        s = _call(closes_by_ticker=_universe(share_below=0.0))
        assert not s.engaged
        assert "breadth" in s.reason

    def test_thin_breadth_in_a_rising_market_does_NOT_engage(self):
        """A normal feature of a narrow bull market."""
        s = _call(benchmark_closes=_rising(200))
        assert not s.engaged
        assert "market" in s.reason


class TestFailSafeOnMissingData:
    """Deliberately the OPPOSITE stance to the falling-knife veto's fail-closed
    load. Refusing to buy on missing data costs an opportunity; selling half the
    book on missing data is an unforced loss."""

    def test_short_benchmark_history_holds_exposure(self):
        s = _call(benchmark_closes=[100.0] * 5)
        assert not s.engaged and "cannot evaluate" in s.reason

    def test_unavailable_breadth_holds_exposure(self):
        s = _call(closes_by_ticker=_universe(n_names=5))
        assert not s.engaged and "breadth unavailable" in s.reason

    def test_an_empty_universe_holds_exposure(self):
        s = _call(closes_by_ticker={})
        assert not s.engaged

    def test_disabled_is_inert_even_in_an_obvious_crash(self):
        s = _call(enabled=False)
        assert not s.engaged and s.market_return is None


class TestReporting:
    def test_every_input_is_reported_even_when_disengaged(self):
        """A risk control that says only 'engaged' cannot be argued with after
        the fact."""
        s = _call(benchmark_closes=_rising(200))
        assert s.market_return is not None and s.breadth is not None
        assert s.n_breadth_names > 0 and s.reason


# ── applying it ───────────────────────────────────────────────────────────────

class TestExposure:
    def test_engaged_uses_the_stressed_exposure(self):
        assert target_exposure(_call(), 1.0, 0.5) == 0.5

    def test_disengaged_uses_the_normal_exposure(self):
        assert target_exposure(_call(benchmark_closes=_rising(200)), 1.0, 0.5) == 1.0

    def test_scaling_preserves_relative_weights_exactly(self):
        """THE property. Re-deriving weights on restore would turn the brake into
        a rebalancing trigger — the rotation a stop-only policy exists to avoid.
        A 6% position comes back as 6%, not as whatever today's target says."""
        w = {"A": 0.06, "B": 0.03, "C": 0.01}
        half = scale_weights(w, 0.5)
        assert half == {"A": 0.03, "B": 0.015, "C": 0.005}
        assert scale_weights(half, 2.0) == pytest.approx(w)
        ratios = [half[k] / w[k] for k in w]
        assert len(set(round(r, 12) for r in ratios)) == 1

    def test_composition_is_untouched(self):
        w = {"A": 0.06, "B": 0.03}
        assert set(scale_weights(w, 0.5)) == set(w)

    def test_a_nonsense_exposure_is_ignored_rather_than_applied(self):
        w = {"A": 0.06}
        assert scale_weights(w, -1.0) == w
        assert scale_weights(w, None) == w


def test_the_state_names_its_own_exposure_key():
    assert _call().equity_exposure_key == "stressed"
    assert _call(benchmark_closes=_rising(200)).equity_exposure_key == "normal"


class TestExposureMoves:
    """Turning an exposure change into intents. The brake must be SILENT on the
    ~99% of days it is disengaged, and must preserve relative weights so that
    restoring cannot quietly re-rank the book."""

    W = {"A": 0.06, "B": 0.04, "C": 0.02}

    def test_no_change_produces_no_moves(self):
        from stock_strategy_shared.crash_brake import plan_exposure_moves
        assert plan_exposure_moves(self.W, 1.0, prev_exposure=1.0) == []

    def test_engaging_sells_every_position_by_the_same_factor(self):
        from stock_strategy_shared.crash_brake import plan_exposure_moves
        moves = plan_exposure_moves(self.W, 0.5, prev_exposure=1.0)
        assert {m["action"] for m in moves} == {"risk_reduce"}
        ratios = {m["ticker"]: m["target_weight"] / m["current_weight"] for m in moves}
        assert len(set(round(r, 12) for r in ratios.values())) == 1

    def test_restoring_returns_each_name_to_its_ORIGINAL_share(self):
        """The property that makes this a risk overlay rather than a rebalance:
        a name that was 6% comes back as 6%, not as whatever today's target says."""
        from stock_strategy_shared.crash_brake import plan_exposure_moves
        half = {m["ticker"]: m["target_weight"]
                for m in plan_exposure_moves(self.W, 0.5, prev_exposure=1.0)}
        back = plan_exposure_moves(half, 1.0, prev_exposure=0.5)
        assert {m["action"] for m in back} == {"risk_restore"}
        for m in back:
            assert m["target_weight"] == pytest.approx(self.W[m["ticker"]], abs=1e-9)

    def test_moves_too_small_to_pay_for_themselves_are_dropped(self):
        """A 0.1% nudge across 25 names is 25 orders of pure commission."""
        from stock_strategy_shared.crash_brake import plan_exposure_moves
        moves = plan_exposure_moves({"A": 0.01}, 0.99, prev_exposure=1.0)
        assert moves == []

    def test_an_empty_book_produces_nothing(self):
        from stock_strategy_shared.crash_brake import plan_exposure_moves
        assert plan_exposure_moves({}, 0.5) == []
