"""Falsifiers for the SPY market-regime sensor.

The two predicates are `spy_r20 <= -0.01` and `vol5/vol20 - 1 >= 0.04`, and both
are threshold comparisons on values this module produces. So the tests are
written AT the thresholds and one step across them, and the thresholds
themselves are read from the FROZEN RULE — never restated here, because a test
carrying its own copy of a number proves only that the copy matches itself.

What this suite cannot do, and does not pretend to: compare against a historical
SPY series. None exists in any handoff artefact. That is a property of what was
preserved, not a gap in the logic — certification §5b item 7. The forward-chain
proof is NAS-bound.
"""
from __future__ import annotations

import math
import os
from pathlib import Path

import pytest

from sentinel.controller import frozen_rule
from sentinel.regime.spy import dated_spy_regime
from sentinel.regime import (
    MIN_CLOSES,
    R20_LOOKBACK_SESSIONS,
    STDDEV_DDOF,
    VOL_FAST_WINDOW,
    VOL_SLOW_WINDOW,
    daily_returns,
    regime_observation_fields,
    regime_predicates,
    rolling_std,
    spy_regime,
    total_return,
    volatility_acceleration,
)


REPO = Path(os.environ.get("SENTINEL_REPO_ROOT") or
            Path(__file__).resolve().parents[2])


@pytest.fixture(scope="module")
def cfg():
    return frozen_rule.load()


@pytest.fixture(scope="module")
def max_spy_r20(cfg):
    return cfg.fast_entry["confirmation_or"][0]["max_spy_r20"]


@pytest.fixture(scope="module")
def min_vol_accel(cfg):
    return cfg.fast_entry["min_spy_vol5_over_vol20_minus_1"]


def closes_for_r20(target, n=MIN_CLOSES, base=100.0):
    """A series whose final 20-session total return is exactly `target`."""
    out = [base] * n
    out[-1] = base * (1.0 + target)
    return out


class TestDatedProductionInput:
    @staticmethod
    def _tail():
        return [f"2026-07-{day:02d}" for day in range(1, MIN_CLOSES + 1)]

    def test_exact_expected_tail_ending_on_decision_is_available(self):
        sessions = self._tail()
        result = dated_spy_regime(
            sessions, [100.0 + i for i in range(MIN_CLOSES)],
            decision_session=sessions[-1], expected_sessions=sessions)
        assert math.isfinite(result.spy_r20)
        assert math.isfinite(result.spy_vol_ratio)

    @pytest.mark.parametrize("defect", ["missing_newest", "missing_interior",
                                         "duplicate", "out_of_order"])
    def test_invalid_chronology_is_unavailable(self, defect):
        expected = self._tail()
        sessions = list(expected)
        closes = [100.0 + i for i in range(MIN_CLOSES)]
        if defect == "missing_newest":
            sessions[-1] = "2026-07-31"
        elif defect == "missing_interior":
            sessions[10] = "2026-07-30"
        elif defect == "duplicate":
            sessions[10] = sessions[9]
        else:
            sessions[9], sessions[10] = sessions[10], sessions[9]
        result = dated_spy_regime(
            sessions, closes, decision_session=expected[-1],
            expected_sessions=expected)
        assert math.isnan(result.spy_r20)
        assert math.isnan(result.spy_vol_ratio)


class TestTheThresholdsComeFromTheFrozenRule:
    def test_the_two_numbers_are_the_frozen_ones(self, max_spy_r20, min_vol_accel):
        assert max_spy_r20 == -0.01
        assert min_vol_accel == 0.04

    def test_the_module_does_not_restate_either_threshold(self):
        """The values live in the frozen JSON; this module produces inputs to
        them. A second copy is a second thing to drift."""
        import sentinel.regime.spy as mod

        src = open(mod.__file__).read()
        code = "\n".join(l.split("#")[0] for l in src.splitlines()
                         if not l.strip().startswith("#"))
        # Strip the docstring, which legitimately quotes the rule for readers.
        body = code.split('"""')[-1]
        assert "-0.01" not in body
        assert "0.04" not in body


class TestSpyR20Boundary:
    def test_r20_EXACTLY_at_the_threshold_confirms(self, cfg, max_spy_r20):
        """INCLUSIVE: `spy_r20 <= -0.01`, tested at the exact value.

        Constructing it from prices does NOT reach the boundary: 99.0/100.0 - 1
        is -0.010000000000000009, a hair below. A test built that way passes
        against `<` as well as `<=` and so proves nothing about inclusivity.
        """
        from sentinel.regime import SpyRegime

        exact = SpyRegime(max_spy_r20, float("nan"))
        assert regime_predicates(exact, cfg)["spy_r20_confirms"] is True

    def test_r20_one_step_ABOVE_the_threshold_does_not_confirm(self, cfg,
                                                               max_spy_r20):
        from sentinel.regime import SpyRegime

        above = SpyRegime(math.nextafter(max_spy_r20, 0.0), float("nan"))
        assert regime_predicates(above, cfg)["spy_r20_confirms"] is False

    def test_r20_one_step_BELOW_the_threshold_confirms(self, cfg, max_spy_r20):
        from sentinel.regime import SpyRegime

        below = SpyRegime(math.nextafter(max_spy_r20, -1.0), float("nan"))
        assert regime_predicates(below, cfg)["spy_r20_confirms"] is True

    def test_a_constructed_series_at_the_threshold_confirms(self, cfg,
                                                            max_spy_r20):
        """The series-level half. Floating point puts it just below the
        boundary, which is the realistic case and must still confirm."""
        r = spy_regime(closes_for_r20(max_spy_r20))
        assert r.spy_r20 == pytest.approx(max_spy_r20, abs=1e-12)
        assert regime_predicates(r, cfg)["spy_r20_confirms"] is True

    def test_r20_just_ABOVE_the_threshold_does_not_confirm(self, cfg):
        r = spy_regime(closes_for_r20(-0.0099))
        assert regime_predicates(r, cfg)["spy_r20_confirms"] is False

    def test_r20_just_BELOW_the_threshold_confirms(self, cfg):
        r = spy_regime(closes_for_r20(-0.0101))
        assert regime_predicates(r, cfg)["spy_r20_confirms"] is True

    def test_a_flat_market_gives_exactly_zero(self):
        assert spy_regime([100.0] * MIN_CLOSES).spy_r20 == 0.0


class TestTheR20WindowLength:
    def test_the_lookback_is_a_GAP_of_20_spanning_21_observations(self):
        # closes[-1] / closes[-21] - 1. Only the first and last matter.
        closes = [1.0] + [999.0] * (R20_LOOKBACK_SESSIONS - 1) + [2.0]
        assert len(closes) == R20_LOOKBACK_SESSIONS + 1
        assert total_return(closes) == pytest.approx(1.0)

    def test_20_closes_is_NOT_enough(self):
        assert math.isnan(total_return([100.0] * R20_LOOKBACK_SESSIONS))

    def test_21_closes_IS_enough(self):
        assert not math.isnan(total_return([100.0] * (R20_LOOKBACK_SESSIONS + 1)))

    def test_off_by_one_reads_a_DIFFERENT_bar(self):
        # A ramp: every bar differs, so a window slip is visible.
        closes = [100.0 + i for i in range(R20_LOOKBACK_SESSIONS + 2)]
        correct = total_return(closes, R20_LOOKBACK_SESSIONS)
        slipped = total_return(closes, R20_LOOKBACK_SESSIONS - 1)
        assert correct != slipped


class TestVolatilityAccelerationBoundary:
    @staticmethod
    def _returns_with_ratio(target_ratio):
        """20 returns whose last-5 sample std over all-20 sample std is
        `target_ratio`. Built by scaling the fast tail of a fixed pattern."""
        base = [0.01, -0.01] * 10                      # 20 returns, |r| = 0.01
        lo, hi = 0.0, 100.0
        for _ in range(200):                            # bisect the tail scale
            mid = (lo + hi) / 2
            trial = base[:-VOL_FAST_WINDOW] + [v * mid for v in base[-VOL_FAST_WINDOW:]]
            got = rolling_std(trial, VOL_FAST_WINDOW) / rolling_std(trial, VOL_SLOW_WINDOW)
            if got < target_ratio:
                lo = mid
            else:
                hi = mid
        mid = (lo + hi) / 2
        return base[:-VOL_FAST_WINDOW] + [v * mid for v in base[-VOL_FAST_WINDOW:]]

    def test_expansion_EXACTLY_at_the_threshold_fires(self, cfg, min_vol_accel):
        """INCLUSIVE: `>= 0.04`.

        Tested at the VALUE, not through a constructed series. Landing a
        rolling-std ratio on exactly 0.04 needs a bisection that converges from
        one side, which tests the search rather than the boundary — and a
        fixture that lands a hair below turns an inclusive threshold into an
        exclusive one without anyone noticing.
        """
        from sentinel.regime import SpyRegime

        exact = SpyRegime(float("nan"), min_vol_accel)
        assert regime_predicates(exact, cfg)["vol_acceleration"] is True

    def test_expansion_one_step_BELOW_the_threshold_does_not_fire(self, cfg,
                                                                  min_vol_accel):
        from sentinel.regime import SpyRegime

        below = SpyRegime(float("nan"), math.nextafter(min_vol_accel, 0.0))
        assert regime_predicates(below, cfg)["vol_acceleration"] is False

    def test_expansion_one_step_ABOVE_the_threshold_fires(self, cfg,
                                                          min_vol_accel):
        from sentinel.regime import SpyRegime

        above = SpyRegime(float("nan"), math.nextafter(min_vol_accel, 1.0))
        assert regime_predicates(above, cfg)["vol_acceleration"] is True

    def test_a_CONSTRUCTED_expansion_crosses_the_threshold_as_expected(self, cfg):
        """The series-level half: a real volatility expansion fires, a mild one
        does not, and the crossing sits where the frozen threshold puts it."""
        from sentinel.regime import SpyRegime

        calm = volatility_acceleration(self._returns_with_ratio(1.02))
        violent = volatility_acceleration(self._returns_with_ratio(1.20))
        assert calm < 0.04 < violent
        assert regime_predicates(SpyRegime(float("nan"), calm),
                                 cfg)["vol_acceleration"] is False
        assert regime_predicates(SpyRegime(float("nan"), violent),
                                 cfg)["vol_acceleration"] is True

    def test_the_ratio_rises_MONOTONICALLY_with_the_fast_window_scale(self):
        """Direction matters: an inverted ratio would still produce plausible
        numbers and would fire on calming markets."""
        seen = [volatility_acceleration(self._returns_with_ratio(r))
                for r in (1.0, 1.1, 1.3, 2.0)]
        assert seen == sorted(seen)
        assert seen[0] < seen[-1]


class TestTheStdDevConvention:
    def test_ddof_is_ONE_sample_not_population(self):
        assert STDDEV_DDOF == 1
        # [0,2]: sample std = sqrt(2) = 1.414..., population std = 1.0
        assert rolling_std([0.0, 2.0], 2, ddof=1) == pytest.approx(math.sqrt(2))
        assert rolling_std([0.0, 2.0], 2, ddof=0) == pytest.approx(1.0)

    def test_matches_pandas_rolling_std_ddof_1(self):
        pd = pytest.importorskip("pandas")
        rets = [0.01, -0.02, 0.005, 0.03, -0.015, 0.002, 0.04, -0.01]
        for w in (3, 5):
            want = pd.Series(rets).rolling(w).std(ddof=1).iloc[-1]
            assert rolling_std(rets, w) == pytest.approx(float(want), rel=1e-12)

    def test_population_ddof_would_BIAS_the_ratio_through_the_threshold(self):
        """Not a rounding difference. ddof=0 shrinks the 5-window by
        sqrt(4/5) and the 20-window by sqrt(19/20); the factors do NOT cancel,
        and the residual is ~4% — the size of the whole threshold."""
        rets = [0.01, -0.01] * 10
        sample = (rolling_std(rets, 5, ddof=1) / rolling_std(rets, 20, ddof=1)) - 1
        population = (rolling_std(rets, 5, ddof=0) / rolling_std(rets, 20, ddof=0)) - 1
        assert abs(population - sample) > 0.03

    def test_the_std_is_of_RETURNS_not_PRICES(self):
        """A std of prices carries the price level and is not a volatility."""
        closes = [100.0 * (1.01 ** i) for i in range(MIN_CLOSES)]
        rets = daily_returns(closes)
        assert rolling_std(rets, 5) == pytest.approx(0.0, abs=1e-12)
        assert rolling_std(closes, 5) > 1.0


class TestInsufficientHistory:
    def test_fewer_than_21_closes_gives_BOTH_fields_unavailable(self):
        r = spy_regime([100.0] * (MIN_CLOSES - 1))
        assert math.isnan(r.spy_r20)
        assert math.isnan(r.spy_vol_ratio)

    def test_exactly_21_closes_gives_both_fields(self):
        closes = [100.0 + i for i in range(MIN_CLOSES)]
        r = spy_regime(closes)
        assert not math.isnan(r.spy_r20)
        assert not math.isnan(r.spy_vol_ratio)

    def test_an_empty_series_does_not_raise(self):
        r = spy_regime([])
        assert math.isnan(r.spy_r20) and math.isnan(r.spy_vol_ratio)

    def test_min_closes_is_the_slow_window_plus_one(self):
        assert MIN_CLOSES == VOL_SLOW_WINDOW + 1


class TestTheWindowLengthsArePinned:
    """The frozen rule names 5 and 20. A helper that scales "the last
    VOL_FAST_WINDOW returns" adapts to a wrong constant and is therefore blind
    to it — these pin the numbers against the spec instead of against the code.
    """

    def test_the_windows_are_5_and_20(self):
        assert (VOL_FAST_WINDOW, VOL_SLOW_WINDOW) == (5, 20)

    def test_the_fast_window_is_EXACTLY_the_last_five_returns(self):
        """Perturb the SIXTH-FROM-LAST return.

        A 5-window must not see it; a 6-window must. That pins the boundary
        from both sides — a window of 4 would also ignore it, so the companion
        assertion below checks the fifth-from-last IS seen.
        """
        tail = [0.05, -0.05, 0.05, -0.05, 0.05]
        base = [0.001] * 15 + tail
        perturbed = list(base)
        perturbed[-6] = 0.09                       # the boundary element

        assert rolling_std(base, 5) == pytest.approx(rolling_std(perturbed, 5)), \
            "a 5-window must NOT see the sixth-from-last return"
        assert rolling_std(base, 6) != pytest.approx(rolling_std(perturbed, 6)), \
            "a 6-window MUST see it"

    def test_the_fifth_from_last_return_IS_inside_the_fast_window(self):
        base = [0.001] * 15 + [0.05, -0.05, 0.05, -0.05, 0.05]
        perturbed = list(base)
        perturbed[-5] = 0.09
        assert rolling_std(base, 5) != pytest.approx(rolling_std(perturbed, 5))

    def test_the_fast_window_matches_pandas_at_window_5_specifically(self):
        pd = pytest.importorskip("pandas")
        rets = [0.01, -0.02, 0.005, 0.03, -0.015, 0.002, 0.04, -0.01,
                0.006, -0.004, 0.011, -0.022, 0.008, 0.017, -0.009,
                0.003, -0.031, 0.014, 0.021, -0.006]
        assert rolling_std(rets, VOL_FAST_WINDOW) == pytest.approx(
            float(pd.Series(rets).rolling(5).std(ddof=1).iloc[-1]), rel=1e-12)
        assert rolling_std(rets, VOL_SLOW_WINDOW) == pytest.approx(
            float(pd.Series(rets).rolling(20).std(ddof=1).iloc[-1]), rel=1e-12)

    def test_a_wrong_fast_window_changes_the_acceleration(self):
        rets = [0.001] * 15 + [0.05, -0.05, 0.05, -0.05, 0.05]
        five = rolling_std(rets, 5) / rolling_std(rets, 20) - 1
        four = rolling_std(rets, 4) / rolling_std(rets, 20) - 1
        assert five != pytest.approx(four)


class TestDegenerateDenominator:
    def test_a_perfectly_flat_window_is_UNAVAILABLE_not_zero(self):
        # vol20 == 0. The reference divides in numpy and gets inf/NaN, which its
        # isfinite guard rejects; NaN reaches the same outcome without raising.
        assert math.isnan(volatility_acceleration([0.0] * VOL_SLOW_WINDOW))

    def test_it_does_not_raise_ZeroDivisionError(self):
        volatility_acceleration([0.0] * VOL_SLOW_WINDOW)

    def test_a_flat_price_series_yields_an_unavailable_ratio(self):
        r = spy_regime([100.0] * MIN_CLOSES)
        assert r.spy_r20 == 0.0
        assert math.isnan(r.spy_vol_ratio)


class TestUnavailableInputs:
    @pytest.mark.parametrize("bad", [None, float("nan"), float("inf"),
                                     float("-inf")])
    def test_a_bad_close_anywhere_in_the_window_is_unavailable(self, bad):
        closes = [100.0] * MIN_CLOSES
        closes[5] = bad
        assert math.isnan(spy_regime(closes).spy_vol_ratio)

    @pytest.mark.parametrize("bad", [None, float("nan"), float("inf")])
    def test_a_bad_ENDPOINT_makes_r20_unavailable(self, bad):
        closes = [100.0] * MIN_CLOSES
        closes[-1] = bad
        assert math.isnan(total_return(closes))
        closes = [100.0] * MIN_CLOSES
        closes[0] = bad
        assert math.isnan(total_return(closes))

    def test_a_NON_POSITIVE_close_is_unavailable_not_a_minus_100pct_return(self):
        closes = [100.0] * MIN_CLOSES
        closes[0] = 0.0
        assert math.isnan(total_return(closes))
        assert math.isnan(total_return([-1.0] + [100.0] * R20_LOOKBACK_SESSIONS))

    def test_rolling_std_returns_NaN_rather_than_RAISING_on_a_None(self):
        """`min_periods == window`, enforced explicitly rather than left to NaN
        arithmetic. NaN propagates through the mean and would give NaN anyway —
        a None does not, it raises TypeError. `rolling_std` is public, so the
        guard has to hold for what a caller can actually pass it."""
        assert math.isnan(rolling_std([0.01, None, 0.02], 3))
        assert math.isnan(rolling_std([0.01, 0.02, None], 3))
        assert math.isnan(rolling_std([None] * 5, 5))

    def test_volatility_acceleration_survives_a_None_in_the_window(self):
        rets = [0.01] * 19 + [None]
        assert math.isnan(volatility_acceleration(rets))

    def test_a_bad_close_kills_the_returns_on_BOTH_sides(self):
        # Dropping only one would splice the series and hand the volatility
        # window a return computed across a gap.
        rets = daily_returns([100.0, 101.0, float("nan"), 103.0, 104.0])
        assert math.isnan(rets[1]) and math.isnan(rets[2])
        assert not math.isnan(rets[0]) and not math.isnan(rets[3])

    def test_unavailable_inputs_give_predicates_of_None_not_False(self, cfg):
        from sentinel.regime import SpyRegime

        p = regime_predicates(SpyRegime(float("nan"), float("nan")), cfg)
        assert p["spy_r20_confirms"] is None
        assert p["vol_acceleration"] is None


class TestTheTotalReturnDomainIsLoadBearing:
    """The falsifier for the whole `closeadj` carve-out.

    If substituting the ordinary close domain could not change a regime result,
    the exemption would not be worth taking. It can, and this shows it crossing
    the frozen threshold.
    """

    @staticmethod
    def _domains(quarterly_dividend=0.006):
        """A market flat in TOTAL return that pays dividends.

        Price return drifts down by the dividend each quarter-end; total return
        does not. Same market, two domains.
        """
        closeadj, close = [], []
        adj, px = 100.0, 100.0
        for i in range(MIN_CLOSES):
            if i and i % 7 == 0:          # a few ex-dividend dates in the window
                px *= (1.0 - quarterly_dividend)
            closeadj.append(adj)
            close.append(px)
        return closeadj, close

    def test_the_two_domains_DISAGREE_across_the_frozen_threshold(self, cfg,
                                                                 max_spy_r20):
        closeadj, close = self._domains()

        correct = spy_regime(closeadj)
        wrong = spy_regime(close)

        # Total return: the market is flat, so no confirmation.
        assert correct.spy_r20 == 0.0
        assert regime_predicates(correct, cfg)["spy_r20_confirms"] is False

        # Price return: the same flat market reads as a decline past -1%.
        assert wrong.spy_r20 < max_spy_r20
        assert regime_predicates(wrong, cfg)["spy_r20_confirms"] is True

    def test_the_wrong_domain_also_fabricates_volatility(self):
        closeadj, close = self._domains()
        assert math.isnan(volatility_acceleration(daily_returns(closeadj)))
        # Dividend steps are not market moves, but they are returns.
        assert rolling_std(daily_returns(close), VOL_SLOW_WINDOW) > 0.0

    def test_the_permitted_column_is_the_total_return_one(self):
        from sentinel.regime import spy as mod

        assert mod.SPY_PRICE_COLUMN == "closeadj"
        assert mod.SPY_TICKER == "SPY"


class TestNoLeakIntoOtherDomains:
    """The exemption must not leak. closeadj-derived numbers may reach the
    controller's two SPY fields and nothing else."""

    def test_the_seam_returns_ONLY_the_two_SPY_fields(self):
        fields = regime_observation_fields([100.0 + i for i in range(MIN_CLOSES)])
        assert set(fields) == {"spy_r20", "spy_vol_ratio"}

    def test_the_regime_module_cannot_reach_wealth_core_or_execution(self):
        """A static check on its imports: nothing from the book, the broker, the
        feed's bar normalisation, or breadth."""
        import ast
        import sentinel.regime.spy as mod

        tree = ast.parse(open(mod.__file__).read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        assert imported <= {"math", "dataclasses", "typing", "__future__", ""}

    def test_breadth_does_not_import_the_regime_module(self):
        """Breadth is SIGNAL-domain by construction. If it could reach the
        regime sensor it could reach a total-return price."""
        import ast
        paths = sorted((REPO / "sentinel" / "breadth").glob("*.py"))
        assert paths, "the breadth source scan is vacuous"
        for py in paths:
            tree = ast.parse(py.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    assert "regime" not in (node.module or ""), py
                if isinstance(node, ast.Import):
                    assert not any("regime" in a.name for a in node.names), py

    def test_only_the_session_kernel_imports_the_SPY_sensor(self):
        """Only the deterministic one-session kernel may cross this seam."""
        import ast
        importers = []
        paths = sorted((REPO / "sentinel").rglob("*.py"))
        assert paths, "the Sentinel source scan is vacuous"
        for py in paths:
            relative = py.relative_to(REPO).as_posix()
            if relative.startswith("sentinel/regime"):
                continue
            tree = ast.parse(py.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and "regime" in (node.module or ""):
                    importers.append(relative)
        assert importers == ["sentinel/core/kernel.py"], (
            "something now imports the SPY sensor: " + ", ".join(importers)
            + ". Only the deterministic session kernel may do so.")


class TestTheSeamIntoTheController:
    def test_the_values_are_accepted_by_the_controller_Observation(self):
        from sentinel.controller.machine import Observation

        closes = [100.0 - i * 0.1 for i in range(MIN_CLOSES)]
        ob = Observation(session="2026-08-12", **regime_observation_fields(closes))
        assert ob.spy_r20 is not None
        assert ob.spy_vol_ratio is not None

    def test_both_seams_compose_into_one_Observation(self):
        """breadth + regime, the two halves of the forward chain that exist."""
        from sentinel.breadth import Holding, breadth_observation_fields
        from sentinel.controller.machine import Observation

        book = [Holding("A", "TECH", 0.0, 0.01, 0.01, 1000)]
        closes = [100.0 - i * 0.1 for i in range(MIN_CLOSES)]
        ob = Observation(session="2026-08-12",
                         **breadth_observation_fields(book),
                         **regime_observation_fields(closes))
        assert ob.green_breadth == 1.0
        assert ob.spy_r20 is not None
