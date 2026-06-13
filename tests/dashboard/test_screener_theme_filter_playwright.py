"""Playwright UI test: the Screener "Theme" filter (replaced the Theme tab).

Drives the REAL dashboard.js boot path in a fresh Chromium, intercepts /api/*, and
asserts:
  - default: the screener shows the top-N (/api/rankings/with-overlays) rows.
  - checking "Theme": the screener shows ONLY the AI-buildout theme set
    (/api/rankings/theme), including a theme name ranked far below the top-N window.
  - unchecking "Theme": the screener reverts to the top-N rows.
  - the held filter composes with the theme filter.

Run standalone:  python tests/dashboard/test_screener_theme_filter_playwright.py
Also collected by pytest as test_* wrappers (skipped if no Chromium binary).
"""
from __future__ import annotations

import glob
import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
from playwright.sync_api import sync_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_JS = ROOT / "services" / "dashboard" / "static" / "dashboard.js"


def _chrome_path() -> str | None:
    for pat in ("/opt/pw-browsers/chromium-*/chrome-linux/chrome",
                "/opt/pw-browsers/chromium-*/chrome-linux64/chrome"):
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[-1]   # newest build
    return None


def _rank_row(ticker, rank, *, held=False, name=None):
    return {
        "ticker": ticker, "rank": rank, "composite_score": 0.6, "percentile": 0.9,
        "regime": "bull_calm", "rank_date": "2026-06-12", "factor_scores": {},
        "rank_slope": None, "prior_rank": None, "name": name or (ticker + " Inc"),
        "sector": "Tech", "market_cap": 1e11, "cluster_id": None,
        "vetter_excluded": False, "vetter_confidence": None, "vetter_risk_type": None,
        "vetter_reason": None, "positive_catalyst": False, "positive_reason": None,
        "held": held, "qty": (5 if held else None),
        "market_value": (1000.0 if held else None), "unrealized_plpc": None,
        "not_in_universe": False,
    }


# Default top-N: a mix of theme + non-theme names. Note GME/AMC are NOT theme names.
_TOPN = [
    _rank_row("NVDA", 1),
    _rank_row("GME", 2),
    _rank_row("AMC", 3),
    _rank_row("VRT", 4, held=True),
    _rank_row("AAPL", 5),
]
# Theme set: includes VRT (held) and OKLO at rank 86 (far below the top-N window),
# proving the theme view pulls from the FULL universe, not the loaded top-N.
_THEME = {
    "count": 3, "run": {"run_id": "r1", "rank_date": "2026-06-12"},
    "theme": {"id": "ai_buildout", "as_of": "2026-06-13", "universe_size": 108},
    "rankings": [
        _rank_row("NVDA", 1),
        _rank_row("VRT", 4, held=True),
        _rank_row("OKLO", 86),
    ],
}


def _page() -> str:
    return """<!doctype html><html><head><meta charset="utf-8"></head><body>
      <span id="sb-regime" class="regime-pill regime-unknown">—</span>
      <div id="sb-text">LOADING</div><div id="sb-sub" style="display:none"></div>
      <span id="ds-date"></span><span id="ds-pending"></span>
      <span id="ds-inflight"></span><span id="ds-done"></span>
      <div id="trader-toolbar"></div>
      <input id="select-all-trades" type="checkbox">
      <button id="btn-approve-sel"></button><span id="sel-count"></span>
      <div class="filter-bar">
        <input type="search" id="r-search">
        <button id="r-search-clear"></button>
        <label><input type="checkbox" id="r-only-held" onchange="renderRankings()"> Holdings</label>
        <label><input type="checkbox" id="r-only-theme" onchange="onThemeToggle()"> Theme</label>
        <span id="r-count"></span>
      </div>
      <table><thead><tr><th id="rh-rank">#</th></tr></thead>
        <tbody id="r-body"><tr><td colspan="4" class="tbl-empty">Loading…</td></tr></tbody></table>
      <table><tbody id="trader-body"><tr><td class="tbl-empty">Loading…</td></tr></tbody></table>
      <table id="holdings-status-table"><tbody id="holdings-status-body"></tbody></table>
      <table><tbody id="live-body"></tbody></table>
      <table><tbody id="orders-body"></tbody></table>
      <table><tbody id="target-body"></tbody></table>
    </body></html>"""


def _route(route):
    url = route.request.url
    if "/api/rankings/with-overlays" in url:
        body = {"count": len(_TOPN), "run": {"run_id": "r1", "rank_date": "2026-06-12"},
                "prior_run": None, "rankings": _TOPN}
    elif "/api/rankings/theme" in url:
        body = _THEME
    elif "/api/regime" in url:
        body = {"regime": "bull_calm", "spy_price": 500}
    elif "/api/auto-approve-status" in url:
        body = {"pending": []}            # shape the 1s ticker expects
    else:
        body = {"rankings": [], "intents": [], "run": {}}
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body))


def _tickers_in_body(page) -> list[str]:
    return page.eval_on_selector_all(
        "#r-body .t-ticker", "els => els.map(e => e.textContent.trim())"
    )


def _run() -> dict:
    chrome = _chrome_path()
    if chrome is None:
        return {"fatal": "no Chromium binary under /opt/pw-browsers"}
    js = DASHBOARD_JS.read_text()
    errors: list[str] = []
    out: dict = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=chrome, headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
        )
        page = browser.new_page()
        page.on("pageerror", lambda exc: errors.append("pageerror: " + str(exc)))
        page.route("**/api/**", _route)
        # Serve the page over a real http origin so relative /api/* fetches resolve
        # to it and hit the **/api/** route (set_content's about:blank origin does
        # not). The JS is inlined so the boot IIFE runs as part of the document.
        html = _page().replace("</body>", "<script>" + js + "</script></body>")
        page.route("http://stocker.test/",
                   lambda r: r.fulfill(status=200, content_type="text/html", body=html))
        page.goto("http://stocker.test/")
        page.wait_for_timeout(600)  # let boot IIFE + loadRankings settle

        out["default"] = _tickers_in_body(page)

        # Turn ON the Theme filter (fires onThemeToggle → fetch /api/rankings/theme).
        page.check("#r-only-theme")
        page.wait_for_timeout(400)
        out["theme_on"] = _tickers_in_body(page)
        out["count_text"] = page.locator("#r-count").inner_text()

        # Compose with Holdings: only the held theme name (VRT) should remain.
        page.check("#r-only-held")
        page.wait_for_timeout(200)
        out["theme_and_held"] = _tickers_in_body(page)
        page.uncheck("#r-only-held")
        page.wait_for_timeout(200)

        # Turn OFF the Theme filter → revert to top-N.
        page.uncheck("#r-only-theme")
        page.wait_for_timeout(300)
        out["theme_off"] = _tickers_in_body(page)

        browser.close()
    out["errors"] = errors
    return out


def _evaluate(r: dict) -> list[str]:
    """Return a list of failure strings (empty == pass)."""
    fails = []
    if r.get("fatal"):
        return [r["fatal"]]
    if r["errors"]:
        fails.append("JS errors: " + "; ".join(r["errors"][:3]))
    if set(r["default"]) != {"NVDA", "GME", "AMC", "VRT", "AAPL"}:
        fails.append(f"default should show top-N; got {r['default']}")
    if set(r["theme_on"]) != {"NVDA", "VRT", "OKLO"}:
        fails.append(f"theme ON should show only theme set; got {r['theme_on']}")
    if "OKLO" not in r["theme_on"]:
        fails.append("theme ON must include a name below the top-N window (OKLO @86)")
    if "GME" in r["theme_on"] or "AAPL" in r["theme_on"]:
        fails.append(f"non-theme names leaked into theme view: {r['theme_on']}")
    if "theme" not in r["count_text"].lower():
        fails.append(f"count badge should mention 'theme'; got {r['count_text']!r}")
    if set(r["theme_and_held"]) != {"VRT"}:
        fails.append(f"theme+held should show only held theme name VRT; got {r['theme_and_held']}")
    if set(r["theme_off"]) != {"NVDA", "GME", "AMC", "VRT", "AAPL"}:
        fails.append(f"theme OFF should revert to top-N; got {r['theme_off']}")
    return fails


# ── pytest entry ────────────────────────────────────────────────────────────────

@pytest.mark.skipif(_chrome_path() is None, reason="no Chromium binary")
def test_screener_theme_filter():
    fails = _evaluate(_run())
    assert not fails, "\n".join(fails)


# ── standalone entry ─────────────────────────────────────────────────────────────

def main() -> int:
    r = _run()
    fails = _evaluate(r)
    print("default     :", r.get("default"))
    print("theme_on    :", r.get("theme_on"))
    print("count_text  :", r.get("count_text"))
    print("theme+held  :", r.get("theme_and_held"))
    print("theme_off   :", r.get("theme_off"))
    if fails:
        for f in fails:
            print("FAIL:", f)
        print("=== RESULT: FAIL ===")
        return 1
    print("=== RESULT: PASS ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
