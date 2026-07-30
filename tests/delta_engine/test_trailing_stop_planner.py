"""plan_trailing_stops — the pure trailing-stop policy.

The planner sits OUTSIDE evaluate_target_vs_live on purpose. That structure is the
feature's main safety property: with the stop off, live is bit-identical to the
pre-feature behaviour *by construction* rather than by a flag threaded through the
engine's seven branches. test_evaluate_target_vs_live_signature_is_unchanged at the
bottom of this file is what keeps that true.

Every skip rule here exists because of a specific way a naive stop misbehaves, and
each has its own test — a stop closes the WHOLE position and the caller cannot
un-sell it, so "no signal" and "sell" must never be confusable.
"""
import inspect
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../services/pipeline/app"))

from engine import (  # noqa: E402
    StopPlan,
    StopState,
    evaluate_target_vs_live,
    plan_trailing_stops,
    reentry_blocked,
)


def _state(peak=100.0, last=100.0, held=30, since=0) -> StopState:
    return StopState(peak_close=peak, last_close=last,
                     sessions_held=held, sessions_since_close=since)


def _plan(states, **over) -> StopPlan:
    kwargs = dict(enabled=True, stop_pct=0.15, arm_after_sessions=5,
                  max_stale_sessions=2, max_stops_per_run=5)
    kwargs.update(over)
    return plan_trailing_stops(states, **kwargs)


class TestOffSwitch:
    """The entire safety story for shipping this to production is that it is off."""

    def test_disabled_stops_nothing_however_bad_the_drawdown(self):
        plan = _plan({"AAA": _state(peak=100.0, last=10.0)}, enabled=False)
        assert plan.stopped == {}
        assert plan.deferred == {}
        assert plan.skipped == {}

    @pytest.mark.parametrize("states", [None, {}])
    def test_no_states_is_an_empty_plan(self, states):
        plan = _plan(states)
        assert plan.stopped == {}


class TestThreshold:
    @pytest.mark.parametrize("last,fires", [
        (100.0, False),   # at peak
        (90.0, False),    # -10%, inside the stop
        (85.0, True),     # exactly -15% — inclusive
        (85.01, False),
        (84.99, True),
        (40.0, True),
    ])
    def test_boundary_is_inclusive(self, last, fires):
        plan = _plan({"AAA": _state(last=last)})
        assert ("AAA" in plan.stopped) is fires

    def test_the_recorded_peak_is_the_one_that_triggered(self):
        """The caller persists this as stop_peak and reads it back to gate re-entry,
        so it must be the peak — not the close, not the stop price."""
        plan = _plan({"AAA": _state(peak=120.0, last=80.0)})
        assert plan.stopped["AAA"] == 120.0


class TestSkipRules:
    def test_unarmed_position_never_fires(self):
        """A 2-session-old position's peak IS its entry price, so any downtick
        reads as a drawdown from peak."""
        plan = _plan({"AAA": _state(last=50.0, held=3)}, arm_after_sessions=5)
        assert plan.stopped == {}
        assert plan.skipped == {"AAA": "unarmed"}

    def test_arming_boundary(self):
        assert _plan({"A": _state(last=50.0, held=5)}, arm_after_sessions=5).stopped
        assert not _plan({"A": _state(last=50.0, held=4)}, arm_after_sessions=5).stopped

    def test_stale_print_never_fires(self):
        """A halted or delisting name whose close is frozen below its peak would
        otherwise emit an unfillable exit every single run, forever."""
        plan = _plan({"AAA": _state(last=50.0, since=5)}, max_stale_sessions=2)
        assert plan.stopped == {}
        assert plan.skipped == {"AAA": "stale"}

    def test_staleness_boundary(self):
        assert _plan({"A": _state(last=50.0, since=2)}, max_stale_sessions=2).stopped
        assert not _plan({"A": _state(last=50.0, since=3)}, max_stale_sessions=2).stopped

    @pytest.mark.parametrize("peak,last", [
        (0.0, 50.0), (-1.0, 50.0), (float("nan"), 50.0),
        (100.0, 0.0), (100.0, -1.0), (100.0, float("nan")),
    ])
    def test_unusable_numbers_are_no_data_not_a_sell(self, peak, last):
        plan = _plan({"AAA": _state(peak=peak, last=last)})
        assert plan.stopped == {}
        assert plan.skipped == {"AAA": "no_data"}

    def test_a_healthy_position_is_neither_stopped_nor_skipped(self):
        """`skipped` means 'could not evaluate', not 'did not fire' — otherwise the
        diagnostic is useless because everything is in it."""
        plan = _plan({"AAA": _state(last=99.0)})
        assert plan.stopped == {} and plan.skipped == {}


class TestCircuitBreaker:
    """Exits are EXEMPT from the risk-service turnover cap (it counts only
    sell_trims), so this is the only thing between a market-wide drawdown and
    liquidating the whole book at a single open."""

    def _crash(self, n=10):
        # AAA is worst (-90%), JJJ mildest — each 5pp apart, all past the stop.
        return {chr(65 + i) * 3: _state(peak=100.0, last=10.0 + i * 5)
                for i in range(n)}

    def test_clamps_to_the_limit(self):
        plan = _plan(self._crash(), max_stops_per_run=3)
        assert len(plan.stopped) == 3

    def test_fires_the_worst_drawdowns_first(self):
        plan = _plan(self._crash(), max_stops_per_run=3)
        assert set(plan.stopped) == {"AAA", "BBB", "CCC"}

    def test_the_remainder_is_deferred_not_dropped(self):
        """A truncated exit list that reads as 'nothing more to do' is the same
        class of bug as a silently capped sweep."""
        plan = _plan(self._crash(), max_stops_per_run=3)
        assert len(plan.deferred) == 7
        assert set(plan.stopped) & set(plan.deferred) == set()

    def test_under_the_limit_nothing_is_deferred(self):
        plan = _plan(self._crash(n=2), max_stops_per_run=5)
        assert len(plan.stopped) == 2 and plan.deferred == {}


class TestDeterminism:
    def test_identical_inputs_give_an_identical_plan(self):
        states = {chr(65 + i) * 3: _state(peak=100.0, last=50.0) for i in range(8)}
        a = _plan(states, max_stops_per_run=3)
        b = _plan(dict(reversed(list(states.items()))), max_stops_per_run=3)
        assert a.stopped == b.stopped
        assert a.deferred == b.deferred

    def test_equal_drawdowns_tie_break_on_ticker(self):
        states = {"ZZZ": _state(last=50.0), "AAA": _state(last=50.0),
                  "MMM": _state(last=50.0)}
        plan = _plan(states, max_stops_per_run=1)
        assert set(plan.stopped) == {"AAA"}


class TestReentryBlocked:
    """The whole re-entry rule: no cooldown parameter, no timer. With a 15% stop,
    clearing it takes roughly a 17.6% rally off the stop price."""

    @pytest.mark.parametrize("last,blocked", [
        (80.0, True), (100.0, True), (100.01, False), (150.0, False),
    ])
    def test_blocks_until_the_triggering_peak_is_exceeded(self, last, blocked):
        assert reentry_blocked(last, 100.0) is blocked

    @pytest.mark.parametrize("last,peak", [
        (None, 100.0), (50.0, None), (None, None),
        (50.0, 0.0), (50.0, float("nan")), (float("nan"), 100.0),
    ])
    def test_unknown_inputs_never_block(self, last, peak):
        """A missing peak is not evidence to hold a name out of the book."""
        assert reentry_blocked(last, peak) is False


def test_evaluate_target_vs_live_signature_is_unchanged():
    """LOAD-BEARING.

    The trailing stop is planned outside the engine so that, with the feature off,
    the engine's inputs and behaviour are literally unchanged — not "changed but
    guarded by a flag". If a later edit slips a stop parameter in here, that
    guarantee is gone and no other test would notice, because with the feature off
    every one of them would still pass.

    Adding an UNRELATED parameter is fine — update the list deliberately. Adding a
    stop-related one means the design drifted and is worth a conversation first.
    """
    assert list(inspect.signature(evaluate_target_vs_live).parameters) == [
        "target_portfolio", "live_positions", "universe", "confirmation_days",
        "max_positions", "actual_weights", "drift_threshold", "account_value",
        "buying_power", "target_history", "orphan_confirmation_days",
        "dedup_survivors", "cash_fraction", "unranked_below_floor",
        "factor_gate_gap", "inflight_entries", "inflight_exits",
        "min_relative_drift", "min_trade_value", "risk_degraded",
    ]
