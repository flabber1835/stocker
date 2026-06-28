"""Screener ▲▼ rank-arrow must not go stale across ranking runs.

Bug: the same ticker showed different red/green arrows on the Screener vs the
Target tab. Root cause — the Screener's per-ticker overlay cache (_overlayCache,
which holds prior_rank / rank_slope, the arrow inputs) is keyed only by ticker and
was never invalidated when a NEW ranking run landed. So the Screener kept showing
the arrow computed against the prior run while the Target tab (always re-fetches
fresh) showed the current one. Fix: loadRankings clears the overlay caches when
rank_date changes, forcing a re-enrich against the new run so both tabs agree.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DASH_JS = (ROOT / "services" / "dashboard" / "static" / "dashboard.js").read_text()


def test_tracks_loaded_rank_date():
    assert "_loadedRankDate" in DASH_JS


def test_overlay_cache_invalidated_on_new_rank_date():
    # The invalidation must live in loadRankings and clear BOTH the screener overlay
    # cache and the Target store when the rank_date changes.
    idx = DASH_JS.index("async function loadRankings()")
    body = DASH_JS[idx: idx + 2500]
    assert "_newRankDate" in body
    assert "_newRankDate !== _loadedRankDate" in body
    assert "_overlayCache = {}" in body
    assert "_fullRankByTicker = {}" in body          # Target tab's store too
    assert "_loadedRankDate = _newRankDate" in body


def test_arrow_function_is_shared_by_both_tabs():
    # Sanity: the arrow is computed by one shared function (so once the cached inputs
    # agree, the rendered arrows agree by construction).
    assert "function rankArrowHtml(" in DASH_JS


def test_table_arrow_uses_only_prior_rank_delta_on_both_tabs():
    """2a fix: the shared table arrow must use ONLY the 1-day prior_rank delta —
    prior_rank is returned by BOTH /universe (screener) and /with-overlays (target),
    so the same ticker can't show different arrows. It must NOT branch on rank_slope
    (only the Target had it → the Screener/Target disagreement)."""
    start = DASH_JS.index("function rankArrowHtml(")
    body = DASH_JS[start: DASH_JS.index("\n}", start)]
    assert "prior_rank" in body and "r.rank" in body
    # The arrow LOGIC must not read rank_slope (the field access); the comment may
    # mention it. r.rank_slope is the actual branch that caused the disagreement.
    assert "r.rank_slope" not in body, "table arrow must not branch on rank_slope (target-only field)"


def test_five_run_slope_preserved_in_detail_card():
    """The richer 5-run slope isn't lost — it moves to the detail card so it's still
    visible (where rank_slope is loaded with the overlay)."""
    assert "Rank trend (5-run)" in DASH_JS
    start = DASH_JS.index("function _buildDetailHtml(")
    body = DASH_JS[start: start + 6000]
    assert "r.rank_slope != null" in body, "detail card must surface the 5-run slope"
