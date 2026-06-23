"""Audit P0 split-brain guard: every service must select the ACTIVE universe snapshot
by MAX(id) — never by snapshot_date/fetched_at, which is day-grained and lets two
same-day snapshots resolve differently across services (factor step scoring a
different universe than the one fetched-for/executed-on).

This is a source-structure regression guard for the unified selector.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVICES = ["pipeline", "av-ingestor", "llm-vetter", "portfolio-builder", "api"]


def _main(svc):
    return (ROOT / "services" / svc / "app" / "main.py").read_text()


def test_pipeline_selects_active_snapshot_by_max_id():
    src = _main("pipeline")
    # The active-snapshot selection must be MAX(id), matching the other services.
    assert "SELECT MAX(id) FROM universe_snapshots" in src


def test_no_service_selects_active_snapshot_by_snapshot_date_ordering():
    # Guard against re-introducing the divergent selector. We allow snapshot_date
    # ordering ONLY for the cross-snapshot NAME-resolution joins (DISTINCT ON ticker),
    # not for choosing the single active snapshot. The active-snapshot anti-pattern is
    # `FROM universe_snapshots ORDER BY snapshot_date DESC ... LIMIT 1`.
    bad = "FROM universe_snapshots ORDER BY snapshot_date DESC"
    for svc in SERVICES:
        assert bad not in _main(svc), (
            f"{svc} selects the active universe snapshot by snapshot_date — "
            "use MAX(id) (split-brain regression)."
        )
