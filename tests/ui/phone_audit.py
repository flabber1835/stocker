#!/usr/bin/env python3
"""Shared iPhone-X layout audit for a dashboard tab.

The dashboard is phone-first, and layout only exists in a browser — no Python
suite can see a sideways-scrolling page, an orphan heading or a ragged tile
row. This module serves the REAL html/css/js from the repo (no running stack,
no database), stubs the tab's API calls, and drives it at 375x812 DPR 3.

Per-tab drivers (lab_iphone.py, review_iphone.py) supply a TabSpec and their
payload variants; every layout assertion lives here so the tabs cannot drift
apart in what they are held to.
"""
from __future__ import annotations

import functools
import http.server
import json
import os
import socket
import socketserver
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHROMIUM = os.getenv("PW_CHROMIUM", "/opt/pw-browsers/chromium")

# iPhone X — the reference device for this dashboard.
IPHONE_X = {"width": 375, "height": 812}
DPR = 3
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1")

MIN_FONT_PX = 10
MIN_TAP_PX = 36


@dataclass
class TabSpec:
    """What differs between tabs. Everything else is asserted identically."""
    name: str                      # "lab" / "review" — used in screenshot names
    nav_id: str                    # bottom-nav button to click
    screen_id: str                 # the <section> that holds the tab
    ready_selector: str            # element whose text signals "loaded"
    header_id: str                 # sticky header/status element
    body_selector: str             # element whose inner_text is the content
    # substrings that MUST appear per variant label — a blank tab passes every
    # layout check, so this is what proves the real screen rendered
    expects: dict[str, list[str]] = field(default_factory=dict)
    # extra per-tab checks: fn(page, checks, label) -> None
    extra: list = field(default_factory=list)
    min_body_chars: int = 80


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve_dashboard() -> tuple[str, socketserver.TCPServer]:
    """Serve the REAL index HTML + static assets. No app, no DB."""
    sys.path.insert(0, str(ROOT / "services" / "dashboard"))
    from app.main import _HTML                              # noqa: E402

    # A temp docroot, never inside the repo: the harness must not leave build
    # droppings in a working tree that gets committed and deployed.
    docroot = Path(tempfile.mkdtemp(prefix="pw-dash-"))
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


def route_api(route, payloads: dict):
    """Fulfil each /api/* call from `payloads` ({url_fragment: obj}); anything
    else gets an empty, well-formed JSON object so the page's other pollers
    neither hang nor error."""
    url = route.request.url
    for fragment, body in payloads.items():
        if fragment in url:
            return route.fulfill(status=200, content_type="application/json",
                                 body=json.dumps(body, default=str))
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


def audit_tab(page, c: Checks, spec: TabSpec, label: str, shots: Path | None) -> str:
    vw, vh = IPHONE_X["width"], IPHONE_X["height"]

    page.click(f"#{spec.nav_id}")
    page.wait_for_timeout(400)
    page.wait_for_function(
        "(sel) => { const b = document.querySelector(sel);"
        " return b && b.textContent && !/Loading/.test(b.textContent); }",
        arg=spec.ready_selector, timeout=8000)

    if shots:
        shots.mkdir(parents=True, exist_ok=True)
        stem = f"{spec.name}_iphonex_{label}"
        page.screenshot(path=str(shots / f"{stem}.png"), full_page=False)
        page.screenshot(path=str(shots / f"{stem}_full.png"), full_page=True)

    # 1. THE cardinal mobile failure: the page itself scrolls sideways, which
    # drags the sticky bars and bottom nav off-screen.
    doc_w, win_w = page.evaluate(
        "() => [Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),"
        " window.innerWidth]")
    c.check(doc_w <= win_w + 1,
            f"[{label}] page does not scroll horizontally "
            f"(scrollWidth {doc_w} <= viewport {win_w})")

    # 2. No element pokes past the right edge — EXCEPT inside a horizontal
    # scroll container, which is the CORRECT way to carry wide content on a
    # phone (the Lab leaderboard is deliberately wider than 375px).
    overflow = page.evaluate(
        """([sel, vw]) => {
             const inScroller = (el) => {
               for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
                 if (['auto','scroll'].includes(getComputedStyle(p).overflowX)) return true;
               }
               return false;
             };
             return Array.from(document.querySelectorAll(sel + ' *'))
               .filter(el => el.getBoundingClientRect().width > 0)
               .filter(el => el.getBoundingClientRect().right > vw + 1)
               .filter(el => !inScroller(el))
               .map(el => `${el.tagName}#${el.id}.${String(el.className).slice(0,40)}`
                          + ` right=${Math.round(el.getBoundingClientRect().right)}`)
               .slice(0, 6);
           }""", [f"#{spec.screen_id}", vw])
    c.check(not overflow,
            f"[{label}] nothing overflows the {vw}px viewport outside a scroll container"
            + (f" — offenders: {overflow}" if overflow else ""))

    # 3. Bottom nav visible and fully on-screen (it is how you leave the tab).
    nav = page.evaluate(
        "() => { const n = document.getElementById('bnav');"
        " if (!n) return null; const r = n.getBoundingClientRect();"
        " const s = getComputedStyle(n);"
        " return {top: r.top, left: r.left, right: r.right,"
        "         display: s.display, visibility: s.visibility}; }")
    c.check(bool(nav) and nav["display"] != "none" and nav["visibility"] != "hidden",
            f"[{label}] bottom nav is rendered")
    if nav:
        c.check(nav["left"] >= -1 and nav["right"] <= vw + 1,
                f"[{label}] bottom nav fits the viewport width")
        c.check(nav["top"] < vh,
                f"[{label}] bottom nav is on-screen (top {round(nav['top'])} < {vh})")

    # 4. The tab's sticky header is visible and inside the viewport.
    sub = page.evaluate(
        "(id) => { const e = document.getElementById(id);"
        " if (!e) return null; const r = e.getBoundingClientRect();"
        " return {top: r.top, right: r.right}; }", spec.header_id)
    c.check(bool(sub) and 0 <= sub["top"] < vh and sub["right"] <= vw + 1,
            f"[{label}] {spec.name} header bar is visible and within the viewport")

    # 5. Legibility: nothing rendered below MIN_FONT_PX.
    tiny = page.evaluate(
        """([sel, minpx]) => Array.from(document.querySelectorAll(sel + ' *'))
             .filter(el => el.textContent && el.textContent.trim()
                        && el.getBoundingClientRect().height > 0
                        && !el.querySelector('*'))
             .map(el => ({px: parseFloat(getComputedStyle(el).fontSize),
                          t: el.textContent.trim().slice(0, 30)}))
             .filter(o => o.px && o.px < minpx)
             .slice(0, 5)""", [f"#{spec.screen_id}", MIN_FONT_PX])
    c.check(not tiny, f"[{label}] no text under {MIN_FONT_PX}px"
                      + (f" — {tiny}" if tiny else ""))

    # 6. Tap targets: nav buttons must be comfortably tappable.
    small = page.evaluate(
        """(minpx) => Array.from(document.querySelectorAll('#bnav .nav-btn'))
             .map(el => ({id: el.id, w: el.getBoundingClientRect().width,
                          h: el.getBoundingClientRect().height}))
             .filter(o => o.h < minpx || o.w < minpx)""", MIN_TAP_PX)
    c.check(not small, f"[{label}] nav tap targets >= {MIN_TAP_PX}px"
                       + (f" — {small}" if small else ""))

    # 7. Content actually rendered. Every check above passes on a BLANK tab, so
    # this is what proves the real screen is on-screen and not a fallback.
    body_text = page.inner_text(spec.body_selector)
    c.check(len(body_text) > spec.min_body_chars,
            f"[{label}] {spec.name} body rendered real content ({len(body_text)} chars)")
    expect = spec.expects.get(label, [])
    missing = [s for s in expect if s not in body_text]
    c.check(not missing, f"[{label}] variant-specific content present"
                         + (f" — missing {missing}" if missing else ""))

    # 8. No section heading left standing with nothing under it — a heading
    # emitted unconditionally and only filled when data exists reads as a
    # broken render rather than "no data yet".
    orphan = page.evaluate(
        """(sel) => Array.from(document.querySelectorAll(sel + ' h3'))
             .filter(h => {
               const n = h.nextElementSibling;
               return !n || !n.textContent.trim() || n.tagName === 'H3';
             })
             .map(h => h.textContent.trim())""", f"#{spec.screen_id}")
    c.check(not orphan, f"[{label}] no empty section heading"
                        + (f" — {orphan} has nothing under it" if orphan else ""))

    # 9. Relative ages must never render negative: the timestamps come from the
    # NAS while Date.now() is the PHONE's clock, and skew printed "-746m ago".
    import re
    neg = [ln for ln in body_text.splitlines() if re.search(r"-\d+[mhd] ago", ln)]
    c.check(not neg, f"[{label}] no negative relative ages"
                     + (f" — {neg[:2]}" if neg else ""))

    # 10. Stat tiles must not go ragged: a value wrapping mid-token makes one
    # tile taller than its row-mates and the grid reads as broken.
    ragged = page.evaluate(
        """(sel) => { const t = Array.from(document.querySelectorAll(sel + ' .stat'));
             if (t.length < 2) return null;
             const rows = {};
             t.forEach(el => { const r = Math.round(el.getBoundingClientRect().top);
                               (rows[r] = rows[r] || []).push(el); });
             const bad = [];
             Object.values(rows).forEach(g => {
               const hs = g.map(e => Math.round(e.getBoundingClientRect().height));
               if (Math.max(...hs) - Math.min(...hs) > 2)
                 bad.push(g.map((e, i) => ((e.querySelector('.stat-k') || {}).textContent)
                                          + '=' + hs[i]).join(', '));
             });
             return bad; }""", f"#{spec.screen_id}")
    if ragged is not None:
        c.check(not ragged, f"[{label}] stat tiles are the same height per row"
                            + (f" — ragged: {ragged}" if ragged else ""))

    # 11. A horizontal scroll container is only legitimate around a WIDE TABLE.
    # Check 2 exempts everything inside such a container, which on a text-only
    # tab silently disabled it: the Review tab's whole body sits in a
    # .tbl-scroll, so long dotted config paths pushed it to scroll sideways and
    # CLIPPED the evidence text while every assertion passed. Text must never
    # require horizontal scrolling.
    text_scrollers = page.evaluate(
        """(sel) => Array.from(document.querySelectorAll(sel + ' *'))
             .filter(e => ['auto','scroll'].includes(getComputedStyle(e).overflowX))
             .filter(e => e.scrollWidth > e.clientWidth + 1)
             .filter(e => !e.querySelector('table'))
             .map(e => `${String(e.className).slice(0,30)} `
                       + `scrollWidth=${e.scrollWidth} > clientWidth=${e.clientWidth}`)
             .slice(0, 4)""", f"#{spec.screen_id}")
    c.check(not text_scrollers,
            f"[{label}] no text-only container scrolls horizontally (content would be clipped)"
            + (f" — {text_scrollers}" if text_scrollers else ""))

    for fn in spec.extra:
        fn(page, c, label)
    return body_text


def run(spec: TabSpec, variants: list[tuple[str, dict]], *,
        headed: bool = False, shots: Path | None = None) -> int:
    """Drive `spec` across `variants` = [(label, {url_fragment: payload})]."""
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

            for label, payloads in variants:
                page.unroute("**/api/**")
                page.route("**/api/**", functools.partial(route_api, payloads=payloads))
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(300)
                print(f"\n── {spec.name} tab @ iPhone X ({label}) ──")
                audit_tab(page, c, spec, label, shots)

            print("\n── page errors ──")
            c.check(not console_errors,
                    f"no uncaught JS errors while rendering the {spec.name} tab"
                    + (f" — {console_errors[:3]}" if console_errors else ""))
            browser.close()
    finally:
        httpd.shutdown()

    print(f"\n{c.passes} passed, {len(c.failures)} failed")
    for f in c.failures:
        print(f"  FAILED: {f}")
    return 1 if c.failures else 0
