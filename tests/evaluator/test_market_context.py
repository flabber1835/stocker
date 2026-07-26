"""market_context — the environment, measured, so results are interpretable.

The evaluator was asked to adapt the strategy while seeing the portfolio's
results but not the conditions producing them. That makes a whole class of
finding uninterpretable: a large negative excess vs SPY reads as "the factor
model is broken" when the measurable truth may be "the index was seven stocks".

Deliberately NOT a news/sentiment feed — see docs/architecture.md. The value
wanted here is quantitative: a narrow mega-cap rally IS
`cap_minus_equal_weight_21d`; the headline is only a label on it.
"""
import pytest

from app.packet import _median, _stdev, market_stats


def _row(t, last, p21=None, p63=None, sma50=None, sma200=None, n200=200):
    return {"ticker": t, "last_px": last, "px_21": p21, "px_63": p63,
            "sma50": sma50, "sma200": sma200, "n200": n200}


class TestPureHelpers:
    def test_median_handles_both_parities(self):
        assert _median([3.0, 1.0, 2.0]) == 2.0
        assert _median([1.0, 2.0, 3.0, 4.0]) == 2.5
        assert _median([]) is None

    def test_stdev_needs_two_points(self):
        assert _stdev([1.0]) is None
        assert _stdev([1.0, 3.0]) == pytest.approx(1.4142, abs=1e-3)


class TestBreadth:
    def test_share_above_the_moving_averages(self):
        rows = [_row("A", 110, sma200=100, sma50=105),
                _row("B", 90, sma200=100, sma50=95),
                _row("C", 120, sma200=100, sma50=100)]
        b = market_stats(rows, set(), {})["ranked_universe_breadth"]
        assert b["pct_above_200sma"] == pytest.approx(2 / 3, abs=1e-4)
        assert b["n_with_200d_history"] == 3

    def test_a_young_listing_cannot_contribute_to_the_200d_number(self):
        """Otherwise a 30-day average is counted under the name '200-day', and
        breadth silently measures something else during an IPO wave."""
        rows = [_row("OLD", 110, sma200=100, n200=200),
                _row("NEW", 110, sma200=100, n200=30)]
        b = market_stats(rows, set(), {})["ranked_universe_breadth"]
        assert b["n_with_200d_history"] == 1

    def test_every_metric_reports_its_own_denominator(self):
        """A breadth number over 40 names and one over 3000 are different
        claims. A section written to make results interpretable must not itself
        be uninterpretable."""
        b = market_stats([_row("A", 110, p21=100, sma200=100)], set(), {})["ranked_universe_breadth"]
        assert {"n_with_200d_history", "n_with_50d_history", "n_scored_21d"} <= set(b)


class TestLeadership:
    def test_mega_cap_lead_is_the_narrow_index_measure(self):
        """THE number that separates 'we picked badly' from 'the index was
        seven stocks'."""
        rows = ([_row(t, 115, p21=100) for t in ("AAPL", "MSFT", "NVDA")]
                + [_row(f"S{i}", 101, p21=100) for i in range(20)])
        lead = market_stats(rows, {"AAPL", "MSFT", "NVDA"}, {})["leadership"]
        assert lead["mega_cap_median_21d"] == pytest.approx(0.15, abs=1e-4)
        assert lead["ranked_universe_median_21d"] == pytest.approx(0.01, abs=1e-4)
        assert lead["mega_cap_median_lead_21d"] == pytest.approx(0.14, abs=1e-4)
        assert lead["n_mega_caps_scored"] == 3

    def test_absent_mega_caps_give_none_not_zero(self):
        """None means 'not measured'; 0.0 would read as 'measured, no
        leadership' — the opposite conclusion."""
        lead = market_stats([_row("X", 110, p21=100)], set(), {})["leadership"]
        assert lead["mega_cap_median_lead_21d"] is None
        assert lead["ranked_universe_median_21d"] is not None

    def test_a_broad_rally_shows_no_lead(self):
        rows = [_row(t, 110, p21=100) for t in ("AAPL", "A", "B", "C")]
        lead = market_stats(rows, {"AAPL"}, {})["leadership"]
        assert lead["mega_cap_median_lead_21d"] == pytest.approx(0.0, abs=1e-9)


class TestDispersion:
    def test_low_dispersion_means_selection_was_barely_rewarded(self):
        flat = market_stats([_row(f"T{i}", 100.5, p21=100) for i in range(30)],
                            set(), {})["dispersion"]
        wide = market_stats([_row(f"T{i}", 100 + i * 3, p21=100) for i in range(30)],
                            set(), {})["dispersion"]
        assert wide["cross_sectional_stdev_21d"] > flat["cross_sectional_stdev_21d"]

    def test_sector_spread_identifies_the_extremes(self):
        rows = ([_row(f"E{i}", 120, p21=100) for i in range(6)]
                + [_row(f"U{i}", 90, p21=100) for i in range(6)])
        smap = {**{f"E{i}": "Energy" for i in range(6)},
                **{f"U{i}": "Utilities" for i in range(6)}}
        d = market_stats(rows, set(), smap)["dispersion"]
        assert d["best_sector"] == "Energy" and d["worst_sector"] == "Utilities"
        assert d["sector_spread_21d"] == pytest.approx(0.30, abs=1e-4)

    def test_a_thin_sector_is_not_reported_as_a_sector_median(self):
        """One stock is not a sector. Reporting it would put a single name's
        move on the page as though it described an industry."""
        rows = [_row("SOLO", 200, p21=100)] + [_row(f"E{i}", 110, p21=100)
                                               for i in range(6)]
        smap = {"SOLO": "Tiny", **{f"E{i}": "Energy" for i in range(6)}}
        d = market_stats(rows, set(), smap)["dispersion"]
        assert "Tiny" not in d["sector_medians_21d"]
        assert d["best_sector"] == "Energy"


class TestNoNewsByDesign:
    def test_the_section_carries_no_external_call(self):
        """The narrative version was deliberately rejected: the evaluator's only
        lever is a config change, so a headline in its context can only be acted
        on by changing the strategy — regime chasing with a diagnostic label."""
        import inspect
        from app.packet import _market_context
        src = inspect.getsource(_market_context)
        for forbidden in ("httpx", "tavily", "requests", "web_search"):
            assert forbidden not in src.lower(), (
                f"market_context reaches out to {forbidden} — it is meant to be "
                "deterministic and reproducible")

    def test_the_note_forbids_using_it_as_a_justification(self):
        import inspect
        from app.packet import _market_context
        src = inspect.getsource(_market_context)
        assert "must NOT" in src and "regime-STATIC" in src

    def test_no_macro_mechanism_exists_to_queue_against(self):
        """The structural half of the guard: even if the model wanted to act on
        market context, there is no config-shaped lever it maps onto."""
        from app.tools import MECHANISMS
        assert not any(m in MECHANISMS for m in ("macro", "regime", "sentiment"))

    def test_the_prompt_tells_it_to_check_context_before_blaming_the_model(self):
        from app.report import SYSTEM_PROMPT
        assert "market_context" in SYSTEM_PROMPT
        assert "cap_minus_equal_weight" in SYSTEM_PROMPT
        assert "sole justification" in SYSTEM_PROMPT.lower()


# ── review fixes: narrowness, pool honesty, falsifiable framing ─────────────

class TestCapWeightedNarrowness:
    """A median treats a $3T name and a $200B name identically, so
    mega_cap_median_lead cannot support the claim "the index was seven stocks".
    Cap-weighted minus equal-weighted over the SAME names can."""

    def _rows(self, big_ret, small_ret, n_small=40):
        return ([_row("MEGA", 100 * (1 + big_ret), p21=100)]
                + [_row(f"S{i}", 100 * (1 + small_ret), p21=100)
                   for i in range(n_small)])

    def _caps(self, mega_cap, small_cap, n_small=40):
        return {"MEGA": mega_cap, **{f"S{i}": small_cap for i in range(n_small)}}

    def test_one_huge_winner_shows_as_narrowness(self):
        lead = market_stats(self._rows(0.20, 0.00), set(), {},
                            self._caps(3e12, 1e10))["leadership"]
        assert lead["cap_minus_equal_weight_21d"] > 0.10, (
            "a mega-cap carrying the tape must register as narrow")
        assert lead["n_with_market_cap"] == 41

    def test_a_broad_rally_is_not_narrow(self):
        lead = market_stats(self._rows(0.10, 0.10), set(), {},
                            self._caps(3e12, 1e10))["leadership"]
        assert lead["cap_minus_equal_weight_21d"] == pytest.approx(0.0, abs=1e-6)

    def test_small_caps_leading_gives_a_negative_value(self):
        lead = market_stats(self._rows(0.00, 0.15), set(), {},
                            self._caps(3e12, 1e10))["leadership"]
        assert lead["cap_minus_equal_weight_21d"] < 0

    def test_thin_market_cap_coverage_reports_none_not_a_number(self):
        """Under 20 priced names with caps, the measure is noise — and a number
        would be acted on where None is correctly ignored."""
        lead = market_stats(self._rows(0.2, 0.0, n_small=5), set(), {},
                            self._caps(3e12, 1e10, n_small=5))["leadership"]
        assert lead["cap_minus_equal_weight_21d"] is None
        assert lead["n_with_market_cap"] == 6

    def test_absent_caps_degrade_to_the_median_proxy(self):
        """No market-cap coverage must not break the section — the weaker
        rank-based proxy still works."""
        lead = market_stats(self._rows(0.2, 0.0), {"MEGA"}, {})["leadership"]
        assert lead["cap_minus_equal_weight_21d"] is None
        assert lead["mega_cap_median_lead_21d"] is not None

    def test_the_static_list_carries_its_own_staleness_marker(self):
        lead = market_stats([_row("A", 110, p21=100)], set(), {})["leadership"]
        assert lead["mega_cap_list_as_of"]
        assert "drifts" in lead["note"]


class TestRegimeSnapshotDedup:
    def test_the_regime_query_takes_one_row_per_session(self):
        """regime_snapshots has NO unique constraint on snapshot_date and the
        pipeline plain-INSERTs, so a manual chain re-run adds a second row for
        the same session. Counting rows would make `sessions_held` and the vol
        percentile partly measure how often someone pressed Run."""
        import inspect
        from app.packet import _market_context
        src = inspect.getsource(_market_context)
        assert "DISTINCT ON (snapshot_date)" in src
        assert "calculated_at DESC" in src, (
            "no deterministic tie-break — which duplicate wins would be arbitrary")


class TestHonestFraming:
    def test_the_section_states_what_its_pool_actually_is(self):
        """Calling ranked-pool breadth 'market breadth' oversells it: the weak
        tail is already excluded, so it reads healthier than the market."""
        import inspect
        from app.packet import _market_context
        src = inspect.getsource(_market_context)
        assert '"pool"' in src
        assert "biased UPWARD" in src

    def test_regime_static_is_framed_as_a_finding_not_doctrine(self):
        """The system's philosophy is measure-don't-assume; embedding a
        contested empirical claim as settled, in the context of the one agent
        whose job is to question assumptions, is self-defeating."""
        import inspect
        import re
        from app.packet import _market_context
        from app.report import SYSTEM_PROMPT
        # Join adjacent string literals before searching: asserting on raw
        # source makes the test depend on where the lines happen to wrap, which
        # tests the formatting rather than the wording.
        src = re.sub(r'"\s*\n\s*"', "", inspect.getsource(_market_context))
        assert "not settled doctrine" in src
        assert "can be overturned" in src
        assert "not doctrine" in SYSTEM_PROMPT
        # ...but overturning it still requires the right KIND of evidence.
        assert "cross-regime" in SYSTEM_PROMPT and "held-out" in SYSTEM_PROMPT
