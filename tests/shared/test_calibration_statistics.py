"""The statistics that separate a result from a coincidence.

An external review recomputed this system's ranking over 48 months and reported a
top-minus-bottom spread of +0.40pp with a bootstrap interval of −1.13 to +1.86 —
correctly calling it weak. The version that shipped here reported the point
estimate and a monotone fraction, and nothing else. A decile curve without a
sample size and an interval is not a measurement, and six anchors drawn from a
70-day window with a 20-session horizon are not six samples.

So these tests are about the honesty of the summary, not the arithmetic of the
mean: does a null relationship report a CI spanning zero, does overlap get
prevented at the source, and does a delisted name get excluded rather than
scored as flat.
"""
from __future__ import annotations

import random

import pytest

from stock_strategy_shared.calibration import (aggregate_calibration,
                                               bootstrap_ci,
                                               decile_forward_returns,
                                               decile_rows_from_ranks,
                                               space_out, spearman_ic)


def _perfect_pairs(n=100):
    """rank 1 best; forward return decreases monotonically with rank."""
    return [(i + 1, 1.0 - 0.01 * i) for i in range(n)]


# ── rank IC ───────────────────────────────────────────────────────────────────

class TestRankIC:
    def test_a_perfect_ranking_scores_plus_one(self):
        """Sign convention: lower rank = better prediction, but the reported IC
        follows the published orientation (positive = the ranking works), so a
        reader comparing it against a paper's 0.03 is comparing like with like."""
        assert spearman_ic(_perfect_pairs()) == pytest.approx(1.0, abs=1e-6)

    def test_an_inverted_ranking_scores_minus_one(self):
        pairs = [(i + 1, 0.01 * i) for i in range(100)]
        assert spearman_ic(pairs) == pytest.approx(-1.0, abs=1e-6)

    def test_noise_scores_near_zero(self):
        rng = random.Random(7)
        pairs = [(i + 1, rng.gauss(0, 1)) for i in range(400)]
        assert abs(spearman_ic(pairs)) < 0.15

    def test_a_constant_side_is_undefined_not_zero(self):
        """Zero would read as 'measured, no relationship'. There is no
        relationship to measure."""
        assert spearman_ic([(1, 0.5), (2, 0.5), (3, 0.5)]) is None

    def test_too_few_points_is_undefined(self):
        assert spearman_ic([(1, 0.1), (2, 0.2)]) is None

    def test_ties_are_averaged_not_ordered_by_input(self):
        a = spearman_ic([(1, 0.1), (2, 0.1), (3, 0.1), (4, 0.9)])
        b = spearman_ic([(2, 0.1), (1, 0.1), (3, 0.1), (4, 0.9)])
        assert a == b


# ── bootstrap ─────────────────────────────────────────────────────────────────

class TestBootstrap:
    def test_a_null_spread_reports_an_interval_spanning_zero(self):
        """THE test. A curve built from noise must not come back looking like a
        finding — the interval has to say so out loud. Checked across many draws,
        not one: a single sample of 40 can wander well off zero, which is exactly
        why a point estimate alone is not reportable."""
        spans = 0
        trials = 100
        for seed in range(trials):
            rng = random.Random(seed)
            ci = bootstrap_ci([rng.gauss(0.0, 0.02) for _ in range(40)], draws=500)
            spans += ci["lo"] < 0 < ci["hi"]
        # The bar is 80%, not 95%: a percentile bootstrap genuinely under-covers
        # at n=40, and pinning the nominal rate would make this test fail for
        # being correct. What it must catch is an interval that is BROKEN — too
        # narrow, or systematically missing zero — not one that is imperfect.
        assert spans >= 0.80 * trials, (
            f"only {spans}/{trials} null samples reported a CI spanning zero")

    def test_a_dead_even_sample_is_a_coin_flip(self):
        """prob_positive is the number worth quoting — it turns '+0.40pp' into
        '…and a 69% chance the true spread is positive', which reads very
        differently. On a sample with mean exactly zero it must say ~50%."""
        vals = [v for x in (0.01, 0.02, 0.03, 0.05) for v in (x, -x)]
        ci = bootstrap_ci(vals)
        assert ci["mean"] == pytest.approx(0.0, abs=1e-9)
        assert 0.35 < ci["prob_positive"] < 0.65

    def test_a_strong_consistent_spread_is_distinguished_from_it(self):
        ci = bootstrap_ci([0.02 + 0.001 * i for i in range(40)])
        assert ci["lo"] > 0 and ci["prob_positive"] > 0.99

    def test_it_is_deterministic(self):
        """A confidence interval that moves between runs is not quotable, and
        this repo tests determinism directly elsewhere."""
        vals = [0.01, -0.02, 0.03, 0.00, 0.015, -0.005]
        assert bootstrap_ci(vals) == bootstrap_ci(vals)

    def test_two_observations_get_no_interval(self):
        """A bootstrap over two points is theatre — better to report nothing."""
        assert bootstrap_ci([0.01, 0.02]) is None


# ── independence of anchors ───────────────────────────────────────────────────

class TestAnchorSpacing:
    def test_overlapping_anchors_are_dropped(self):
        """The original sampled 6 dates from a 70-day window against a 20-session
        horizon — the windows overlapped almost entirely, so the six 'samples'
        shared most of one return path."""
        kept = space_out([0, 5, 10, 15, 20, 25, 40, 41, 60], min_gap=20)
        idx = [[0, 5, 10, 15, 20, 25, 40, 41, 60][k] for k in kept]
        assert all(b - a >= 20 for a, b in zip(idx, idx[1:])), idx

    def test_the_newest_anchor_is_always_kept(self):
        """The most recent evidence is the most relevant; spacing should thin the
        past, not the present."""
        keys = [0, 10, 20, 30, 44]
        kept = space_out(keys, min_gap=20)
        assert keys[kept[-1]] == 44

    def test_max_n_caps_the_count(self):
        assert len(space_out(list(range(0, 1000, 25)), min_gap=20, max_n=5)) == 5

    def test_it_is_deterministic(self):
        keys = list(range(0, 500, 7))
        assert space_out(keys, 20, 10) == space_out(keys, 20, 10)


# ── missing endpoint prices ───────────────────────────────────────────────────

class TestMissingEndpoints:
    def test_a_name_with_no_endpoint_price_is_excluded_and_counted(self):
        """It must never be carried at its last print. A delisted name scored as
        FLAT inflates the deciles it concentrates in — the low ones — which
        shrinks top-minus-bottom and understates the ranking."""
        scores = {f"T{i:02d}": float(50 - i) for i in range(50)}
        base = {t: 100.0 for t in scores}
        fwd = {t: 110.0 for t in scores}
        del fwd["T45"], fwd["T46"], fwd["T47"]      # delisted, worst-ranked
        rows = decile_forward_returns(scores, base, fwd)
        meta = rows[0]["_meta"]
        assert meta["n_missing"] == 3 and meta["n_scored"] == 50
        assert sum(r["n"] for r in rows) == 47

    def test_the_rate_reaches_the_summary(self):
        scores = {f"T{i:02d}": float(50 - i) for i in range(50)}
        base = {t: 100.0 for t in scores}
        fwd = {t: 110.0 for t in scores if t not in ("T48", "T49")}
        agg = aggregate_calibration([decile_forward_returns(scores, base, fwd)], 20)
        assert agg["n_missing_endpoint"] == 2
        assert agg["missing_endpoint_rate"] == pytest.approx(0.04)


# ── the aggregate ─────────────────────────────────────────────────────────────

class TestAggregate:
    def test_a_perfect_relationship_is_monotone_with_a_positive_interval(self):
        rows = [decile_rows_from_ranks(_perfect_pairs()) for _ in range(8)]
        agg = aggregate_calibration(rows, 20)
        assert agg["monotone_fraction"] == 1.0
        assert agg["spread_ci"]["prob_positive"] > 0.99
        assert agg["per_date_ic"]["mean"] == pytest.approx(1.0, abs=1e-6)
        assert agg["per_date_ic"]["share_positive"] == 1.0
        assert agg["n_dates"] == 8

    def test_noise_gets_an_interval_that_spans_zero(self):
        rng = random.Random(11)
        rows = [decile_rows_from_ranks([(i + 1, rng.gauss(0, 0.05))
                                        for i in range(200)]) for _ in range(30)]
        agg = aggregate_calibration(rows, 20)
        assert agg["spread_ci"]["lo"] < 0 < agg["spread_ci"]["hi"]
        assert abs(agg["per_date_ic"]["mean"]) < 0.1

    def test_regimes_are_reported_separately_when_they_differ(self):
        """A factor can be monotone in bull_calm and inverted in bear_stress.
        Pooling can flatten a real conditional relationship into nothing, or
        universalise an accident that only happened in one regime."""
        good = decile_rows_from_ranks(_perfect_pairs())
        bad = decile_rows_from_ranks([(i + 1, 0.01 * i) for i in range(100)])
        agg = aggregate_calibration([good, good, bad, bad], 20,
                                    regimes=["bull_calm", "bull_calm",
                                             "bear_stress", "bear_stress"])
        by = agg["by_regime"]
        assert by["bull_calm"]["top_minus_bottom"] > 0
        assert by["bear_stress"]["top_minus_bottom"] < 0

    def test_a_single_date_regime_is_not_reported_as_a_curve(self):
        """One observation restated as a 'regime finding' is the most misleading
        thing this section could emit."""
        good = decile_rows_from_ranks(_perfect_pairs())
        agg = aggregate_calibration([good, good, good], 20,
                                    regimes=["bull_calm", "bull_calm", "bear_calm"])
        assert "bear_calm" not in (agg.get("by_regime") or {})

    def test_no_usable_date_returns_none(self):
        assert aggregate_calibration([[], []], 20) is None


def test_bt_engine_imports_the_canonical_module():
    """There used to be two implementations of this math and they DRIFTED — the
    live one lost the config filter, the error bars and the bounded forward
    lookup while the tunnel's was fine. One module now."""
    import os
    import sys
    root = os.path.join(os.path.dirname(__file__), "..", "..")
    sys.path.insert(0, os.path.join(root, "services", "bt-engine"))
    try:
        import stock_strategy_shared.calibration as canonical
        from app import calibration as shim
        assert shim is canonical
    finally:
        sys.path.pop(0)
        sys.modules.pop("app.calibration", None)
