"""Structure tests for the Trader screen's Holdings Status section.

The Trader screen keeps the order blotter (buy/sell orders + approval) as-is, and
adds a per-ticker informational section below it: a plain-English standing status
for every broker holding the delta engine evaluated (hold-in-target, orphan
counting down to exit, drift add/trim, order submitted, etc). Read-only.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DASH_MAIN = ROOT / "services" / "dashboard" / "app" / "main.py"
DASH_JS = ROOT / "services" / "dashboard" / "static" / "dashboard.js"
DASH_CSS = ROOT / "services" / "dashboard" / "static" / "dashboard.css"


def _read(p):
    return p.read_text()


def test_section_html_present_and_in_trader_screen():
    html = _read(DASH_MAIN)
    # the section table lives inside the trader screen, after the blotter
    tstart = html.index('id="screen-trader"')
    tend = html.index('id="screen-portfolio"')
    trader = html[tstart:tend]
    assert "Holdings Status" in trader
    assert 'id="holdings-status-body"' in trader
    for col in (">TICKER<", ">STATUS<", ">WEIGHT<"):
        assert col in trader, f"missing column {col}"
    # blotter (order table) still present and unchanged in the same screen
    assert 'id="trader-body"' in trader


def test_section_is_read_only():
    """No approve/reject controls in the holdings-status table markup."""
    html = _read(DASH_MAIN)
    start = html.index('id="holdings-status-table"')
    section = html[start:start + 600]
    for forbidden in ("approveTrade", "rejectTrade", "btn-approve", "checkbox"):
        assert forbidden not in section, f"holdings-status section must be read-only, found {forbidden}"


def test_js_render_and_status_logic():
    js = _read(DASH_JS)
    assert "function renderHoldingsStatus" in js
    assert "function _holdingStatus" in js
    assert "renderHoldingsStatus();" in js          # called from renderTrader
    assert "deltaRun = run" in js                    # run meta captured for confirmation_days
    # statuses cover the required cases from the request
    assert "in target" in js                          # hold because it's in target
    assert "Orphan" in js and "exits in" in js        # orphan + exit countdown
    assert "Order submitted" in js                    # buy/sell order submitted
    assert "buy-add" in js and "sell-trim" in js      # add / trim drift


def test_holdings_status_badge_css():
    css = _read(DASH_CSS)
    for cls in (".hs-badge", "hs-hold", "hs-atrisk", "hs-exit", "hs-submitted"):
        assert cls in css, f"missing css {cls}"
