"""Playwright UI test: the Screener navigate-typeahead search.

Drives the REAL dashboard.js boot path in a fresh Chromium, intercepts /api/*, and
asserts the reworked search behaviour (search no longer FILTERS the list):

  - the Holdings/Theme list-filter checkboxes are GONE.
  - typing shows a dropdown of matching tickers (ticker- AND name-contains).
  - the main list is NOT filtered while typing.
  - ArrowDown + Enter selects the highlighted match and scrolls/flashes its row,
    leaving the detail card COLLAPSED.
  - clicking a dropdown row selects it.
  - a match ranked outside the rendered list is fetched via
    /api/rankings/with-overlays?tickers=... , injected, then scrolled to.
  - a ticker not in the ranking run shows an inline "… not in this ranking run" note.

Run standalone:  python tests/dashboard/test_screener_search_typeahead_playwright.py
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


# Rendered top-N list. KEY/KEYS share a prefix; "Apple" is a name-only match for "APPL".
_TOPN = [
    _rank_row("NVDA", 1, name="NVIDIA Corp"),
    _rank_row("KEY", 2, name="KeyCorp"),
    _rank_row("KEYS", 3, name="Keysight Technologies"),
    _rank_row("AAPL", 4, name="Apple Inc"),
    _rank_row("MSFT", 5, name="Microsoft Corp"),
]
# OKLO is ranked 86 — NOT in the rendered list — so selecting it must fetch+inject
# via /api/rankings/with-overlays?tickers=OKLO.
_OKLO = _rank_row("OKLO", 86, name="Oklo Inc")


def _page() -> str:
    # Mirror the real screener markup (search-wrap + dropdown + note), no checkboxes.
    return """<!doctype html><html><head><meta charset="utf-8"><style>
      .search-dd{position:absolute;}
      .row-flash{background:yellow;}
      #r-body tr{display:block;}
      </style></head><body>
      <span id="sb-regime" class="regime-pill regime-unknown">—</span>
      <div id="sb-text">LOADING</div><div id="sb-sub" style="display:none"></div>
      <span id="ds-date"></span><span id="ds-pending"></span>
      <span id="ds-inflight"></span><span id="ds-done"></span>
      <div id="trader-toolbar"></div>
      <input id="select-all-trades" type="checkbox">
      <button id="btn-approve-sel"></button><span id="sel-count"></span>
      <section id="screen-screener" class="screen active"><div class="filter-bar">
        <span class="search-wrap">
          <input type="search" id="r-search" oninput="onSearchInput()" onkeydown="onSearchKeydown(event)">
          <button id="r-search-clear" onclick="clearSearch()" style="display:none">x</button>
          <div id="r-search-dd" class="search-dd" style="display:none"></div>
        </span>
        <span id="r-search-note" style="display:none"></span>
        <span id="r-count"></span>
      </div>
      <table><thead><tr><th id="rh-rank">#</th></tr></thead>
        <tbody id="r-body"><tr><td colspan="4" class="tbl-empty">Loading…</td></tr></tbody></table>
      </section>
      <section id="screen-trader"></section>
      <table><tbody id="trader-body"><tr><td class="tbl-empty">Loading…</td></tr></tbody></table>
      <table id="holdings-status-table"><tbody id="holdings-status-body"></tbody></table>
      <table><tbody id="live-body"></tbody></table>
      <table><tbody id="orders-body"></tbody></table>
      <table><tbody id="target-body"></tbody></table>
    </body></html>"""


def _route(route):
    url = route.request.url
    if "/api/rankings/with-overlays" in url and "tickers=" in url:
        # Scoped fetch for a deep-ranked / unknown ticker.
        if "OKLO" in url:
            body = {"count": 1, "run": {"run_id": "r1", "rank_date": "2026-06-12"},
                    "prior_run": None, "rankings": [_OKLO]}
        else:
            body = {"count": 0, "run": {"run_id": "r1", "rank_date": "2026-06-12"},
                    "prior_run": None, "rankings": []}
    elif "/api/rankings/with-overlays" in url:
        body = {"count": len(_TOPN), "run": {"run_id": "r1", "rank_date": "2026-06-12"},
                "prior_run": None, "rankings": _TOPN}
    elif "/api/rankings/suggest" in url:
        # Cheap typeahead: match ticker- OR name-contains across TOPN + OKLO.
        from urllib.parse import urlparse, parse_qs
        q = (parse_qs(urlparse(url).query).get("q", [""])[0] or "").upper()
        pool = _TOPN + [_OKLO]
        matches = [
            {"ticker": r["ticker"], "name": r["name"], "rank": r["rank"]}
            for r in pool
            if q and (q in r["ticker"].upper() or q in (r["name"] or "").upper())
        ]
        matches.sort(key=lambda m: (
            0 if m["ticker"].upper() == q else 1 if m["ticker"].upper().startswith(q) else 2,
            m["rank"],
        ))
        body = {"q": q, "matches": matches}
    elif "/api/regime" in url:
        body = {"regime": "bull_calm", "spy_price": 500}
    elif "/api/auto-approve-status" in url:
        body = {"pending": []}
    else:
        body = {"rankings": [], "intents": [], "run": {}}
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body))


def _tickers_in_body(page) -> list[str]:
    return page.eval_on_selector_all(
        "#r-body .t-ticker", "els => els.map(e => e.textContent.trim())"
    )


def _dd_items(page) -> list[str]:
    return page.eval_on_selector_all(
        "#r-search-dd .search-dd-item .sd-ticker", "els => els.map(e => e.textContent.trim())"
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
        html = _page().replace("</body>", "<script>" + js + "</script></body>")
        page.route("http://stocker.test/",
                   lambda r: r.fulfill(status=200, content_type="text/html", body=html))
        page.goto("http://stocker.test/")
        page.wait_for_timeout(600)  # boot IIFE + loadRankings

        out["default"] = _tickers_in_body(page)
        out["has_held_checkbox"] = page.locator("#r-only-held").count() > 0
        out["has_theme_checkbox"] = page.locator("#r-only-theme").count() > 0

        # ── Type a prefix: dropdown shows ticker-contains matches; list unchanged.
        page.fill("#r-search", "KEY")
        page.wait_for_timeout(350)
        out["dd_key"] = _dd_items(page)
        out["list_after_type"] = _tickers_in_body(page)   # must still be full list

        # ── Name-only match ("APPL" → "Apple Inc" matches AAPL by name).
        page.fill("#r-search", "APPL")
        page.wait_for_timeout(350)
        out["dd_appl"] = _dd_items(page)

        # ── ArrowDown + Enter selects highlighted (first = AAPL) and flashes its row.
        page.focus("#r-search")
        page.keyboard.press("ArrowDown")
        page.keyboard.press("Enter")
        page.wait_for_timeout(150)
        out["flashed_after_enter"] = page.eval_on_selector_all(
            "#r-body tr.row-flash .t-ticker", "els => els.map(e => e.textContent.trim())"
        )
        # Card must stay collapsed (no detail-row injected).
        out["detail_rows_after_enter"] = page.locator("#r-body tr.detail-row").count()

        # ── Click a dropdown row.
        page.fill("#r-search", "MSF")
        page.wait_for_timeout(350)
        page.click("#r-search-dd .search-dd-item:first-child")
        page.wait_for_timeout(150)
        out["flashed_after_click"] = page.eval_on_selector_all(
            "#r-body tr.row-flash .t-ticker", "els => els.map(e => e.textContent.trim())"
        )

        # ── Deep-ranked match (OKLO @86, not in rendered list) → fetch+inject+scroll.
        page.fill("#r-search", "OKLO")
        page.wait_for_timeout(350)
        page.keyboard.press("Enter")
        page.wait_for_timeout(300)
        out["list_after_oklo"] = _tickers_in_body(page)

        # ── Ticker not in the ranking run → inline note, no scroll-to-nothing.
        page.fill("#r-search", "ZZZZ")
        page.wait_for_timeout(350)
        page.keyboard.press("Enter")
        page.wait_for_timeout(300)
        out["note_text"] = page.locator("#r-search-note").inner_text()

        browser.close()
    out["errors"] = errors
    return out


def _evaluate(r: dict) -> list[str]:
    fails = []
    if r.get("fatal"):
        return [r["fatal"]]
    if r["errors"]:
        fails.append("JS errors: " + "; ".join(r["errors"][:3]))
    if r.get("has_held_checkbox"):
        fails.append("Holdings filter checkbox should be removed")
    if r.get("has_theme_checkbox"):
        fails.append("Theme filter checkbox should be removed")
    full = {"NVDA", "KEY", "KEYS", "AAPL", "MSFT"}
    if set(r["default"]) != full:
        fails.append(f"default should show full top-N; got {r['default']}")
    if set(r["dd_key"]) != {"KEY", "KEYS"}:
        fails.append(f"dropdown for 'KEY' should be KEY,KEYS; got {r['dd_key']}")
    if set(r["list_after_type"]) != full:
        fails.append(f"list must NOT be filtered while typing; got {r['list_after_type']}")
    if "AAPL" not in r["dd_appl"]:
        fails.append(f"name-contains 'APPL' should match AAPL (Apple Inc); got {r['dd_appl']}")
    if r["flashed_after_enter"] != ["AAPL"]:
        fails.append(f"ArrowDown+Enter should flash AAPL row; got {r['flashed_after_enter']}")
    if r["detail_rows_after_enter"] != 0:
        fails.append("selecting a match must leave the card COLLAPSED (no detail row)")
    if r["flashed_after_click"] != ["MSFT"]:
        fails.append(f"clicking dropdown row should flash MSFT; got {r['flashed_after_click']}")
    if "OKLO" not in set(r["list_after_oklo"]):
        fails.append(f"deep-ranked OKLO should be injected into the list; got {r['list_after_oklo']}")
    if "ZZZZ" not in (r["note_text"] or "") or "ranking run" not in (r["note_text"] or "").lower():
        fails.append(f"unknown ticker should show inline note; got {r['note_text']!r}")
    return fails


# ── pytest entry ────────────────────────────────────────────────────────────────

@pytest.mark.skipif(_chrome_path() is None, reason="no Chromium binary")
def test_screener_search_typeahead():
    fails = _evaluate(_run())
    assert not fails, "\n".join(fails)


# ── standalone entry ─────────────────────────────────────────────────────────────

def main() -> int:
    r = _run()
    fails = _evaluate(r)
    for k in ("default", "dd_key", "list_after_type", "dd_appl", "flashed_after_enter",
              "detail_rows_after_enter", "flashed_after_click", "list_after_oklo", "note_text"):
        print(f"{k:24}:", r.get(k))
    if fails:
        for f in fails:
            print("FAIL:", f)
        print("=== RESULT: FAIL ===")
        return 1
    print("=== RESULT: PASS ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
