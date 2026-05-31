"""Structure tests for the Screener's CLUSTER column (sortable correlation cluster).

The screener shows each ranked ticker's correlation cluster (from the latest
portfolio build's portfolio_holdings.cluster_id), overlaid by the api's
/rankings/with-overlays + /rankings/search endpoints. Column is sortable.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DASH_MAIN = ROOT / "services" / "dashboard" / "app" / "main.py"
DASH_JS = ROOT / "services" / "dashboard" / "static" / "dashboard.js"
API_MAIN = ROOT / "services" / "api" / "app" / "main.py"


def _read(p):
    return p.read_text()


def test_screener_has_sortable_cluster_header():
    html = _read(DASH_MAIN)
    assert 'id="rh-cluster_id"' in html
    assert "sortRankings('cluster_id')" in html
    assert ">CLUSTER<" in html
    # screener body colspan bumped from 4 to 5 for the new column
    assert 'id="r-body"><tr><td colspan="5"' in html


def test_screener_js_maps_and_renders_cluster():
    js = _read(DASH_JS)
    assert "cluster_id: r.cluster_id" in js          # _mapRankRow carries it
    assert "t-cluster" in js                          # rendered cell
    # cluster sorts ascending (A->Z) by default like name/ticker
    assert "col === 'cluster_id'" in js


def test_api_overlays_cluster_id_on_rankings():
    api = _read(API_MAIN)
    # helper param + load from the latest build's FULL candidate-pool cluster map
    # (candidate_clusters), so every ranked top-N candidate can show a cluster — not
    # only the ~max_positions selected holdings.
    assert "cluster_by_ticker" in api
    assert "SELECT ticker, cluster_id FROM candidate_clusters" in api
    # both the with-overlays and search endpoints pass it through
    assert api.count("cluster_by_ticker=") >= 2
