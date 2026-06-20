"""Structure tests for the Screener search controls.

History: the standalone Theme tab was first replaced by a Screener "Theme" filter
checkbox (alongside "Holdings"). Both list-FILTER checkboxes were then REMOVED when
the search box was reworked into a navigate-typeahead — the screener now always shows
the full ranked list and search jumps to a row instead of filtering. These tests
assert (a) the old Theme tab stays gone, and (b) the Holdings/Theme filter checkboxes
and their JS are gone.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DASH_MAIN = ROOT / "services" / "dashboard" / "app" / "main.py"
DASH_JS = ROOT / "services" / "dashboard" / "static" / "dashboard.js"


def _main():
    return DASH_MAIN.read_text()


def _js():
    return DASH_JS.read_text()


# ── Theme tab removed (legacy, still valid) ─────────────────────────────────────

def test_theme_tab_section_removed():
    html = _main()
    assert 'id="screen-theme"' not in html
    assert 'id="theme-body"' not in html


def test_theme_nav_button_removed():
    html = _main()
    assert 'id="nav-theme"' not in html
    assert "showScreen('theme'" not in html


def test_old_theme_proxies_removed():
    html = _main()
    assert '@app.get("/api/theme")' not in html
    assert '@app.post("/api/theme/refresh")' not in html
    assert "THEME_URL" not in html


def test_theme_tab_js_removed():
    js = _js()
    for fn in ("function loadTheme", "function renderThemeTable", "function sortTheme",
               "function toggleThemeDetail", "function refreshTheme"):
        assert fn not in js, fn
    assert "name === 'theme'" not in js


# ── Holdings / Theme list-filter checkboxes REMOVED ─────────────────────────────

def test_holdings_and_theme_filter_checkboxes_removed():
    html = _main()
    assert 'id="r-only-held"' not in html
    assert 'id="r-only-theme"' not in html
    assert "onThemeToggle()" not in html


def test_theme_filter_js_removed():
    js = _js()
    assert "function onThemeToggle" not in js
    assert "function _loadThemeData" not in js
    assert "_themeMode" not in js
    assert "_themeData" not in js
    # The old API-filter search behaviour is gone too.
    assert "_searchMode" not in js


def test_render_rankings_does_not_filter_by_holdings_or_theme():
    js = _js()
    # renderRankings must not reference removed filter inputs.
    assert "r-only-held" not in js
    assert "r-only-theme" not in js
