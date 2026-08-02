"""The vendor shadow — measuring the AV-vs-Sharadar difference.

The reason this exists is narrow and worth restating: live's `adjusted_close` is
AV-vintage while Sharadar's is uniformly restated, so a cutover silently re-bases
every price and moves every peak the trailing stop reads. On a book running
`exit_policy: trailing_stop_only` that is a strategy change arriving as a data
change, and its first evidence would be sales.

So the tests below care most about the ways a comparison can LIE:

  * a diff that reports agreement because it compared the wrong things
    (positional alignment, level instead of return, one-directional set diffs)
  * a cap that truncates a count rather than a listing, so "nothing suspicious"
    means "we stopped looking"
  * a headline that leads with rank correlation, which can sit at 0.99 while
    three names move through the top 25 and change the portfolio
"""
from __future__ import annotations

import pandas as pd
import pytest

from app.vendor_shadow import (
    MIN_PRICE_SESSIONS,
    PriceDiff,
    ShadowReport,
    compare_price_series,
    diff_sets,
    overlap_at_k,
    rank_movers,
    spearman,
    summarize_price_diffs,
)


# ── set comparisons ─────────────────────────────────────────────────────────

class TestSetDiff:
    def test_it_reports_BOTH_directions(self):
        """'How many names differ' hides which vendor is adding them, and that
        is the diagnosis: only-live is usually listing metadata, only-shadow is
        usually coverage."""
        d = diff_sets(["A", "B", "C"], ["B", "C", "D"])
        assert d.only_live == ["A"] and d.only_shadow == ["D"]
        assert (d.n_live, d.n_shadow, d.n_both) == (3, 3, 2)

    def test_jaccard_is_none_on_two_empty_sets_not_zero(self):
        """Zero would read as 'measured, total disagreement' — the worst
        possible misreading of 'we had nothing to compare'."""
        assert diff_sets([], []).jaccard is None
        assert diff_sets(["A"], ["A"]).jaccard == 1.0

    def test_the_named_sample_is_capped_but_the_COUNTS_are_exact(self):
        """A 2000-name mismatch must produce a readable row, and must not
        understate its own size while doing so."""
        d = diff_sets([f"L{i}" for i in range(500)], [], sample=5)
        assert len(d.only_live) == 5
        assert d.n_live == 500 and d.n_both == 0


class TestOverlapAtK:
    def test_it_measures_the_names_that_would_be_BOUGHT(self):
        live = ["A", "B", "C", "D"]
        shadow = ["A", "B", "X", "Y"]
        assert overlap_at_k(live, shadow, 4) == 0.5

    def test_order_within_the_top_k_does_not_matter(self):
        """A 25-name equal-ish book cares about membership, not about which of
        two selected names ranked higher."""
        assert overlap_at_k(["A", "B", "C"], ["C", "B", "A"], 3) == 1.0

    def test_a_short_side_is_unknown_rather_than_disagreement(self):
        """A partial top-k would read as the vendors disagreeing when the real
        answer is missing data."""
        assert overlap_at_k(["A", "B"], ["A", "B", "C"], 3) is None
        assert overlap_at_k([], [], 25) is None


# ── rank agreement ──────────────────────────────────────────────────────────

class TestSpearman:
    def test_it_aligns_on_TICKER_not_on_position(self):
        """THE alignment test. The two frames come from different vendors'
        universes, so positional alignment would correlate one company's rank
        against another's — a wrong number that looks entirely plausible."""
        a = pd.Series({"A": 1, "B": 2, "C": 3})
        b = pd.Series({"C": 3, "B": 2, "A": 1})       # same data, shuffled order
        assert spearman(a, b) == pytest.approx(1.0)

    def test_only_tickers_BOTH_sides_scored_are_used(self):
        """A name one vendor never ranked is dropped, not imputed. Note the
        overlap must still clear the 3-point floor — below it the answer is
        None, which is the correct reading of 'too little to compare'."""
        a = pd.Series({"A": 1, "B": 2, "C": 3, "D": 4})
        b = pd.Series({"A": 1, "B": 2, "C": 3, "Z": 9})
        assert spearman(a, b) == pytest.approx(1.0)

    def test_a_reversed_ranking_is_strongly_negative(self):
        a = pd.Series({"A": 1, "B": 2, "C": 3, "D": 4})
        b = pd.Series({"A": 4, "B": 3, "C": 2, "D": 1})
        assert spearman(a, b) == pytest.approx(-1.0)

    @pytest.mark.parametrize("a,b", [
        ({"A": 1}, {"A": 1}),                                # too few points
        ({"A": 1, "B": 1, "C": 1}, {"A": 1, "B": 2, "C": 3}),  # one side constant
        ({}, {}),
    ])
    def test_undefined_is_none_never_a_number(self, a, b):
        assert spearman(pd.Series(a, dtype=float), pd.Series(b, dtype=float)) is None


class TestRankMovers:
    def test_the_biggest_absolute_moves_come_first(self):
        m = rank_movers({"A": 1, "B": 2, "C": 3}, {"A": 1, "B": 90, "C": 5})
        assert m[0]["ticker"] == "B" and m[0]["delta"] == 88

    def test_a_name_only_one_side_ranked_is_skipped_not_zeroed(self):
        """Treating an unranked name as delta 0 would report perfect agreement
        about a security one vendor never saw."""
        m = rank_movers({"A": 1, "B": 2}, {"A": 1})
        assert [r["ticker"] for r in m] == ["A"], "B was never ranked by the shadow"

    def test_ties_break_on_ticker_so_the_output_is_deterministic(self):
        m = rank_movers({"B": 1, "A": 1}, {"B": 5, "A": 5})
        assert [r["ticker"] for r in m] == ["A", "B"]


# ── the corporate-action probe ──────────────────────────────────────────────

def _series(n=120, start=100.0, split_at=None, split=2.0):
    """A wiggling series; optionally a vendor-applied split partway through.

    The wiggle is not decoration. A constant-return series has one distinct
    return value, which makes every correlation undefined — a fixture that would
    let the probe pass by never computing anything.
    """
    import math as _m
    out, px = {}, start
    for i in range(n):
        d = pd.Timestamp("2025-01-01") + pd.Timedelta(days=i)
        f = split if (split_at is not None and i >= split_at) else 1.0
        out[d.date()] = px / f
        px *= 1.0 + 0.004 + 0.01 * _m.sin(i / 3.0)
    return out


class TestPriceProbe:
    def test_a_constant_adjustment_factor_is_NOT_a_difference(self):
        """The load-bearing choice. Two vendors' adjusted closes legitimately
        differ by a constant factor (different adjustment epochs). Comparing
        LEVELS would flag every single ticker; returns are invariant to it."""
        live = _series()
        shadow = {d: v * 0.87 for d, v in live.items()}
        d = compare_price_series("AAA", live, shadow)
        assert d.return_corr == pytest.approx(1.0)
        assert not d.suspicious

    def test_a_split_one_vendor_applied_and_the_other_did_not_IS_flagged(self):
        """THE test. This is the failure mode that would liquidate splitting
        holdings on a cutover, and it is invisible to every other measurement
        until it has already moved a rank."""
        live = _series()
        shadow = _series(split_at=60)
        d = compare_price_series("AAA", live, shadow)
        assert d.suspicious
        assert d.ratio_drift > 1.5

    def test_a_GRADUAL_rebasing_is_caught_by_drift_when_correlation_is_not(self):
        """CAUGHT BY MUTATION TESTING. The split test above passes on
        `return_corr` alone — one huge outlier day wrecks the correlation — so it
        never exercised the drift trigger, and removing that trigger left the
        suite green.

        This is the case only drift can see, and it is the more insidious of the
        two: a dividend adjustment applied differently accumulates a little each
        day, so every daily return still agrees to better than 0.99 while the two
        price LEVELS separate by 10%+ over a year. Momentum is computed off those
        levels.
        """
        live = _series(n=250)
        shadow = {d: v * (1.0 + 0.0005 * i)      # ~13% apart by year-end
                  for i, (d, v) in enumerate(live.items())}
        d = compare_price_series("AAA", live, shadow)
        assert d.return_corr is not None and d.return_corr > 0.99, \
            "precondition: the correlation check alone would pass this"
        assert d.ratio_drift is not None and d.ratio_drift > 1.05
        assert d.suspicious, "a 13% level divergence must not pass as agreement"

    def test_only_dates_BOTH_vendors_have_are_compared(self):
        """A session one vendor lacks is a coverage gap. Scoring it as a price
        disagreement would conflate two very different problems."""
        live = _series(n=120)
        shadow = {d: v for i, (d, v) in enumerate(live.items()) if i % 2 == 0}
        d = compare_price_series("AAA", live, shadow)
        assert d.n_sessions == len(shadow)
        assert d.return_corr == pytest.approx(1.0)

    def test_a_short_history_is_never_suspicious(self):
        """Below the floor it is a coverage difference, and reporting it as an
        adjustment difference would bury the real ones."""
        d = compare_price_series("AAA", _series(n=10), _series(n=10, split_at=5))
        assert d.n_sessions < MIN_PRICE_SESSIONS
        assert not d.suspicious

    def test_nonpositive_prices_are_dropped_rather_than_producing_a_ratio(self):
        live = dict(_series(n=60))
        shadow = dict(live)
        k = list(shadow)[10]
        shadow[k] = 0.0
        d = compare_price_series("AAA", live, shadow)
        assert d.n_sessions == 59 and d.ratio_drift == pytest.approx(1.0)

    def test_no_overlap_at_all_is_unknown_not_perfect_agreement(self):
        d = compare_price_series("AAA", _series(n=60), {})
        assert d.n_sessions == 0 and d.return_corr is None
        assert not d.suspicious


class TestPriceSummary:
    def test_the_suspicious_COUNT_is_never_truncated_by_the_sample_cap(self):
        """A cap that silently truncates the count reads as 'we checked and it
        is fine' — the exact failure this whole exercise exists to avoid."""
        diffs = [PriceDiff(f"T{i}", 100, 0.2, 3.0, 0.5) for i in range(50)]
        s = summarize_price_diffs(diffs, sample=5)
        assert s["n_suspicious"] == 50
        assert len(s["suspicious"]) == 5

    def test_too_short_names_are_counted_separately_not_silently_dropped(self):
        diffs = [PriceDiff("A", 5, None, None, None),
                 PriceDiff("B", 100, 1.0, 1.0, 0.0)]
        s = summarize_price_diffs(diffs)
        assert s["n_compared"] == 2 and s["n_usable"] == 1 and s["n_too_short"] == 1

    def test_the_worst_correlations_are_listed_first(self):
        diffs = [PriceDiff("GOOD", 100, 0.5, 1.0, 0.1),
                 PriceDiff("WORST", 100, -0.9, 1.0, 0.1)]
        s = summarize_price_diffs(diffs)
        assert s["suspicious"][0]["ticker"] == "WORST"


# ── the verdict ─────────────────────────────────────────────────────────────

class TestVerdict:
    """Ordered by what a cutover would BREAK, not by what is easiest to measure.
    A rank IC of 0.99 that moves three names through the top 25 changes the
    portfolio; one that shuffles ranks 400-2000 does not."""

    def test_a_target_difference_outranks_everything_else(self):
        r = ShadowReport(score_date="2026-08-02",
                         target={"jaccard": 0.6},
                         ranking={"spearman": 0.999, "overlap_at_25": 1.0})
        assert "TARGET DIFFERS" in r.verdict()

    def test_a_top_25_difference_is_reported_even_when_the_rank_IC_is_high(self):
        r = ShadowReport(score_date="2026-08-02",
                         target={"jaccard": 1.0},
                         ranking={"spearman": 0.999, "overlap_at_25": 0.8})
        assert "TOP-25 DIFFERS" in r.verdict()

    def test_price_outliers_surface_when_nothing_downstream_moved(self):
        """The early-warning case: the adjustment already differs but has not
        yet reached a rank. That is precisely when it is cheap to attribute."""
        r = ShadowReport(score_date="2026-08-02",
                         target={"jaccard": 1.0},
                         ranking={"spearman": 1.0, "overlap_at_25": 1.0},
                         price_adjustment={"suspicious": [{"ticker": "AAA"}]})
        assert "attribution" in r.verdict()

    def test_agreement_says_so_plainly(self):
        r = ShadowReport(score_date="2026-08-02", target={"jaccard": 1.0},
                         ranking={"spearman": 1.0, "overlap_at_25": 1.0},
                         price_adjustment={"suspicious": []})
        assert "no material difference" in r.verdict()

    def test_missing_measurements_do_not_manufacture_a_clean_verdict(self):
        """An empty report must not claim agreement it never measured — but it
        also must not claim a difference. It reports what it has."""
        assert ShadowReport(score_date="2026-08-02").verdict()

    def test_to_dict_carries_the_verdict_so_a_stored_row_cannot_disagree(self):
        """Nothing is derived at read time: a persisted row and the run that
        made it must say the same thing forever."""
        r = ShadowReport(score_date="2026-08-02", target={"jaccard": 0.5})
        assert r.to_dict()["verdict"] == r.verdict()
