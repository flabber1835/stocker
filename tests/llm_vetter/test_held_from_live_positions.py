"""
Tests for the vetter's held_tickers logic.

The vetter tells the LLM whether each stock is "ALREADY HELD" or a
"CANDIDATE FOR ENTRY". Before the fix, held_tickers came from
portfolio_holdings (portfolio-builder's target), which marks tickers as
held even when the corresponding trade was never submitted, risk-rejected,
or not yet filled.

After the fix, held_tickers comes from live_positions (alpaca-sync), which
reflects what the broker actually holds with qty > 0.

These tests verify the selection logic without a live DB by simulating
the query results.
"""
from __future__ import annotations


# ── Helpers that mirror the fixed query logic ─────────────────────────────────

def _held_from_live_positions(live_positions: list[dict]) -> set[str]:
    """
    Simulate:
        SELECT ticker FROM live_positions
        WHERE sync_run_id = (
          SELECT run_id FROM alpaca_sync_runs WHERE status='success'
          ORDER BY completed_at DESC LIMIT 1
        ) AND qty > 0
    """
    if not live_positions:
        return set()
    return {r["ticker"] for r in live_positions if r.get("qty", 0) > 0}


def _held_from_portfolio_holdings(portfolio_holdings: list[dict]) -> set[str]:
    """Old behaviour: read from portfolio_holdings (the target, not actual)."""
    return {r["ticker"] for r in portfolio_holdings}


# ── Fixtures ──────────────────────────────────────────────────────────────────

LIVE_POSITIONS = [
    {"ticker": "AAPL", "qty": 10,  "market_value": 1750.0},
    {"ticker": "MSFT", "qty": 5,   "market_value": 2000.0},
    {"ticker": "TSLA", "qty": 0,   "market_value": 0.0},    # closed, qty=0
]

PORTFOLIO_HOLDINGS = [
    # Target includes NVDA (entry intent pending approval) — not yet in Alpaca
    {"ticker": "AAPL"},
    {"ticker": "MSFT"},
    {"ticker": "NVDA"},   # in target but NOT in live positions
]


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestHeldFromLivePositions:
    def test_held_tickers_match_live_positions_with_qty(self):
        held = _held_from_live_positions(LIVE_POSITIONS)
        assert "AAPL" in held
        assert "MSFT" in held

    def test_zero_qty_position_excluded(self):
        """A live_positions row with qty=0 (closed position) must not count as held."""
        held = _held_from_live_positions(LIVE_POSITIONS)
        assert "TSLA" not in held

    def test_target_only_ticker_not_held(self):
        """NVDA is in portfolio_holdings target but has no live_positions row — not held."""
        held = _held_from_live_positions(LIVE_POSITIONS)
        assert "NVDA" not in held

    def test_empty_live_positions_gives_empty_set(self):
        assert _held_from_live_positions([]) == set()

    def test_all_zero_qty_gives_empty_set(self):
        positions = [{"ticker": "X", "qty": 0}, {"ticker": "Y", "qty": 0}]
        assert _held_from_live_positions(positions) == set()


class TestOldBehaviourVsNew:
    """Illustrates the divergence that the fix corrects."""

    def test_old_behaviour_marks_target_only_ticker_as_held(self):
        """portfolio_holdings includes NVDA even though Alpaca doesn't hold it."""
        old_held = _held_from_portfolio_holdings(PORTFOLIO_HOLDINGS)
        assert "NVDA" in old_held

    def test_new_behaviour_excludes_target_only_ticker(self):
        """live_positions does not include NVDA — correctly not marked held."""
        new_held = _held_from_live_positions(LIVE_POSITIONS)
        assert "NVDA" not in new_held

    def test_both_agree_on_actually_held_tickers(self):
        """AAPL and MSFT are in both target and live — both methods agree."""
        old_held = _held_from_portfolio_holdings(PORTFOLIO_HOLDINGS)
        new_held = _held_from_live_positions(LIVE_POSITIONS)
        assert "AAPL" in old_held and "AAPL" in new_held
        assert "MSFT" in old_held and "MSFT" in new_held

    def test_closed_position_excluded_by_new_not_old(self):
        """TSLA is closed (qty=0). New behaviour correctly excludes it."""
        positions_with_closed = LIVE_POSITIONS  # TSLA has qty=0
        holdings_with_closed = [{"ticker": "TSLA"}]
        old_held = _held_from_portfolio_holdings(holdings_with_closed)
        new_held = _held_from_live_positions(positions_with_closed)
        assert "TSLA" in old_held   # old: stale target still says held
        assert "TSLA" not in new_held  # new: correctly not held


class TestHeldQuerySQLColumn:
    """Regression: the held-tickers subquery must select run_id (UUID), not id.

    live_positions.sync_run_id is a UUID FK to alpaca_sync_runs.run_id.
    A previous version selected `id`, which 500'd the entire vetter run with:
        asyncpg.exceptions.UndefinedFunctionError:
        operator does not exist: uuid = integer

    The vetter crashed before ever calling the LLM, so the chain showed a brief
    "LLM ANALYSIS" then "READY" with no analysis performed. The other six call
    sites across the codebase all correctly use run_id; this was the lone outlier.

    The pure-Python simulations above never caught it because they don't exercise
    the real SQL, so this test inspects the source string directly.
    """

    def _vetter_source(self) -> str:
        import os
        path = os.path.join(
            os.path.dirname(__file__), "..", "..",
            "services", "llm-vetter", "app", "main.py",
        )
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_held_subquery_selects_run_id_not_id(self):
        src = self._vetter_source()
        assert "SELECT run_id FROM alpaca_sync_runs" in src, (
            "held-tickers subquery must select run_id (UUID) to match "
            "live_positions.sync_run_id"
        )

    def test_held_subquery_does_not_select_integer_id(self):
        src = self._vetter_source()
        assert "SELECT id FROM alpaca_sync_runs" not in src, (
            "selecting `id` from alpaca_sync_runs compares integer to UUID "
            "(sync_run_id) and crashes the vetter run"
        )


class TestInPortfolioFlagEffect:
    """
    Verify that only actually-held tickers receive the ALREADY HELD prompt flag.
    The vetter passes in_portfolio=ticker in held_tickers to vet_single_ticker,
    which renders as 'ALREADY HELD — assess continuation risk' in the prompt.
    """

    def test_held_ticker_gets_in_portfolio_true(self):
        held = _held_from_live_positions(LIVE_POSITIONS)
        assert ("AAPL" in held) is True

    def test_untraded_target_ticker_gets_in_portfolio_false(self):
        held = _held_from_live_positions(LIVE_POSITIONS)
        assert ("NVDA" in held) is False

    def test_closed_position_gets_in_portfolio_false(self):
        held = _held_from_live_positions(LIVE_POSITIONS)
        assert ("TSLA" in held) is False
