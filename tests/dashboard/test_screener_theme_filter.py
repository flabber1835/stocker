"""Structure tests for the Screener "Theme" filter that replaced the Theme tab.

The standalone Theme tab (nav button + screen + JS + theme-classifier proxy) was
removed; the theme is now a Screener checkbox ("Theme", like "Holdings") that filters
the universe to the hardcoded AI-buildout set via api /rankings/theme.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DASH_MAIN = ROOT / "services" / "dashboard" / "app" / "main.py"
DASH_JS = ROOT / "services" / "dashboard" / "static" / "dashboard.js"


def _main():
    return DASH_MAIN.read_text()


def _js():
    return DASH_JS.read_text()


# ── Theme tab removed ──────────────────────────────────────────────────────────

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


# ── Theme filter added ─────────────────────────────────────────────────────────

def test_screener_has_theme_checkbox():
    html = _main()
    assert 'id="r-only-theme"' in html
    assert "onThemeToggle()" in html
    # Sits next to the Holdings filter.
    assert 'id="r-only-held"' in html


def test_dashboard_proxies_rankings_theme():
    html = _main()
    assert '@app.get("/api/rankings/theme")' in html
    assert '"/rankings/theme"' in html


def test_js_has_theme_filter_logic():
    js = _js()
    assert "function onThemeToggle" in js
    assert "function _loadThemeData" in js
    assert "/api/rankings/theme" in js
    # Source precedence helper used by the detail-card lookup.
    assert "function _rankSource" in js
    assert "_themeMode" in js
