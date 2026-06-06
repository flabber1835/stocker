"""Structure tests for the redesigned TARGET tab.

The tab is a sortable table of the held∪target union with per-ticker trade
decisions, mirroring the screener (rank + trend arrow + click-through detail):

    #  ·  TICKER  ·  HELD  ·  TARGET  ·  TRADE

These read the HTML/JS source as text and assert the wiring is present so an
accidental regression is caught in CI. Behavioural rendering is covered by
tests/dashboard/test_target_tab_playwright.py.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DASH_MAIN = ROOT / "services" / "dashboard" / "app" / "main.py"
DASH_JS = ROOT / "services" / "dashboard" / "static" / "dashboard.js"
PB_MAIN = ROOT / "services" / "portfolio-builder" / "app" / "main.py"


def _read(p):
    return p.read_text()


def _target_section(html: str) -> str:
    start = html.index('id="screen-target"')
    return html[start:start + 1600]


def test_nav_button_present():
    html = _read(DASH_MAIN)
    assert 'id="nav-target"' in html
    assert "showScreen('target'" in html
    assert ">Target<" in html


def test_section_has_sortable_columns():
    section = _target_section(_read(DASH_MAIN))
    assert 'id="target-body"' in section
    # Five sortable columns, each wired to sortTarget (blue-triangle sort).
    for col, header in (("rank", "#"), ("ticker", "TICKER"), ("held", "HELD"),
                        ("in_target", "TARGET"), ("trade", "TRADE")):
        assert f"sortTarget('{col}')" in section, f"missing sort hook for {col}"
        assert f">{header}<" in section, f"missing column header {header}"
    for hid in ("tgh-rank", "tgh-ticker", "tgh-held", "tgh-target", "tgh-trade"):
        assert f'id="{hid}"' in section, f"missing sortable header id {hid}"


def test_target_is_read_only_view():
    """The Target tab is a view (click → detail), not a trade surface — no
    approve/reject controls in the section."""
    section = _target_section(_read(DASH_MAIN))
    for forbidden in ("approveTrade", "rejectTrade", "btn-approve", 'onclick="approve'):
        assert forbidden not in section, f"target tab must be read-only, found {forbidden}"
    # Rows are click-through to the shared detail card.
    assert "toggleTargetDetail" in _read(DASH_JS)


def test_js_target_table_wiring():
    js = _read(DASH_JS)
    assert "name === 'target'" in js
    for fn in ("async function loadTargetPortfolio", "function buildTargetRows",
               "function sortTarget", "function renderTargetTable",
               "function toggleTargetDetail"):
        assert fn in js, f"missing {fn}"
    # Union sourced from delta intents + screener rankData (not the old weight list).
    assert "deltaData" in js and "rankData" in js
    assert "TARGET_TRADE" in js                 # action → label/held/target map
    assert "rankArrowHtml" in js                # same trend arrow as the screener
    # The old informational fetch/fields are gone.
    assert "/api/target-portfolio" not in js
    assert "h.weight" not in js


def test_builder_persists_and_returns_cluster_and_name():
    # Unchanged builder behaviour the screener/detail still rely on.
    pb = _read(PB_MAIN)
    assert "cluster_id=EXCLUDED.cluster_id" in pb
    assert "LEFT JOIN names n" in pb
    assert "ph.cluster_id" in pb
