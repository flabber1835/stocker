"""Screener overlays must not go stale across ranking runs.

Bug 1: the same ticker showed different red/green arrows on the Screener vs the
Target tab. Root cause — the Screener's per-ticker overlay cache (_overlayCache,
which holds prior_rank / rank_slope arrow inputs AND lazy-loaded factor_scores like
earnings_surprise) is keyed only by ticker and was never invalidated when a NEW
ranking run landed.

Bug 2 (same root, sharper): the cache was invalidated on rank_DATE change, but a
same-date RE-RUN (a fresh build after an earnings ingest — new run_id, same
rank_date) never tripped it, so the detail card kept showing the pre-earnings
overlay (earnings_surprise rendered "—" even though the new run had 0.997).

Fix: loadRankings clears the overlay caches when the run_id (d.run.run_id)
changes, forcing a re-enrich against the new run so both tabs agree and same-date
re-runs refresh.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DASH_JS = (ROOT / "services" / "dashboard" / "static" / "dashboard.js").read_text()


def test_tracks_loaded_run_id():
    assert "_loadedRunId" in DASH_JS


def test_overlay_cache_invalidated_on_new_run_id():
    # The invalidation must live in loadRankings and clear BOTH the screener overlay
    # cache and the Target store when the RUN changes. Keyed on run_id (not rank_date)
    # so a same-date re-run still busts the cache.
    idx = DASH_JS.index("async function loadRankings()")
    body = DASH_JS[idx: idx + 2500]
    assert "_newRunId" in body
    assert "d.run && d.run.run_id" in body            # keyed on the run identity
    assert "_newRunId !== _loadedRunId" in body
    assert "_overlayCache = {}" in body
    assert "_fullRankByTicker = {}" in body           # Target tab's store too
    assert "_loadedRunId = _newRunId" in body


def test_invalidation_not_keyed_on_rank_date():
    # Regression guard for bug 2: a same-date re-run must still invalidate, so the
    # check must NOT compare rank_date (two runs share a date).
    idx = DASH_JS.index("async function loadRankings()")
    body = DASH_JS[idx: idx + 2500]
    assert "_loadedRankDate" not in body, "must key on run_id, not rank_date (same-date re-run bug)"


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
