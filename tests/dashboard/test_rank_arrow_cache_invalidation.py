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
