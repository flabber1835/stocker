"""Structure tests for the informational Target Portfolio panel (4th UI panel).

These mirror the existing dashboard tests: they read the HTML/JS source as text
and assert the panel's wiring is present, so an accidental removal regresses in CI.
The panel shows ticker, company name, correlation cluster, and weight for the
latest target portfolio build (read-only — no trade controls).
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DASH_MAIN = ROOT / "services" / "dashboard" / "app" / "main.py"
DASH_JS = ROOT / "services" / "dashboard" / "static" / "dashboard.js"
PB_MAIN = ROOT / "services" / "portfolio-builder" / "app" / "main.py"


def _read(p):
    return p.read_text()


def test_nav_button_present():
    html = _read(DASH_MAIN)
    assert 'id="nav-target"' in html
    assert "showScreen('target'" in html
    assert ">Target<" in html


def test_screen_section_and_columns_present():
    html = _read(DASH_MAIN)
    assert 'id="screen-target"' in html
    assert 'id="target-body"' in html
    for col in (">TICKER<", ">COMPANY<", ">CLUSTER<", ">WEIGHT<"):
        assert col in html, f"missing column header {col}"


def test_panel_is_informational_no_trade_controls():
    """The Target panel must be read-only — no approve/reject/trade controls.
    Scope the check to the screen-target section."""
    html = _read(DASH_MAIN)
    start = html.index('id="screen-target"')
    section = html[start:start + 1400]
    for forbidden in ("approveTrade", "rejectTrade", "btn-approve", 'onclick="approve'):
        assert forbidden not in section, f"target panel must be read-only, found {forbidden}"


def test_js_loader_and_hook():
    js = _read(DASH_JS)
    assert "async function loadTargetPortfolio" in js
    assert "/api/target-portfolio" in js
    assert "name === 'target'" in js
    # renders the four informational fields
    assert "cluster_id" in js
    assert "h.ticker" in js and "h.name" in js and "h.weight" in js


def test_dashboard_proxy_endpoint_present():
    main = _read(DASH_MAIN)
    assert '@app.get("/api/target-portfolio")' in main
    # proxies the builder's latest target, not the api service
    assert "PORTFOLIO_URL" in main
    assert "/portfolio/latest" in main


def test_builder_persists_and_returns_cluster_and_name():
    pb = _read(PB_MAIN)
    assert "cluster_id=EXCLUDED.cluster_id" in pb  # persisted on insert
    assert "LEFT JOIN names n" in pb               # company name join
    assert "ph.cluster_id" in pb                   # returned by /portfolio/latest
