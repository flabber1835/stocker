"""
Tests for the rank-observation deduplication logic used inside _do_delta.

The deduplication lives in app/main.py (not engine.py) — it de-dupes raw DB
rows by (ticker, rank_date) keeping only the most-recently completed one so
that a calendar date never counts as two confirmation days.

Because the dedup logic runs inside an async DB function we extract the
essential algorithm here and test it as a pure-Python helper to avoid needing a
live database in unit tests.
"""
from datetime import date, datetime, timezone
from dataclasses import dataclass
from typing import Optional

import pytest

from app.engine import RankObservation, evaluate_all


# ── Replicate the dedup algorithm from app/main.py ────────────────────────────
# (Copied verbatim so the test documents the expected contract.)

@dataclass
class _FakeRow:
    ticker: str
    rank: int
    composite_score: float
    rank_date: date
    completed_at: Optional[datetime]


def _deduplicate_rankings(raw_rankings: list[_FakeRow]) -> list[_FakeRow]:
    """
    Deduplicate by (ticker, rank_date), keeping the row with the highest
    completed_at.  Mirrors the logic in delta-engine app/main.py _do_delta.
    """
    _dedup: dict[tuple, _FakeRow] = {}
    for row in raw_rankings:
        key = (row.ticker, row.rank_date)
        existing = _dedup.get(key)
        if existing is None or (row.completed_at or "") > (existing.completed_at or ""):
            _dedup[key] = row
    return list(_dedup.values())


def _build_universe(rows: list[_FakeRow]) -> dict[str, list[RankObservation]]:
    """Convert deduped rows into the universe dict used by evaluate_all."""
    universe: dict[str, list[RankObservation]] = {}
    for row in rows:
        obs = RankObservation(
            run_date=row.rank_date,
            rank=row.rank,
            composite_score=float(row.composite_score),
        )
        universe.setdefault(row.ticker, []).append(obs)
    for ticker in universe:
        universe[ticker].sort(key=lambda o: o.run_date, reverse=True)
    return universe


# ── helpers ───────────────────────────────────────────────────────────────────

_D1 = date(2026, 5, 15)
_D2 = date(2026, 5, 16)
_D3 = date(2026, 5, 17)

_T_EARLY  = datetime(2026, 5, 17, 10, 0, 0, tzinfo=timezone.utc)
_T_LATE   = datetime(2026, 5, 17, 18, 0, 0, tzinfo=timezone.utc)

# The production DB query returns completed_at as a datetime object (SQLAlchemy).
# When the dedup guard does `(row.completed_at or "") > (existing.completed_at or "")`,
# it relies on Python's > operator on either two datetime objects or two strings —
# but NOT a mixture.  In tests we always supply real datetime objects so that the
# comparison is type-consistent.  The None case is handled separately below.


def _row(ticker: str, rank: int, rank_date: date, completed_at: Optional[datetime]) -> _FakeRow:
    return _FakeRow(ticker=ticker, rank=rank, composite_score=1.0,
                    rank_date=rank_date, completed_at=completed_at)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestDeduplication:

    def test_duplicate_rank_dates_deduplicated(self):
        """
        Two rows for the same (ticker, rank_date) — the later completed_at wins.
        After dedup the date should appear exactly once.
        """
        rows = [
            _row("AAPL", rank=5,  rank_date=_D1, completed_at=_T_EARLY),
            _row("AAPL", rank=10, rank_date=_D1, completed_at=_T_LATE),   # later → kept
        ]
        deduped = _deduplicate_rankings(rows)
        aapl_rows = [r for r in deduped if r.ticker == "AAPL"]
        assert len(aapl_rows) == 1, "Duplicate rank_date must collapse to one row"
        # The row with the most recent completed_at is kept
        assert aapl_rows[0].rank == 10, "Later completed_at should be preferred"

    def test_no_duplicate_dates_unchanged(self):
        """Three observations on three distinct dates all survive deduplication."""
        rows = [
            _row("MSFT", rank=5,  rank_date=_D1, completed_at=_T_EARLY),
            _row("MSFT", rank=8,  rank_date=_D2, completed_at=_T_EARLY),
            _row("MSFT", rank=12, rank_date=_D3, completed_at=_T_EARLY),
        ]
        deduped = _deduplicate_rankings(rows)
        msft_rows = [r for r in deduped if r.ticker == "MSFT"]
        assert len(msft_rows) == 3, "No duplicates: all three rows must be preserved"

    def test_deduplication_preserves_order_after_sort(self):
        """After dedup + sort, observations should be most-recent-first."""
        rows = [
            _row("NVDA", rank=15, rank_date=_D3, completed_at=_T_EARLY),
            _row("NVDA", rank=20, rank_date=_D1, completed_at=_T_EARLY),
            _row("NVDA", rank=18, rank_date=_D2, completed_at=_T_EARLY),
        ]
        deduped = _deduplicate_rankings(rows)
        universe = _build_universe(deduped)
        obs_dates = [o.run_date for o in universe["NVDA"]]
        assert obs_dates == sorted(obs_dates, reverse=True), (
            "Observations must be sorted most-recent-first after dedup"
        )

    def test_duplicate_date_does_not_double_count_confirmation(self):
        """
        Without dedup a ticker with 2 rows on the same date would falsely appear
        to have 2 consecutive days in the entry zone.  After dedup it only has 1.
        """
        # Both rows are on _D1 — entry zone (rank ≤ 25)
        rows = [
            _row("GOOG", rank=10, rank_date=_D1, completed_at=_T_EARLY),
            _row("GOOG", rank=10, rank_date=_D1, completed_at=_T_LATE),
        ]
        deduped = _deduplicate_rankings(rows)
        universe = _build_universe(deduped)

        decisions = evaluate_all(
            universe=universe,
            current_portfolio={},
            entry_rank=25, exit_rank=40,
            confirmation_days=3,
            max_positions=30,
        )
        # Only 1 unique date in entry zone, well below confirmation_days=3
        assert decisions["GOOG"].action == "watch", (
            "Duplicate date must not inflate confirmation day count"
        )

    def test_multi_ticker_dedup_independent(self):
        """Dedup applies per (ticker, rank_date) — different tickers are independent."""
        rows = [
            # AAPL: two rows on _D1
            _row("AAPL", rank=5,  rank_date=_D1, completed_at=_T_EARLY),
            _row("AAPL", rank=6,  rank_date=_D1, completed_at=_T_LATE),
            # MSFT: one row on _D1
            _row("MSFT", rank=7,  rank_date=_D1, completed_at=_T_EARLY),
        ]
        deduped = _deduplicate_rankings(rows)
        aapl_d1 = [r for r in deduped if r.ticker == "AAPL" and r.rank_date == _D1]
        msft_d1 = [r for r in deduped if r.ticker == "MSFT" and r.rank_date == _D1]
        assert len(aapl_d1) == 1
        assert len(msft_d1) == 1

    def test_earliest_row_wins_when_completed_at_is_lower(self):
        """
        Edge case: earlier completed_at appears second in the list.
        The later completed_at must still win regardless of input order.
        """
        rows = [
            _row("AMD", rank=3,  rank_date=_D1, completed_at=_T_LATE),   # later, listed first
            _row("AMD", rank=30, rank_date=_D1, completed_at=_T_EARLY),  # earlier, listed second
        ]
        deduped = _deduplicate_rankings(rows)
        amd_rows = [r for r in deduped if r.ticker == "AMD"]
        assert len(amd_rows) == 1
        assert amd_rows[0].rank == 3, "Row with later completed_at must be retained"

    def test_none_completed_at_is_superseded_by_non_none(self):
        """
        A row with completed_at=None should be superseded by any row that has
        a real completed_at timestamp.
        """
        rows = [
            _row("TSLA", rank=5,  rank_date=_D1, completed_at=None),
            _row("TSLA", rank=8,  rank_date=_D1, completed_at=_T_EARLY),
        ]
        deduped = _deduplicate_rankings(rows)
        tsla_rows = [r for r in deduped if r.ticker == "TSLA"]
        assert len(tsla_rows) == 1
        assert tsla_rows[0].rank == 8, "Non-None completed_at must supersede None"
