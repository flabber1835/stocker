"""SG1: the delta's config check validates LINEAGE consistency (ranking vs the
portfolio it diffs), not the delta's freshly-reloaded config — so a config edit AFTER
a self-consistent chain built no longer false-deadlocks the delta.
"""
import app.main as pl


def test_consistent_lineage_no_skew():
    # ranking and portfolio built under the same config → OK, even if the file has since
    # changed to something else (the delta doesn't compare against its own reload).
    assert pl._detect_lineage_skew("SAME", "SAME") is None


def test_cross_config_lineage_flagged():
    msg = pl._detect_lineage_skew("OLDrank", "NEWport")
    assert msg is not None and "OLDrank" in msg and "NEWport" in msg


def test_cold_start_no_portfolio_is_ok():
    # No portfolio yet (cold start) → nothing to compare → no skew.
    assert pl._detect_lineage_skew("RANK", None) is None
    assert pl._detect_lineage_skew(None, None) is None
