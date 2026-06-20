"""Playwright UI tests: the virtualized full-universe Screener.

Drives the REAL dashboard.js boot path, intercepts /api/*, and asserts the Phase 2/3
behaviour:

  Desktop (chromium):
    - loadRankings() fetches /api/rankings/universe (the FULL light list, 1500 rows).
    - the table is VIRTUALIZED: only a small window of <tr.rank-row> is in the DOM
      (< 100) even though the universe has 1500 rows.
    - scrolling the container renders a DIFFERENT window of rows.
    - sortRankings() reorders the full array (first visible row changes).
    - the typeahead scroll-to a DEEP ticker (index ~1200) brings it into view.
    - expanding a row LAZY-loads its overlays — a /api/rankings/with-overlays?tickers=
      request fires and the card then shows a heavy field (vetter / rank_slope).

  iPhone-16 (true WebKit if installable, else chromium with iPhone-16 emulation):
    - the universe list renders on the 393x852 mobile viewport.
    - touch/scroll updates the virtual window.
    - the search dropdown is usable and a selection scrolls to the row.
    - a detail card opens.

Run standalone:  python tests/dashboard/test_screener_virtualized_playwright.py
Collected by pytest as test_* wrappers (skipped if no browser binary).
"""
from __future__ import annotations

import glob
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
from playwright.sync_api import sync_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_JS = ROOT / "services" / "dashboard" / "static" / "dashboard.js"
DASHBOARD_CSS = ROOT / "services" / "dashboard" / "static" / "dashboard.css"

N_UNIVERSE = 1500
DEEP_IDX = 1200   # 1-based rank we scroll-to to prove index-based deep navigation


def _chrome_path() -> str | None:
    for pat in ("/opt/pw-browsers/chromium-*/chrome-linux/chrome",
                "/opt/pw-browsers/chromium-*/chrome-linux64/chrome"):
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[-1]   # newest build
    return None


def _webkit_path() -> str | None:
    # Try the already-installed location; the runner may also install on demand.
    for pat in ("/opt/pw-browsers/webkit-*/pw_run.sh",
                "/opt/pw-browsers/webkit-*/MiniBrowser"):
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[-1]
    return None


def _try_install_webkit() -> bool:
    """Best-effort `playwright install webkit`. Returns True if a WebKit binary is
    available afterwards. Network may be unavailable in CI — fail gracefully."""
    if _webkit_path():
        return True
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "webkit"],
            check=False, timeout=180, capture_output=True,
        )
    except Exception:
        return False
    return _webkit_path() is not None


# ── Synthetic data ────────────────────────────────────────────────────────────
def _universe(n: int = N_UNIVERSE) -> list[dict]:
    sectors = ["Tech", "Health", "Energy", "Financials", "Industrials", "Consumer"]
    rows = []
    for i in range(1, n + 1):
        tk = "TK%04d" % i
        rows.append({
            "ticker": tk, "rank": i, "name": "Test Corp %d" % i,
            "sector": sectors[i % len(sectors)],
            "composite_score": round(1.0 - i / (n + 1.0), 4),
            "percentile": round(1.0 - i / (n + 1.0), 4),
            "prior_rank": i, "cluster_id": ("C%d" % (i % 7) if i % 7 else None),
            "held": False, "qty": None, "market_value": None, "not_in_universe": False,
        })
    return rows


_UNIVERSE = _universe()


def _overlay_row(ticker: str) -> dict:
    return {
        "ticker": ticker, "rank": 1, "name": "Test Corp " + ticker, "sector": "Tech",
        "composite_score": 0.55, "percentile": 0.8, "regime": "bull_calm",
        "rank_date": "2026-06-12", "prior_rank": 5, "cluster_id": "C1",
        "rank_slope": -3.0, "market_cap": 1.2e11, "beta": 1.1,
        "factor_scores": {
            "momentum": 0.7, "quality": 0.6, "value": 0.4, "growth": 0.5,
            "low_volatility": 0.55, "liquidity": 0.9, "drawdown_21d": -0.08,
            "excess_dd_21d": -0.05, "idio_vol": 0.28, "excess_dd_limit": 0.12, "beta": 1.1,
        },
        "vetter_excluded": False, "vetter_confidence": "high",
        "vetter_risk_type": "none", "vetter_reason": "Clean — no falling-knife signal.",
        "positive_catalyst": False, "positive_reason": None,
        "held": False, "qty": None, "market_value": None, "not_in_universe": False,
    }


def _page() -> str:
    css = DASHBOARD_CSS.read_text()
    # Mirror the REAL screener markup including the #r-scroll virtual container so the
    # windowing path (not the no-scroll fallback) is exercised.
    return """<!doctype html><html><head><meta charset="utf-8">
      <style>%s</style>
      <style>html,body{margin:0;height:100%%;} #r-scroll{max-height:500px;}</style>
      </head><body>
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
      <div class="tbl-scroll" id="r-scroll" onscroll="onRankScroll()">
        <table><thead><tr>
          <th id="rh-rank" onclick="sortRankings('rank')">#</th>
          <th id="rh-ticker" onclick="sortRankings('ticker')">TICKER</th>
          <th id="rh-name" onclick="sortRankings('name')">COMPANY</th>
        </tr></thead>
        <tbody id="r-body"><tr><td colspan="3" class="tbl-empty">Loading…</td></tr></tbody></table>
      </div>
      </section>
      <section id="screen-trader"></section>
      <table><tbody id="trader-body"><tr><td class="tbl-empty">Loading…</td></tr></tbody></table>
      <table id="holdings-status-table"><tbody id="holdings-status-body"></tbody></table>
      <table><tbody id="live-body"></tbody></table>
      <table><tbody id="orders-body"></tbody></table>
      <table><tbody id="target-body"></tbody></table>
    </body></html>""" % css


_overlay_requests: list[str] = []


def _route(route):
    url = route.request.url
    if "/api/rankings/universe" in url:
        body = {"count": len(_UNIVERSE), "run": {"run_id": "big", "rank_date": "2026-06-12"},
                "prior_run": None, "rankings": _UNIVERSE}
    elif "/api/rankings/with-overlays" in url and "tickers=" in url:
        from urllib.parse import urlparse, parse_qs
        tks = (parse_qs(urlparse(url).query).get("tickers", [""])[0] or "").upper()
        _overlay_requests.append(tks)
        rows = [_overlay_row(t.strip()) for t in tks.split(",") if t.strip()]
        body = {"count": len(rows), "run": {"run_id": "ov", "rank_date": "2026-06-12"},
                "prior_run": None, "rankings": rows}
    elif "/api/rankings/with-overlays" in url:
        body = {"count": len(_UNIVERSE), "run": {"run_id": "big", "rank_date": "2026-06-12"},
                "prior_run": None, "rankings": _UNIVERSE[:100]}
    elif "/api/rankings/suggest" in url:
        from urllib.parse import urlparse, parse_qs
        q = (parse_qs(urlparse(url).query).get("q", [""])[0] or "").upper()
        matches = [
            {"ticker": r["ticker"], "name": r["name"], "rank": r["rank"]}
            for r in _UNIVERSE
            if q and (q in r["ticker"].upper() or q in (r["name"] or "").upper())
        ]
        matches.sort(key=lambda m: (
            0 if m["ticker"].upper() == q else 1 if m["ticker"].upper().startswith(q) else 2,
            m["rank"],
        ))
        body = {"q": q, "matches": matches[:20]}
    elif "/api/regime" in url:
        body = {"regime": "bull_calm", "spy_price": 500}
    elif "/api/auto-approve-status" in url:
        body = {"pending": []}
    else:
        body = {"rankings": [], "intents": [], "run": {}}
    route.fulfill(status=200, content_type="application/json", body=json.dumps(body))


def _row_count(page) -> int:
    return page.locator("#r-body tr.rank-row").count()


def _tickers_in_body(page) -> list[str]:
    return page.eval_on_selector_all(
        "#r-body tr.rank-row .t-ticker", "els => els.map(e => e.textContent.trim())"
    )


def _boot_page(page):
    page.route("**/api/**", _route)
    js = DASHBOARD_JS.read_text()
    html = _page().replace("</body>", "<script>" + js + "</script></body>")
    page.route("http://stocker.test/",
               lambda r: r.fulfill(status=200, content_type="text/html", body=html))
    page.goto("http://stocker.test/")
    page.wait_for_timeout(700)   # boot IIFE + loadRankings + first window paint


# ── Desktop virtualization test ───────────────────────────────────────────────
def _run_desktop() -> dict:
    chrome = _chrome_path()
    if chrome is None:
        return {"fatal": "no Chromium binary under /opt/pw-browsers"}
    _overlay_requests.clear()
    errors: list[str] = []
    out: dict = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=chrome, headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
        )
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        page.on("pageerror", lambda exc: errors.append("pageerror: " + str(exc)))
        _boot_page(page)

        # Full universe loaded but only a small window in the DOM.
        out["count_label"] = page.locator("#r-count").inner_text()
        out["window_rows_initial"] = _row_count(page)
        out["first_tickers"] = _tickers_in_body(page)[:3]

        # Scroll down → a DIFFERENT window of rows renders.
        page.eval_on_selector("#r-scroll", "el => { el.scrollTop = 8000; el.dispatchEvent(new Event('scroll')); }")
        page.wait_for_timeout(250)
        out["window_rows_after_scroll"] = _row_count(page)
        out["tickers_after_scroll"] = _tickers_in_body(page)[:3]

        # Sticky-header guard (regression: thead floated OVER tickers when it carried
        # top:46px inside the bounded #r-scroll). While scrolled, the column header
        # must pin FLUSH at the top of #r-scroll and NO data row may render above it.
        out["header_geom"] = page.evaluate(
            "() => {"
            "  const sc = document.getElementById('r-scroll').getBoundingClientRect();"
            "  const th = document.querySelector('#r-scroll thead').getBoundingClientRect();"
            "  const tops = [...document.querySelectorAll('#r-scroll tr.rank-row')]"
            "      .map(r => r.getBoundingClientRect().top);"
            "  return {scTop: sc.top, thTop: th.top, thBottom: th.bottom,"
            "          minRowTop: tops.length ? Math.min(...tops) : null};"
            "}")

        # Scroll back to top.
        page.eval_on_selector("#r-scroll", "el => { el.scrollTop = 0; el.dispatchEvent(new Event('scroll')); }")
        page.wait_for_timeout(250)

        # Sort by ticker descending (click twice — asc then desc) → first row changes.
        page.click("#rh-ticker")
        page.wait_for_timeout(150)
        page.click("#rh-ticker")
        page.wait_for_timeout(150)
        out["first_after_sort_desc"] = _tickers_in_body(page)[:1]
        # Restore rank sort.
        page.click("#rh-rank")
        page.wait_for_timeout(150)

        # Typeahead scroll-to a DEEP ticker (index ~1200) → brought into view & flashed.
        deep_tk = "TK%04d" % DEEP_IDX
        page.fill("#r-search", deep_tk)
        page.wait_for_timeout(350)
        page.keyboard.press("Enter")
        page.wait_for_timeout(400)
        out["deep_in_dom"] = page.locator("#rank-row-" + deep_tk).count()
        out["deep_flashed"] = page.eval_on_selector_all(
            "#r-body tr.row-flash .t-ticker", "els => els.map(e => e.textContent.trim())"
        )

        # Expand the deep row → lazy-load overlays; a with-overlays?tickers= fired and
        # the card shows a heavy field (vetter verdict).
        page.click("#rank-row-" + deep_tk)
        page.wait_for_timeout(500)
        out["detail_open"] = page.locator("#detail-row-" + deep_tk).count()
        out["overlay_requested"] = any(deep_tk in r for r in _overlay_requests)
        out["card_has_vetter"] = page.locator("#detail-row-" + deep_tk + " .llm-label").count()

        browser.close()
    out["errors"] = errors
    return out


def _evaluate_desktop(r: dict) -> list[str]:
    fails = []
    if r.get("fatal"):
        return [r["fatal"]]
    if r["errors"]:
        fails.append("JS errors: " + "; ".join(r["errors"][:3]))
    # Count label reflects the full universe.
    if str(N_UNIVERSE) not in (r.get("count_label") or ""):
        fails.append("count badge should show full universe %d; got %r" % (N_UNIVERSE, r.get("count_label")))
    # Virtualization: only a small window in the DOM.
    n0 = r.get("window_rows_initial", 0)
    if not (0 < n0 < 100):
        fails.append("virtualized DOM should hold < 100 rows; got %r" % n0)
    if r.get("first_tickers", [None])[0] != "TK0001":
        fails.append("initial first row should be TK0001; got %r" % r.get("first_tickers"))
    # Scrolling renders a different window.
    if r.get("tickers_after_scroll") == r.get("first_tickers"):
        fails.append("scrolling should render a different window; got same tickers")
    if not (0 < r.get("window_rows_after_scroll", 0) < 100):
        fails.append("DOM after scroll should still hold < 100 rows; got %r" % r.get("window_rows_after_scroll"))
    # Sort reorders the full array.
    if r.get("first_after_sort_desc", [None])[0] == "TK0001":
        fails.append("ticker-desc sort should change the first row; still TK0001")
    # Deep typeahead scroll-to.
    if r.get("deep_in_dom", 0) < 1:
        fails.append("deep ticker should be rendered into the window after scroll-to")
    if r.get("deep_flashed", []) != ["TK%04d" % DEEP_IDX]:
        fails.append("deep ticker row should flash; got %r" % r.get("deep_flashed"))
    # Lazy card.
    if r.get("detail_open", 0) < 1:
        fails.append("detail card should open for the deep row")
    if not r.get("overlay_requested"):
        fails.append("expanding should fire a with-overlays?tickers= request")
    if r.get("card_has_vetter", 0) < 1:
        fails.append("card should show a heavy overlay field (vetter) after lazy load")
    # Sticky-header guard: the column header must pin FLUSH at the top of #r-scroll
    # after scrolling. The regression (thead top:46px inside the bounded container)
    # parked the header 46px down, leaving a gap where rows showed ABOVE it. We test
    # thTop ≈ scTop only — NOT "no row above header bottom", because rows correctly
    # scroll UNDER an opaque sticky header (their top can sit above its bottom).
    g = r.get("header_geom") or {}
    if not g:
        fails.append("header_geom not captured")
    elif abs(g["thTop"] - g["scTop"]) > 2:
        fails.append("sticky header not flush at #r-scroll top after scroll "
                     "(regression: header floating over tickers): thTop=%r scTop=%r"
                     % (g["thTop"], g["scTop"]))
    return fails


# ── iPhone-16 mobile test (true WebKit if available, else chromium emulation) ──
# iPhone 16 logical viewport: 393x852 @3x. Mobile Safari UA.
_IPHONE16 = {
    "viewport": {"width": 393, "height": 852},
    "device_scale_factor": 3,
    "is_mobile": True,
    "has_touch": True,
    "user_agent": ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
                   "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"),
}


def _run_mobile() -> dict:
    out: dict = {"engine": None}
    webkit_available = _try_install_webkit()
    chrome = _chrome_path()
    if not webkit_available and chrome is None:
        return {"fatal": "no browser binary (no WebKit, no Chromium)"}
    _overlay_requests.clear()
    errors: list[str] = []
    with sync_playwright() as p:
        browser = None
        ctx = None
        # Prefer TRUE WebKit (real mobile Safari engine). The binary may be present but
        # un-launchable (missing system libs, no GTK, etc.) — if launch fails, fall back
        # to chromium with iPhone-16 device emulation (clearly flagged, NOT true WebKit).
        if webkit_available:
            try:
                browser = p.webkit.launch(headless=True)
                ctx = browser.new_context(
                    viewport=_IPHONE16["viewport"], has_touch=True,
                    user_agent=_IPHONE16["user_agent"],
                )
                out["engine"] = "webkit"
            except Exception as e:  # noqa: BLE001
                out["webkit_launch_error"] = str(e)[:120]
                if browser is not None:
                    try:
                        browser.close()
                    except Exception:
                        pass
                browser = None
                ctx = None
        if ctx is None:
            if chrome is None:
                return {"fatal": "WebKit unusable and no Chromium fallback"}
            # CHROMIUM-EMULATED iPhone-16 — NOT a true WebKit run. Full device params.
            out["engine"] = "chromium-emulated"
            browser = p.chromium.launch(
                executable_path=chrome, headless=True,
                args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
            )
            ctx = browser.new_context(**_IPHONE16)
        page = ctx.new_page()
        page.on("pageerror", lambda exc: errors.append("pageerror: " + str(exc)))
        _boot_page(page)

        out["window_rows"] = _row_count(page)
        out["first_tickers"] = _tickers_in_body(page)[:2]

        # Touch/scroll updates the virtual window.
        page.eval_on_selector("#r-scroll", "el => { el.scrollTop = 6000; el.dispatchEvent(new Event('scroll')); }")
        page.wait_for_timeout(300)
        out["tickers_after_scroll"] = _tickers_in_body(page)[:2]
        page.eval_on_selector("#r-scroll", "el => { el.scrollTop = 0; el.dispatchEvent(new Event('scroll')); }")
        page.wait_for_timeout(250)

        # Search dropdown usable; selecting scrolls to the row.
        page.fill("#r-search", "TK0042")
        page.wait_for_timeout(400)
        out["dd_count"] = page.locator("#r-search-dd .search-dd-item").count()
        page.keyboard.press("Enter")
        page.wait_for_timeout(400)
        out["selected_in_dom"] = page.locator("#rank-row-TK0042").count()

        # Card opens.
        if out["selected_in_dom"]:
            page.click("#rank-row-TK0042")
            page.wait_for_timeout(450)
            out["card_open"] = page.locator("#detail-row-TK0042").count()
        else:
            out["card_open"] = 0

        ctx.close()
        browser.close()
    out["errors"] = errors
    return out


def _evaluate_mobile(r: dict) -> list[str]:
    fails = []
    if r.get("fatal"):
        return [r["fatal"]]
    if r["errors"]:
        fails.append("JS errors: " + "; ".join(r["errors"][:3]))
    if not (0 < r.get("window_rows", 0) < 100):
        fails.append("mobile: virtualized DOM should hold < 100 rows; got %r" % r.get("window_rows"))
    if r.get("first_tickers", [None])[0] != "TK0001":
        fails.append("mobile: first row should be TK0001; got %r" % r.get("first_tickers"))
    if r.get("tickers_after_scroll") == r.get("first_tickers"):
        fails.append("mobile: touch-scroll should update the window")
    if r.get("dd_count", 0) < 1:
        fails.append("mobile: search dropdown should show a match for TK0042")
    if r.get("selected_in_dom", 0) < 1:
        fails.append("mobile: selecting a match should scroll TK0042 into the window")
    if r.get("card_open", 0) < 1:
        fails.append("mobile: a detail card should open")
    return fails


# ── pytest entries ────────────────────────────────────────────────────────────
@pytest.mark.skipif(_chrome_path() is None, reason="no Chromium binary")
def test_screener_virtualization_desktop():
    fails = _evaluate_desktop(_run_desktop())
    assert not fails, "\n".join(fails)


@pytest.mark.skipif(_chrome_path() is None and _webkit_path() is None,
                    reason="no usable browser binary (no chromium fallback, no webkit)")
def test_screener_virtualization_iphone16():
    r = _run_mobile()
    fails = _evaluate_mobile(r)
    # Surface which engine was actually used (true WebKit vs chromium-emulated).
    assert not fails, ("engine=%s\n" % r.get("engine")) + "\n".join(fails)


# ── standalone entry ──────────────────────────────────────────────────────────
def main() -> int:
    rc = 0
    print("=== DESKTOP ===")
    rd = _run_desktop()
    for k in ("count_label", "window_rows_initial", "first_tickers",
              "window_rows_after_scroll", "tickers_after_scroll", "first_after_sort_desc",
              "deep_in_dom", "deep_flashed", "detail_open", "overlay_requested",
              "card_has_vetter"):
        print("%-26s:" % k, rd.get(k))
    fd = _evaluate_desktop(rd)
    for f in fd:
        print("FAIL:", f)
    rc |= 1 if fd else 0

    print("\n=== MOBILE (iPhone-16) ===")
    rm = _run_mobile()
    print("engine:", rm.get("engine"))
    for k in ("window_rows", "first_tickers", "tickers_after_scroll",
              "dd_count", "selected_in_dom", "card_open"):
        print("%-26s:" % k, rm.get(k))
    fm = _evaluate_mobile(rm)
    for f in fm:
        print("FAIL:", f)
    rc |= 1 if fm else 0

    print("\n=== RESULT:", "FAIL" if rc else "PASS", "===")
    return rc


if __name__ == "__main__":
    sys.exit(main())
