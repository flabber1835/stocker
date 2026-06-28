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
