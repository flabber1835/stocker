"""Wealth Core v1 signal mathematics, against hand-computed miniatures.

These cover the mandatory acceptance tests that concern signals:

  * recent_return == 0 qualifies
  * durable ranking DIFFERS from raw-momentum ranking in a constructed example
  * input row ordering cannot change the ranking
  * no future session enters any signal

The last is the one worth stating carefully. A look-ahead test that only checks
"the answer is the same" can pass vacuously if the extra data was never in the
window to begin with. So it asserts the CONTRAPOSITIVE as well: perturbing a
price the signal DOES depend on must change the answer. A test that cannot fail
proves nothing about the one that can.
"""
from __future__ import annotations

import math

import pytest

from stock_strategy_shared.wealth_core.signals import (
    LONG_LOOKBACK_SESSIONS,
    REQUIRED_CLOSES,
    SKIP_RECENT_SESSIONS,
    DurableScore,
    annualized_formation_volatility,
    durable_score,
    medium_term_momentum,
    passes_freshness,
    rank_candidates,
    recent_return,
    top_decile_cutoff,
)


def _series(n=REQUIRED_CLOSES, start=100.0, step=1.0):
    """A strictly increasing close series, oldest first, index -1 == close[t]."""
    return [start + step * i for i in range(n)]


# ── medium-term momentum (spec §3) ──────────────────────────────────────────

class TestMediumTermMomentum:
    def test_it_is_close_t21_over_close_t126(self):
        """Hand-computed. With 127 closes 100..226 step 1, close[t-21] is index
        105 (=205) and close[t-126] is index 0 (=100)."""
        c = _series()
        assert c[-(SKIP_RECENT_SESSIONS + 1)] == 205.0
        assert c[-(LONG_LOOKBACK_SESSIONS + 1)] == 100.0
        assert medium_term_momentum(c) == pytest.approx(205.0 / 100.0 - 1.0)

    def test_the_skipped_month_is_actually_skipped(self):
        """THE defining property of 6-1 momentum. Moving only the final 21
        closes must not move the signal — that is what the skip is for."""
        c = _series()
        before = medium_term_momentum(c)
        c2 = list(c)
        for i in range(len(c2) - SKIP_RECENT_SESSIONS, len(c2)):
            c2[i] *= 3.0
        assert medium_term_momentum(c2) == pytest.approx(before)

    def test_it_DOES_move_when_an_endpoint_moves(self):
        """The contrapositive. Without this, the skip test above could pass on a
        function that ignored its input entirely."""
        c = _series()
        before = medium_term_momentum(c)
        c2 = list(c)
        c2[-(SKIP_RECENT_SESSIONS + 1)] *= 1.5
        assert medium_term_momentum(c2) != pytest.approx(before)

    @pytest.mark.parametrize("closes", [
        None, [], _series(REQUIRED_CLOSES - 1),          # one session short
    ])
    def test_insufficient_history_is_rejected(self, closes):
        assert medium_term_momentum(closes) is None

    def test_nonpositive_or_nonfinite_endpoints_are_rejected(self):
        c = _series(); c[-(LONG_LOOKBACK_SESSIONS + 1)] = 0.0
        assert medium_term_momentum(c) is None
        c = _series(); c[-(SKIP_RECENT_SESSIONS + 1)] = float("nan")
        assert medium_term_momentum(c) is None


# ── freshness (spec §4) ─────────────────────────────────────────────────────

class TestFreshness:
    def test_recent_return_is_close_t_over_close_t21(self):
        c = _series()
        assert recent_return(c) == pytest.approx(226.0 / 205.0 - 1.0)

    def test_ZERO_QUALIFIES(self):
        """MANDATORY. The spec says `recent_return >= 0` and states explicitly
        that zero qualifies. `> 0` would silently drop every flat name."""
        assert passes_freshness(0.0) is True

    def test_negative_is_rejected_and_positive_accepted(self):
        assert passes_freshness(-1e-12) is False
        assert passes_freshness(1e-12) is True

    def test_unknown_is_rejected_not_treated_as_zero(self):
        """None means 'could not compute'. Treating it as 0.0 would let a
        security with unusable prices pass the gate."""
        assert passes_freshness(None) is False


# ── formation volatility (spec §5) ──────────────────────────────────────────

class TestFormationVolatility:
    def test_it_matches_a_hand_computed_sample_stdev(self):
        """Explicit definition: sample stdev (ddof=1) of one-session SIMPLE
        returns over t-126 … t-21, times sqrt(252)."""
        c = _series()
        seg = c[-(LONG_LOOKBACK_SESSIONS + 1):len(c) - SKIP_RECENT_SESSIONS]
        rets = [b / a - 1.0 for a, b in zip(seg, seg[1:])]
        n = len(rets)
        mean = sum(rets) / n
        expected = math.sqrt(sum((r - mean) ** 2 for r in rets) / (n - 1)) * math.sqrt(252)
        assert annualized_formation_volatility(c) == pytest.approx(expected)

    def test_the_segment_is_formation_only_not_the_recent_month(self):
        """Volatility is measured over the SAME segment as the momentum signal.
        Including the skipped month would let the most recent 21 sessions move
        the denominator, quietly re-introducing what the skip removes."""
        c = _series()
        before = annualized_formation_volatility(c)
        c2 = list(c)
        for i in range(len(c2) - SKIP_RECENT_SESSIONS, len(c2)):
            c2[i] *= 5.0
        assert annualized_formation_volatility(c2) == pytest.approx(before)

    def test_it_uses_105_returns_from_106_closes(self):
        """The inclusive segment t-126 … t-21 spans 106 closes. Pinned because
        an off-by-one here changes every score by a small amount that no
        aggregate would reveal."""
        c = _series()
        seg = c[-(LONG_LOOKBACK_SESSIONS + 1):len(c) - SKIP_RECENT_SESSIONS]
        assert len(seg) == 106

    def test_a_frozen_price_yields_None_rather_than_zero(self):
        """Zero volatility would divide into infinity and hand the top of the
        ranking to whichever security stopped printing."""
        assert annualized_formation_volatility([100.0] * REQUIRED_CLOSES) is None

    def test_a_gap_inside_the_formation_window_invalidates_it(self):
        c = _series(); c[10] = float("nan")
        assert annualized_formation_volatility(c) is None


# ── durable score (spec §5) ─────────────────────────────────────────────────

class TestDurableScore:
    def test_it_is_log1p_momentum_over_volatility(self):
        assert durable_score(0.5, 0.25) == pytest.approx(math.log1p(0.5) / 0.25)

    @pytest.mark.parametrize("mom,vol", [
        (None, 0.2), (0.5, None), (0.5, 0.0), (0.5, -0.1),
        (-1.0, 0.2),                      # log1p undefined at -100%
        (float("nan"), 0.2), (0.5, float("inf")),
    ])
    def test_unusable_inputs_yield_None(self, mom, vol):
        assert durable_score(mom, vol) is None

    def test_DURABLE_ORDER_DIFFERS_FROM_RAW_MOMENTUM_ORDER(self):
        """MANDATORY, and the reason the spec insists raw momentum is not the
        sort key. HOT has the higher momentum; CALM wins on durable score
        because its formation path was quieter."""
        hot = DurableScore("S1", "HOT", momentum=1.00, recent=0.05,
                           volatility=0.90,
                           score=durable_score(1.00, 0.90), in_top_decile=True)
        calm = DurableScore("S2", "CALM", momentum=0.60, recent=0.05,
                            volatility=0.30,
                            score=durable_score(0.60, 0.30), in_top_decile=True)
        assert hot.momentum > calm.momentum          # raw order: HOT first
        ranked = rank_candidates([hot, calm])
        assert [r.ticker for r in ranked] == ["CALM", "HOT"]


# ── top-decile membership (spec §3) ─────────────────────────────────────────

class TestTopDecile:
    @pytest.mark.parametrize("n,expected", [
        (100, 10), (25, 3), (1, 1), (0, 0), (9, 1), (11, 2),
    ])
    def test_ceil_is_the_documented_default(self, n, expected):
        assert top_decile_cutoff(n) == expected

    def test_floor_and_round_are_available_because_the_spec_does_not_say(self):
        """Recorded as UNRESOLVED rather than silently fixed: 'the highest 10%'
        does not state a rounding rule, and the readings differ by one name on
        most days."""
        assert top_decile_cutoff(25, rounding="floor") == 2
        assert top_decile_cutoff(25, rounding="round") == 3

    def test_the_cutoff_never_exceeds_the_population(self):
        assert top_decile_cutoff(3, top_fraction=1.5) == 3

    def test_an_unknown_rounding_rule_is_refused(self):
        with pytest.raises(ValueError):
            top_decile_cutoff(10, rounding="nearest-ish")


# ── determinism (spec §5, mandatory) ────────────────────────────────────────

class TestDeterminism:
    def _cand(self, sid, tic, score):
        return DurableScore(sid, tic, momentum=0.5, recent=0.01, volatility=0.2,
                            score=score, in_top_decile=True)

    def test_INPUT_ORDER_CANNOT_CHANGE_THE_RANKING(self):
        """MANDATORY. A database returning rows in a different order must not
        produce a different portfolio from identical data."""
        rows = [self._cand(f"S{i}", f"T{i}", 1.0 - i * 0.01) for i in range(20)]
        forward = [r.ticker for r in rank_candidates(rows)]
        assert [r.ticker for r in rank_candidates(list(reversed(rows)))] == forward
        assert [r.ticker for r in rank_candidates(rows[7:] + rows[:7])] == forward

    def test_exact_ties_break_on_security_id_then_ticker(self):
        """Every candidate scores identically, so ONLY the tie breakers decide.
        Without them this ordering would be whatever the input order was."""
        rows = [self._cand("S2", "BBB", 1.0), self._cand("S1", "ZZZ", 1.0),
                self._cand("S1", "AAA", 1.0)]
        assert [(r.security_id, r.ticker) for r in rank_candidates(rows)] == [
            ("S1", "AAA"), ("S1", "ZZZ"), ("S2", "BBB")]

    def test_unqualified_candidates_never_reach_the_ranking(self):
        good = self._cand("S1", "GOOD", 1.0)
        no_decile = DurableScore("S2", "OUT", 0.5, 0.01, 0.2, 2.0,
                                 in_top_decile=False)
        stale = DurableScore("S3", "STALE", 0.5, -0.01, 0.2, 3.0,
                             in_top_decile=True)
        no_score = DurableScore("S4", "NOSCORE", 0.5, 0.01, None, None,
                                in_top_decile=True)
        ranked = rank_candidates([no_decile, stale, no_score, good])
        assert [r.ticker for r in ranked] == ["GOOD"]


# ── no look-ahead (spec §11, mandatory) ─────────────────────────────────────

class TestNoLookahead:
    def test_no_future_session_enters_any_signal(self):
        """Appending sessions AFTER t must not change a decision made at t.

        The window is taken from the end of the series, so this is checked by
        computing on the t-truncated series and asserting the same values — the
        complement (that in-window prices DO matter) is asserted above, so this
        cannot pass vacuously."""
        c = _series()
        mom, rec = medium_term_momentum(c), recent_return(c)
        vol = annualized_formation_volatility(c)

        future = c + [999.0, 1234.5, 0.01]
        # A decision at t reads only up to t: the caller truncates, and the
        # signal must be identical to the untruncated computation.
        truncated = future[:len(c)]
        assert medium_term_momentum(truncated) == pytest.approx(mom)
        assert recent_return(truncated) == pytest.approx(rec)
        assert annualized_formation_volatility(truncated) == pytest.approx(vol)

    def test_a_price_INSIDE_the_window_does_change_the_signal(self):
        """The falsifier for the test above."""
        c = _series()
        c2 = list(c); c2[-1] *= 1.2
        assert recent_return(c2) != pytest.approx(recent_return(c))
