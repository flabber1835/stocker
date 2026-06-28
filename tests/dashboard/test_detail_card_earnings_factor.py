"""Detail card must show the 7th factor (earnings_surprise).

The PEAD earnings-surprise factor is computed, persisted in factor_scores, written
into the rankings.factor_scores JSONB (rank.FACTORS includes it), and weighted in
the composite (0.12 in momentum_rotation_v2). The detail card's factor-chip list
historically showed only six factors and omitted it — so a real scoring factor was
invisible. This guards the full display path: the row must carry earnings_surprise
(via _mapRankRow) AND the chip list must render it.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DASH_JS = (ROOT / "services" / "dashboard" / "static" / "dashboard.js").read_text()


def test_mapped_row_exposes_earnings_surprise():
    # _mapRankRow must surface earnings_surprise as a top-level field so the chip's
    # r[f.key] lookup resolves (the api returns it inside factor_scores).
    start = DASH_JS.index("function _mapRankRow(")
    body = DASH_JS[start: DASH_JS.index("\n}", start)]
    assert "earnings_surprise: fs.earnings_surprise" in body


def test_detail_card_factor_list_includes_earnings_surprise():
    start = DASH_JS.index("const FACTORS = [")
    body = DASH_JS[start: DASH_JS.index("];", start)]
    assert "earnings_surprise" in body, "detail card must list the earnings_surprise factor"


def test_lazy_overlay_projects_earnings_surprise():
    # The detail card's factor chips are populated from the lazily-fetched overlay
    # object (_ensureOverlay), which explicitly enumerates the factor fields it copies
    # off the with-overlays response. If earnings_surprise is omitted there, the chip
    # reads undefined → "—" even when the api returns the value. Guard that projection.
    start = DASH_JS.index("const overlay = {")
    body = DASH_JS[start: DASH_JS.index("};", start)]
    assert "earnings_surprise: match.earnings_surprise" in body, \
        "lazy overlay must project earnings_surprise onto the cached detail row"


def test_near_high_shown_on_detail_card():
    # near_high is now a weighted scoring factor (momentum_rotation_v2) so it must be
    # visible on the card — same full path as earnings_surprise: row mapper, chip list,
    # and the lazy overlay projection.
    mapper = DASH_JS[DASH_JS.index("function _mapRankRow("):]
    mapper = mapper[: mapper.index("\n}")]
    assert "near_high: fs.near_high" in mapper
    chips = DASH_JS[DASH_JS.index("const FACTORS = ["):]
    chips = chips[: chips.index("];")]
    assert "near_high" in chips
    overlay = DASH_JS[DASH_JS.index("const overlay = {"):]
    overlay = overlay[: overlay.index("};")]
    assert "near_high: match.near_high" in overlay
