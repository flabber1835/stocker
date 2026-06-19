"""
Regression tests for the /rankings/with-overlays overlay-CTE scoping fix
(bug F1 — the real screener "no data" root cause).

The endpoint decorates only the top-`limit` ranking rows, but its overlay CTEs
(ticker_slopes, prior_ranks, names, caps) used to be computed over the FULL
universe before being LEFT JOINed down to ~100 rows. On a Russell-3000-scale DB
that O(universe) work blew past the dashboard proxy timeout and the screener
showed "no data". The fix materializes a `displayed` CTE of the top-`limit`
tickers FIRST and scopes every overlay CTE to it — mirroring the `matched` CTE
already used by /rankings/search.

These tests don't need a live DB: they inspect the SQL the endpoint builds so a
future edit that drops the scoping (reintroducing the unbounded scan) fails in
CI. The pure-Python decoration logic (_apply_overlays, held-injection, etc.) is
covered separately in test_rankings_search.py.
"""
from __future__ import annotations
import inspect
import re

from app import main


def _endpoint_source() -> str:
    # The heavy SQL lives in the internal compute function; the public
    # `get_rankings_with_overlays` endpoint is now a thin per-run cache wrapper
    # around it (single-flight + stale-while-revalidate).
    return inspect.getsource(main._compute_with_overlays)


# ── The scoping CTE exists and every overlay CTE references it ─────────────────

class TestDisplayedScoping:
    def test_displayed_cte_is_declared(self):
        """A `displayed` CTE bounding the work to the top-`limit` tickers must exist."""
        src = _endpoint_source()
        assert "displayed AS (" in src, "displayed scoping CTE was removed"

    def test_displayed_cte_is_bounded_by_limit_or_ticker_set(self):
        """The displayed CTE must be bounded: top-`limit` by default, or the explicit
        ticker set when `tickers=` is passed (the Target tab's scoped fetch). The
        default filter (limit) and the scoped filter (ANY(:only_tickers)) both live
        in the _disp_filter the CTE is built from."""
        src = _endpoint_source()
        # default path still bounds to the top-`limit` for the latest run
        assert re.search(r"run_id = :run_id ORDER BY rank ASC LIMIT :limit", src), \
            "default displayed CTE is no longer bounded by :limit"
        # scoped path bounds to the explicit set instead of the whole universe
        assert "ticker = ANY(:only_tickers)" in src, \
            "scoped (tickers=) path missing — Target tab would over-fetch the universe"

    def test_ticker_slopes_scoped_to_displayed(self):
        """ticker_slopes (REGR_SLOPE over 5 runs) must filter to the displayed set."""
        src = _endpoint_source()
        block = re.search(r"ticker_slopes AS \((.*?)GROUP BY", src, re.DOTALL)
        assert block, "ticker_slopes CTE not found"
        assert "IN (SELECT ticker FROM displayed)" in block.group(1), \
            "ticker_slopes is not scoped to displayed — unbounded universe scan"

    def test_ticker_slopes_still_uses_recent_runs(self):
        """Correctness: the 5-run history join must be preserved for the slope."""
        src = _endpoint_source()
        block = re.search(r"ticker_slopes AS \((.*?)GROUP BY", src, re.DOTALL)
        assert block
        assert "recent_runs" in block.group(1), \
            "ticker_slopes lost its 5-run history join — rank_slope would be wrong"

    def test_prior_ranks_scoped_to_displayed(self):
        src = _endpoint_source()
        block = re.search(r"prior_ranks AS \((.*?)\),", src, re.DOTALL)
        assert block, "prior_ranks CTE not found"
        assert "IN (SELECT ticker FROM displayed)" in block.group(1)

    def test_names_scoped_to_displayed(self):
        src = _endpoint_source()
        block = re.search(r"names AS \((.*?)\),", src, re.DOTALL)
        assert block, "names CTE not found"
        assert "IN (SELECT ticker FROM displayed)" in block.group(1), \
            "names CTE scans the whole universe snapshot — unbounded"

    def test_caps_scoped_to_displayed(self):
        src = _endpoint_source()
        # caps is the last CTE before the final SELECT
        block = re.search(r"caps AS \((.*?)\)\"\s*\n\s*\"SELECT", src, re.DOTALL)
        assert block, "caps CTE not found"
        assert "IN (SELECT ticker FROM displayed)" in block.group(1), \
            "caps CTE scans the whole fundamentals table — the original F1 bug"


# ── Response shape is preserved (same SELECT columns / final ORDER) ───────────

class TestResponseShapeUnchanged:
    def test_final_select_columns_unchanged(self):
        """The decorated columns the dashboard reads must be unchanged."""
        src = _endpoint_source()
        for col in ("r.ticker", "r.rank", "r.composite_score", "r.percentile",
                    "r.regime", "r.rank_date", "r.factor_scores",
                    "ts.rank_slope", "pr.prior_rank", "n.name", "n.sector",
                    "c.market_cap"):
            assert col in src, f"final SELECT lost column {col}"

    def test_final_query_still_limits_and_orders(self):
        src = _endpoint_source()
        assert "ORDER BY r.rank ASC LIMIT :limit" in src

    def test_left_joins_preserved(self):
        """Overlays remain LEFT JOINs so a missing name/cap doesn't drop a row."""
        src = _endpoint_source()
        for join in ("LEFT JOIN ticker_slopes", "LEFT JOIN prior_ranks",
                     "LEFT JOIN names", "LEFT JOIN caps"):
            assert join in src, f"{join} was changed/removed"


# ── The fix mirrors the already-correct /rankings/search pattern ──────────────

def test_search_endpoint_still_scopes_with_matched():
    """Guard the sibling endpoint's existing scoping doesn't regress either."""
    src = inspect.getsource(main.search_rankings)
    assert "matched AS (" in src
    assert "IN (SELECT ticker FROM matched)" in src
