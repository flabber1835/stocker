"""Structure tests for the Screener's cluster display.

History: cluster was once a sortable CLUSTER *column* in the screener row. When the
screener went full-universe it was MOVED to the per-row detail card (so COMPANY
gets the full row width). These tests assert the column is gone and cluster now
lives in the detail card, while the api still overlays cluster_id.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DASH_MAIN = ROOT / "services" / "dashboard" / "app" / "main.py"
DASH_JS = ROOT / "services" / "dashboard" / "static" / "dashboard.js"
API_MAIN = ROOT / "services" / "api" / "app" / "main.py"


def _read(p):
    return p.read_text()


def test_screener_cluster_column_removed():
    html = _read(DASH_MAIN)
    # The sortable CLUSTER column was removed from the screener row.
    assert 'id="rh-cluster_id"' not in html
    assert ">CLUSTER<" not in html
    # Compact row is now 3 columns: # · TICKER · COMPANY (cluster moved to the card).
    assert 'id="r-body"><tr><td colspan="3"' in html
    assert 'id="rh-rank" title="Rank">#<' in html
    # SIZE column header is also gone (size lives in the detail card).
    assert 'id="rh-market_cap"' not in html


def test_screener_row_has_no_cluster_or_size_cell():
    js = _read(DASH_JS)
    # the row no longer renders a cluster or size cell — both moved to the card
    assert "t-cluster" not in js
    # NOTE: a raw `"t-size" not in js` is over-broad — it matches the substring
    # inside any inline `font-size:` style (which is what this test is NOT about).
    # The guard's intent is "no CSS class / cell named t-size": match the token
    # only when delimited like a class name.
    import re
    assert not re.search(r"""["'\s.]t-size["'\s]""", js), \
        "a t-size class/cell reappeared in dashboard.js"


def test_screener_detail_card_carries_cluster_size_drawdown():
    js = _read(DASH_JS)
    # cluster + size + drawdown render in the detail card grid (not the row)
    assert ">Cluster<" in js
    assert ">Size<" in js
    assert ">21d Drawdown<" in js
    # _mapRankRow still carries cluster_id (used by the detail card)
    assert "cluster_id: r.cluster_id" in js


def test_api_overlays_cluster_id_on_rankings():
    api = _read(API_MAIN)
    # helper param + load from the latest build's FULL candidate-pool cluster map
    # (candidate_clusters), so every ranked candidate can show a cluster — not only
    # the ~max_positions selected holdings.
    assert "cluster_by_ticker" in api
    assert "SELECT ticker, cluster_id FROM candidate_clusters" in api
    # both the with-overlays and search endpoints pass it through
    assert api.count("cluster_by_ticker=") >= 2
