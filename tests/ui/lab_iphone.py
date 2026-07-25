#!/usr/bin/env python3
"""Playwright layout check for the Lab tab on an iPhone X.

The dashboard is used from a phone, and the Lab tab is the densest screen in it
(a running experiment's live stats, the weekly-cap strip, a schedule list and a
6-column leaderboard table). Wide tables are exactly what breaks a 375px
viewport: the usual failure is the PAGE scrolling sideways, which drags the
sticky bars and bottom nav off-screen and makes every other tab feel broken too.

This serves the REAL html/css/js from the repo (no running stack) with
/api/bt/status stubbed, drives the Lab tab at 375x812 DPR3, and asserts the
layout properties that actually matter on a phone:

  * the page body never scrolls horizontally (wide content scrolls in its own box)
  * nothing overflows the viewport width
  * the bottom nav and sticky filter bar stay visible and on-screen
  * text stays legible (no sub-10px font)
  * tap targets meet a usable minimum
  * the leaderboard is reachable by scrolling ITS container, not the page

Run standalone:  python tests/ui/lab_iphone.py [--headed] [--shots DIR]
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import os
import socket
import socketserver
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHROMIUM = os.getenv("PW_CHROMIUM", "/opt/pw-browsers/chromium")

# iPhone X — the reference device for this dashboard.
IPHONE_X = {"width": 375, "height": 812}
DPR = 3
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1")

# A deliberately DEMANDING payload: long hypothesis text, a full leaderboard,
# long config diffs — the shapes most likely to blow out a narrow viewport.
# /api/bt/status answers {"status": <status.json>, "sweep": <latest_sweep.json>}
# — the Lab reads coverage/experiments from d.status, NOT from the top level.
# Getting this wrong renders the "no artifacts yet" fallback, which passes
# every layout check while showing none of the real screen; the
# variant-content assertion in audit_lab is what catches that.
def _ago(minutes: int) -> str:
    """Timestamps must be relative to the BROWSER's clock or every rendered age
    is nonsense (a hardcoded one produced '-746m ago' and hid a real bug)."""
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


BT_STATUS_INNER = {
    "generated_at": _ago(4),
    "scheduler": {"last_tick": _ago(3), "last_topup": _ago(600),
                  "last_sweep_fire": None, "last_export": _ago(900),
                  "notes": ["experiment fired (full_config) sweep 9f2c1a44 "
                            "tune 2023-07-25→2025-07-25 validate 2025-07-25→2026-07-25",
                            "no promotion for 2f1c9a03: tune CAGR edge -0.0042 "
                            "< margin +0.0100"]},
    "sweep_latest": {"status": "success", "n_done": 27, "n_configs": 27,
                     "tune_start": "2023-07-25", "tune_end": "2025-07-25",
                     "validate_start": "2025-07-25", "validate_end": "2026-07-25",
                     "error_message": None},
    "coverage": {"go": True, "prices": {"rows": 35009761, "tickers": 17781,
                                        "date_min": "2004-01-02", "date_max": "2026-07-24"},
                 "fundamentals": {"rows": 488689}, "earliest_viable_start": "2005-01-03"},
    "coverage_as_of": _ago(5),
    "experiments": {
        "running": None,
        "queued": [
            {"kind": "full_config",
             "hypothesis": "concentrating to 17 names raises expected compounded return "
                           "because cap_blocked candidates have outperformed selected "
                           "ones for three consecutive weeks"},
            {"kind": "full_config", "hypothesis": "tighter knife limit cuts the drawdown tail"},
        ],
        "schedule": [
            {"when": "2026-07-25T22:00", "kind": "full_config",
             "thesis": "concentrating to 17 names raises expected compounded return",
             "note": None},
            {"when": "2026-07-26T22:00", "kind": "full_config",
             "thesis": "tighter knife limit cuts the drawdown tail",
             "note": "after weekly cap resets"},
        ],
        "recent": [
            {"kind": "baseline", "status": "success", "hypothesis": "BASELINE: active config",
             "cagr": 0.1421, "promotion": None, "completed_at": _ago(1200)},
            {"kind": "full_config", "status": "success",
             "hypothesis": "momentum 0.42 -> 0.55 with earnings_surprise at 0.12",
             "cagr": 0.1180,
             "promotion": "edge does NOT survive validation: out-of-sample CAGR -0.0300 "
                          "vs baseline (tol 0.0000)",
             "completed_at": _ago(2600)},
        ],
        "next_fire_local": "2026-07-25T22:00-04:00",
        "fired_this_week": 0,
        "baselines_this_week": 3,
        "week_cap": 5,
        "window_years": 3,
        "validate_months": 12,
        "last_promotion": None,
        "promotion_applied": None,
    },
}

SWEEP = {
    "sweep_id": "9f2c1a44-0000-4000-8000-000000000000",
    "status": "success", "generated_at": _ago(1500),
    "n_configs": 27,
    "leaderboard": [
        {"config_idx": i,
         "config_diff": {"static_factor_weights.momentum": 0.30 + i * 0.01,
                         "portfolio_builder.max_positions": 20 + i},
         "oos_sharpe": 1.05 - i * 0.03, "is_sharpe": 1.4 - i * 0.02,
         "oos_return": 0.19 - i * 0.01, "oos_max_drawdown": -0.22 - i * 0.005,
         "overfit_gap": 0.35 + i * 0.05}
        for i in range(15)
    ],
}

BT_STATUS = {"status": BT_STATUS_INNER, "sweep": SWEEP}

# CLOCK SKEW: the NAS writes the timestamps, the PHONE renders the ages. A NAS
# clock a little ahead used to print "-746m ago", which reads as a dead bridge.
BT_STATUS_SKEWED = json.loads(json.dumps(BT_STATUS))
BT_STATUS_SKEWED["status"]["generated_at"] = _ago(-45)
BT_STATUS_SKEWED["status"]["coverage_as_of"] = _ago(-45)
BT_STATUS_SKEWED["status"]["scheduler"]["last_tick"] = _ago(-45)

# A running experiment — the wider variant (live stat tiles + progress).
BT_STATUS_RUNNING = json.loads(json.dumps(BT_STATUS))
BT_STATUS_RUNNING["status"]["experiments"]["running"] = {
    "kind": "full_config",
    "hypothesis": "concentrating to 17 names raises expected compounded return",
    "fired_at": _ago(95),
    "windows": {"tune_start": "2023-07-25", "tune_end": "2025-07-25",
                "validate_start": "2025-07-25", "validate_end": "2026-07-25"},
    "progress_pct": 42,
    "live": {"phase": "tune", "as_of": "2024-11-08", "equity": 137421.55, "total_return": 0.3742,
             "annualized_return": 0.1638, "max_drawdown": -0.2413,
             "benchmark_total_return": 0.2510, "n_trades": 418, "n_positions": 17},
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve_dashboard() -> tuple[str, socketserver.TCPServer]:
    """Serve the REAL index HTML + static assets, no app/DB required."""
    sys.path.insert(0, str(ROOT / "services" / "dashboard"))
    from app.main import _HTML                              # noqa: E402

    # A temp docroot, never inside the repo: the harness must not leave build
    # droppings in a working tree that gets committed and deployed.
    import tempfile
    docroot = Path(tempfile.mkdtemp(prefix="pw-lab-"))
    (docroot / "static").mkdir(parents=True, exist_ok=True)
    (docroot / "index.html").write_text(_HTML)
    for f in ("dashboard.js", "dashboard.css"):
        (docroot / "static" / f).write_text(
            (ROOT / "services" / "dashboard" / "static" / f).read_text())

    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(docroot))
    handler.log_message = lambda *a, **k: None  # type: ignore[attr-defined]
    port = _free_port()
    httpd = socketserver.TCPServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{port}/index.html", httpd


def _route_api(route, status_payload):
    url = route.request.url
    if "/api/bt/status" in url:
        return route.fulfill(status=200, content_type="application/json",
                             body=json.dumps(status_payload))
    # Everything else the page polls: an empty, well-formed answer.
    return route.fulfill(status=200, content_type="application/json", body="{}")


class Checks:
    def __init__(self):
        self.failures: list[str] = []
        self.passes = 0

    def check(self, ok: bool, msg: str):
        if ok:
            self.passes += 1
            print(f"  OK   {msg}")
        else:
            self.failures.append(msg)
            print(f"  FAIL {msg}")
        return ok


def audit_lab(page, c: Checks, label: str, shots: Path | None):
    vw = IPHONE_X["width"]

    page.click("#nav-lab")
    page.wait_for_timeout(400)
    page.wait_for_function(
        "() => { const b = document.getElementById('lab-body');"
        " return b && !/Loading/.test(b.textContent); }", timeout=8000)

    if shots:
        shots.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(shots / f"lab_iphonex_{label}.png"), full_page=False)
        page.screenshot(path=str(shots / f"lab_iphonex_{label}_full.png"), full_page=True)

    # 1. THE cardinal mobile failure: the page itself scrolls sideways.
    doc_w, win_w = page.evaluate(
        "() => [Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),"
        " window.innerWidth]")
    c.check(doc_w <= win_w + 1,
            f"[{label}] page does not scroll horizontally "
            f"(scrollWidth {doc_w} <= viewport {win_w})")

    # 2. No element pokes past the right edge — EXCEPT inside a horizontal
    # scroll container, which is the correct way to carry a wide table on a
    # phone (the leaderboard is deliberately wider than 375px and scrolls in
    # its own box; check 7 verifies that separately).
    overflow = page.evaluate(
        """(vw) => {
             const inScroller = (el) => {
               for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
                 if (['auto','scroll'].includes(getComputedStyle(p).overflowX)) return true;
               }
               return false;
             };
             return Array.from(document.querySelectorAll('#screen-lab *'))
               .filter(el => el.getBoundingClientRect().width > 0)
               .filter(el => el.getBoundingClientRect().right > vw + 1)
               .filter(el => !inScroller(el))
               .map(el => `${el.tagName}#${el.id}.${String(el.className).slice(0,40)}`
                          + ` right=${Math.round(el.getBoundingClientRect().right)}`)
               .slice(0, 6);
           }""", vw)
    c.check(not overflow,
            f"[{label}] nothing overflows the 375px viewport outside a scroll container"
            + (f" — offenders: {overflow}" if overflow else ""))

    # 3. Bottom nav visible and fully on-screen (it is how you leave the tab).
    nav = page.evaluate(
        "() => { const n = document.getElementById('bnav');"
        " if (!n) return null; const r = n.getBoundingClientRect();"
        " const s = getComputedStyle(n);"
        " return {top: r.top, bottom: r.bottom, left: r.left, right: r.right,"
        "         display: s.display, visibility: s.visibility}; }")
    c.check(bool(nav) and nav["display"] != "none" and nav["visibility"] != "hidden",
            f"[{label}] bottom nav is rendered")
    if nav:
        c.check(nav["left"] >= -1 and nav["right"] <= vw + 1,
                f"[{label}] bottom nav fits the viewport width")
        c.check(nav["top"] < IPHONE_X["height"],
                f"[{label}] bottom nav is on-screen (top {round(nav['top'])} "
                f"< {IPHONE_X['height']})")

    # 4. The Lab's sticky header is visible in the viewport.
    sub = page.evaluate(
        "() => { const e = document.getElementById('lab-sub');"
        " if (!e) return null; const r = e.getBoundingClientRect();"
        " return {top: r.top, bottom: r.bottom, right: r.right}; }")
    c.check(bool(sub) and 0 <= sub["top"] < IPHONE_X["height"] and sub["right"] <= vw + 1,
            f"[{label}] Lab header bar is visible and within the viewport")

    # 5. Legibility: no rendered text below 10px in the Lab.
    tiny = page.evaluate(
        """() => Array.from(document.querySelectorAll('#screen-lab *'))
             .filter(el => el.textContent && el.textContent.trim()
                        && el.getBoundingClientRect().height > 0
                        && !el.querySelector('*'))
             .map(el => ({px: parseFloat(getComputedStyle(el).fontSize),
                          t: el.textContent.trim().slice(0, 30)}))
             .filter(o => o.px && o.px < 10)
             .slice(0, 5)""")
    c.check(not tiny, f"[{label}] no text under 10px" + (f" — {tiny}" if tiny else ""))

    # 6. Tap targets: nav buttons must be comfortably tappable.
    small = page.evaluate(
        """() => Array.from(document.querySelectorAll('#bnav .nav-btn'))
             .map(el => ({id: el.id, w: el.getBoundingClientRect().width,
                          h: el.getBoundingClientRect().height}))
             .filter(o => o.h < 36 || o.w < 36)""")
    c.check(not small, f"[{label}] nav tap targets >= 36px"
                       + (f" — {small}" if small else ""))

    # 7. Content actually rendered — a BLANK tab passes every layout check
    # above, so assert the variant-specific content is really on screen.
    body_text = page.inner_text("#lab-body")
    c.check(len(body_text) > 80, f"[{label}] Lab body rendered real content "
                                 f"({len(body_text)} chars)")
    expect = {
        "idle": ["none running", "candidates fired this week", "baseline"],
        "running": ["running", "thesis:"],
        "clock-skew": ["none running", "just now"],
    }[label]
    missing = [s for s in expect if s not in body_text]
    c.check(not missing, f"[{label}] variant-specific content present"
                         + (f" — missing {missing}" if missing else ""))

    # 8. No section heading left standing with nothing under it. `Automation`
    # emitted its <h3> unconditionally and only filled it when the scheduler
    # block was present, so a status artifact without it showed a bare orphan
    # heading — which reads as a broken render, not "no data yet".
    orphan = page.evaluate(
        """() => Array.from(document.querySelectorAll('#lab-body .lab-h'))
             .filter(h => {
               const n = h.nextElementSibling;
               return !n || !n.textContent.trim() || n.classList.contains('lab-h');
             })
             .map(h => h.textContent.trim())""")
    c.check(not orphan, f"[{label}] no empty section heading"
                        + (f" — {orphan} has nothing under it" if orphan else ""))

    # 9. Relative ages must never render negative. The timestamps come from the
    # NAS while Date.now() is the PHONE's clock; a few minutes of skew produced
    # "-746m ago", which reads as a broken bridge when nothing is wrong.
    neg = [ln for ln in body_text.splitlines() if "-" in ln and "m ago" in ln
           and any(f"-{d}" in ln for d in "0123456789")]
    neg = [ln for ln in neg if __import__("re").search(r"-\d+[mhd] ago", ln)]
    c.check(not neg, f"[{label}] no negative relative ages"
                     + (f" — {neg[:2]}" if neg else ""))

    # 10. Live-stat tiles must not go ragged: a value that wraps mid-token
    # ("2024-11-" / "08") makes one tile taller than its row-mates and the grid
    # reads as broken on a narrow screen.
    ragged = page.evaluate(
        """() => { const t = Array.from(document.querySelectorAll('#lab-body .stat'));
             if (t.length < 2) return null;
             const rows = {};
             t.forEach(el => { const r = Math.round(el.getBoundingClientRect().top);
                               (rows[r] = rows[r] || []).push(el); });
             const bad = [];
             Object.values(rows).forEach(g => {
               const hs = g.map(e => Math.round(e.getBoundingClientRect().height));
               if (Math.max(...hs) - Math.min(...hs) > 2)
                 bad.push(g.map((e, i) => (e.querySelector('.stat-k') || {}).textContent
                                          + '=' + hs[i]).join(', '));
             });
             return bad; }""")
    if ragged is not None:
        c.check(not ragged, f"[{label}] live-stat tiles are the same height per row"
                            + (f" — ragged: {ragged}" if ragged else ""))
    return body_text


def audit_leaderboard(page, c: Checks):
    """The 6-column leaderboard is the widest thing on the screen: it must
    scroll inside its OWN container, never widen the page."""
    info = page.evaluate(
        """() => { const t = document.querySelector('#screen-lab .lab-tbl');
             if (!t) return null;
             let box = t.parentElement, scroller = null;
             while (box && box !== document.body) {
               const s = getComputedStyle(box);
               if (['auto','scroll'].includes(s.overflowX)) { scroller = box; break; }
               box = box.parentElement;
             }
             return {tableW: t.scrollWidth,
                     scrollerW: scroller ? scroller.clientWidth : null,
                     canScroll: scroller ? scroller.scrollWidth > scroller.clientWidth + 1 : false,
                     hasScroller: !!scroller,
                     scrollerCls: scroller ? String(scroller.className).slice(0,40) : null}; }""")
    c.check(info is not None, "[leaderboard] table rendered")
    if not info:
        return
    if info["tableW"] > IPHONE_X["width"]:
        c.check(info["hasScroller"] and info["canScroll"],
                f"[leaderboard] wide table ({info['tableW']}px) scrolls inside its own "
                f"container ({info['scrollerCls']}), not the page")
    else:
        c.check(True, f"[leaderboard] table fits the viewport ({info['tableW']}px)")


def run(headed: bool = False, shots: Path | None = None) -> int:
    from playwright.sync_api import sync_playwright

    url, httpd = serve_dashboard()
    c = Checks()
    console_errors: list[str] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=not headed, executable_path=CHROMIUM,
                args=["--no-sandbox", "--disable-dev-shm-usage"])
            ctx = browser.new_context(viewport=IPHONE_X, device_scale_factor=DPR,
                                      is_mobile=True, has_touch=True, user_agent=UA)
            page = ctx.new_page()
            page.on("pageerror", lambda e: console_errors.append(str(e)))
            page.on("console", lambda m: console_errors.append(m.text)
                    if m.type == "error" else None)

            for label, payload in (("idle", BT_STATUS), ("running", BT_STATUS_RUNNING),
                                   ("clock-skew", BT_STATUS_SKEWED)):
                page.unroute("**/api/**")
                page.route("**/api/**", functools.partial(_route_api,
                                                          status_payload=payload))
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(300)
                print(f"\n── Lab tab @ iPhone X ({label}) ──")
                audit_lab(page, c, label, shots)
                if label == "idle":
                    audit_leaderboard(page, c)

            print("\n── page errors ──")
            c.check(not console_errors,
                    "no uncaught JS errors while rendering the Lab"
                    + (f" — {console_errors[:3]}" if console_errors else ""))
            browser.close()
    finally:
        httpd.shutdown()

    print(f"\n{c.passes} passed, {len(c.failures)} failed")
    for f in c.failures:
        print(f"  FAILED: {f}")
    return 1 if c.failures else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--shots", type=Path, default=None)
    a = ap.parse_args()
    sys.exit(run(headed=a.headed, shots=a.shots))
