"""market_context — the environment, measured, so results are interpretable.

The evaluator was asked to adapt the strategy while seeing the portfolio's
results but not the conditions producing them. That makes a whole class of
finding uninterpretable: a large negative excess vs SPY reads as "the factor
model is broken" when the measurable truth may be "the index was seven stocks".

Deliberately NOT a news/sentiment feed — see docs/architecture.md. The value
wanted here is quantitative: a narrow mega-cap rally IS
`mega_cap_lead_21d`; the headline is only a label on it.
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
        b = market_stats(rows, set(), {})["breadth"]
        assert b["pct_above_200sma"] == pytest.approx(2 / 3, abs=1e-4)
        assert b["n_with_200d_history"] == 3

    def test_a_young_listing_cannot_contribute_to_the_200d_number(self):
        """Otherwise a 30-day average is counted under the name '200-day', and
        breadth silently measures something else during an IPO wave."""
        rows = [_row("OLD", 110, sma200=100, n200=200),
                _row("NEW", 110, sma200=100, n200=30)]
        b = market_stats(rows, set(), {})["breadth"]
        assert b["n_with_200d_history"] == 1

    def test_every_metric_reports_its_own_denominator(self):
        """A breadth number over 40 names and one over 3000 are different
        claims. A section written to make results interpretable must not itself
        be uninterpretable."""
        b = market_stats([_row("A", 110, p21=100, sma200=100)], set(), {})["breadth"]
        assert {"n_with_200d_history", "n_with_50d_history", "n_scored_21d"} <= set(b)


class TestLeadership:
    def test_mega_cap_lead_is_the_narrow_index_measure(self):
        """THE number that separates 'we picked badly' from 'the index was
        seven stocks'."""
        rows = ([_row(t, 115, p21=100) for t in ("AAPL", "MSFT", "NVDA")]
                + [_row(f"S{i}", 101, p21=100) for i in range(20)])
        lead = market_stats(rows, {"AAPL", "MSFT", "NVDA"}, {})["leadership"]
        assert lead["mega_cap_median_21d"] == pytest.approx(0.15, abs=1e-4)
        assert lead["universe_median_21d"] == pytest.approx(0.01, abs=1e-4)
        assert lead["mega_cap_lead_21d"] == pytest.approx(0.14, abs=1e-4)
        assert lead["n_mega_caps_scored"] == 3

    def test_absent_mega_caps_give_none_not_zero(self):
        """None means 'not measured'; 0.0 would read as 'measured, no
        leadership' — the opposite conclusion."""
        lead = market_stats([_row("X", 110, p21=100)], set(), {})["leadership"]
        assert lead["mega_cap_lead_21d"] is None
        assert lead["universe_median_21d"] is not None

    def test_a_broad_rally_shows_no_lead(self):
        rows = [_row(t, 110, p21=100) for t in ("AAPL", "A", "B", "C")]
        lead = market_stats(rows, {"AAPL"}, {})["leadership"]
        assert lead["mega_cap_lead_21d"] == pytest.approx(0.0, abs=1e-9)


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
        assert "mega_cap_lead" in SYSTEM_PROMPT
        assert "sole justification" in SYSTEM_PROMPT.lower()
