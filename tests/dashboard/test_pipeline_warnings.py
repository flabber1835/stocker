"""
Tests for the staleness-warning logic in the dashboard pipeline-status endpoint.

The core logic is:
  rank_warning  = uni_fetched_at is set AND (rank_completed_at is None OR
                  uni_fetched_at > rank_completed_at)
  vet_warning   = rank_completed_at is set AND (vet_completed_at is None OR
                  rank_completed_at > vet_completed_at)
  port_warning  = rank_completed_at is set AND (port_completed_at is None OR
                  rank_completed_at > port_completed_at)

Previous bug: rank_warning was computed by comparing universe snapshot_date
(today's calendar date) against rank_date (the last available trading day's
price date).  Because snapshot_date is always >= rank_date the warning would
never clear, even immediately after a successful ranking run.

Fix: compare full ISO timestamps — uni_fetched_at vs rank_completed_at.
"""
import pytest
from app.main import _compute_pipeline_warnings


def _compute_warnings(
    uni_fetched_at: str | None,
    rank_completed_at: str | None,
    vet_completed_at: str | None,
    port_completed_at: str | None,
) -> dict:
    rank_warning, vet_warning, port_warning = _compute_pipeline_warnings(
        uni_fetched_at, rank_completed_at, vet_completed_at, port_completed_at
    )
    return {
        "rank_warning": rank_warning,
        "vet_warning": vet_warning,
        "port_warning": port_warning,
    }


class TestRankWarning:
    def test_no_warning_when_rank_completed_after_universe_fetch(self):
        """Ranking ran after universe was fetched → no warning."""
        w = _compute_warnings(
            uni_fetched_at="2026-05-16T08:00:00+00:00",
            rank_completed_at="2026-05-16T09:00:00+00:00",
            vet_completed_at=None,
            port_completed_at=None,
        )
        assert w["rank_warning"] is False

    def test_warning_when_universe_newer_than_rank(self):
        """Universe was re-fetched after the last ranking run → warn."""
        w = _compute_warnings(
            uni_fetched_at="2026-05-16T12:00:00+00:00",
            rank_completed_at="2026-05-16T08:00:00+00:00",
            vet_completed_at=None,
            port_completed_at=None,
        )
        assert w["rank_warning"] is True

    def test_warning_when_rank_never_run(self):
        """Universe exists but rankings have never been run → warn."""
        w = _compute_warnings(
            uni_fetched_at="2026-05-16T08:00:00+00:00",
            rank_completed_at=None,
            vet_completed_at=None,
            port_completed_at=None,
        )
        assert w["rank_warning"] is True

    def test_no_warning_when_universe_not_fetched_yet(self):
        """No universe data at all → nothing to warn about."""
        w = _compute_warnings(
            uni_fetched_at=None,
            rank_completed_at=None,
            vet_completed_at=None,
            port_completed_at=None,
        )
        assert w["rank_warning"] is False

    def test_old_bug_not_reproduced(self):
        """
        The old logic compared snapshot_date (today) > rank_date (last trading
        day).  This always returned True because today >= last trading day.
        Verify the timestamp-based logic does NOT trigger that false positive.
        """
        # Simulate: universe fetched at 08:00, ranking completed at 09:00 —
        # even though snapshot_date="2026-05-16" > rank_date="2026-05-14"
        # the correct timestamp comparison shows no warning.
        w = _compute_warnings(
            uni_fetched_at="2026-05-16T08:00:00+00:00",
            rank_completed_at="2026-05-16T09:00:00+00:00",
            vet_completed_at=None,
            port_completed_at=None,
        )
        assert w["rank_warning"] is False, (
            "False positive: warning should not fire when ranking ran after universe fetch"
        )


class TestVetWarning:
    def test_no_warning_when_vet_completed_after_rank(self):
        """Vetter ran after ranking → no warning."""
        w = _compute_warnings(
            uni_fetched_at="2026-05-16T08:00:00+00:00",
            rank_completed_at="2026-05-16T09:00:00+00:00",
            vet_completed_at="2026-05-16T10:00:00+00:00",
            port_completed_at=None,
        )
        assert w["vet_warning"] is False

    def test_warning_when_rank_newer_than_vet(self):
        """Rankings re-run after last vetter run → warn."""
        w = _compute_warnings(
            uni_fetched_at="2026-05-16T08:00:00+00:00",
            rank_completed_at="2026-05-16T11:00:00+00:00",
            vet_completed_at="2026-05-16T10:00:00+00:00",
            port_completed_at=None,
        )
        assert w["vet_warning"] is True

    def test_warning_when_vet_never_run(self):
        """Rankings exist but vetter has never run → warn."""
        w = _compute_warnings(
            uni_fetched_at="2026-05-16T08:00:00+00:00",
            rank_completed_at="2026-05-16T09:00:00+00:00",
            vet_completed_at=None,
            port_completed_at=None,
        )
        assert w["vet_warning"] is True

    def test_no_vet_warning_when_no_rank(self):
        """No ranking run → vetter warning is suppressed (nothing to vet)."""
        w = _compute_warnings(
            uni_fetched_at=None,
            rank_completed_at=None,
            vet_completed_at=None,
            port_completed_at=None,
        )
        assert w["vet_warning"] is False


class TestPortfolioWarning:
    def test_no_warning_when_portfolio_built_after_rank(self):
        """Portfolio built after rankings → no warning."""
        w = _compute_warnings(
            uni_fetched_at="2026-05-16T08:00:00+00:00",
            rank_completed_at="2026-05-16T09:00:00+00:00",
            vet_completed_at="2026-05-16T10:00:00+00:00",
            port_completed_at="2026-05-16T11:00:00+00:00",
        )
        assert w["port_warning"] is False

    def test_warning_when_rank_newer_than_portfolio(self):
        """Rankings re-run after portfolio was built → warn."""
        w = _compute_warnings(
            uni_fetched_at="2026-05-16T08:00:00+00:00",
            rank_completed_at="2026-05-16T12:00:00+00:00",
            vet_completed_at="2026-05-16T10:00:00+00:00",
            port_completed_at="2026-05-16T11:00:00+00:00",
        )
        assert w["port_warning"] is True

    def test_warning_when_portfolio_never_built(self):
        """Rankings exist but portfolio has never been built → warn."""
        w = _compute_warnings(
            uni_fetched_at="2026-05-16T08:00:00+00:00",
            rank_completed_at="2026-05-16T09:00:00+00:00",
            vet_completed_at=None,
            port_completed_at=None,
        )
        assert w["port_warning"] is True

    def test_full_pipeline_up_to_date_no_warnings(self):
        """All steps run in order → no warnings anywhere."""
        w = _compute_warnings(
            uni_fetched_at="2026-05-16T08:00:00+00:00",
            rank_completed_at="2026-05-16T09:00:00+00:00",
            vet_completed_at="2026-05-16T10:00:00+00:00",
            port_completed_at="2026-05-16T11:00:00+00:00",
        )
        assert w["rank_warning"] is False
        assert w["vet_warning"] is False
        assert w["port_warning"] is False
