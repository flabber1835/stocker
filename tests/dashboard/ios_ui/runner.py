"""
iOS UI intent runner — drives the mock dashboard with Playwright at iPhone
viewport and asserts each Intent.

This is a standalone runner (not pytest) so output is one line per intent and
the dashboard server is restarted only once per scenario.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from tests.dashboard.ios_ui.intents import INTENTS, SCENARIOS  # noqa: E402

PORT = int(os.getenv("MOCK_DASH_PORT", "8770"))
URL = f"http://127.0.0.1:{PORT}"

PANEL_TO_NAV = {
    "screener": "SCREENER",
    "trader":   "TRADER",
    "portfolio": "PORTFOLIO",
}


def _start_server(scenario: str) -> subprocess.Popen:
    env = {**os.environ, "STOCKER_SCENARIO": scenario}
    p = subprocess.Popen(
        [sys.executable, str(ROOT / "tests" / "dashboard" / "ios_ui" / "mock_dashboard.py"),
         str(PORT)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    # Wait for it to come up
    import urllib.request
    for _ in range(40):
        try:
            urllib.request.urlopen(f"{URL}/health", timeout=0.3)
            return p
        except Exception:
            time.sleep(0.1)
    p.terminate()
    raise RuntimeError(f"mock dashboard didn't start: stderr={p.stderr.read().decode()[:500]}")


def _stop_server(p: subprocess.Popen):
    try:
        p.terminate()
        p.wait(timeout=3)
    except Exception:
        p.kill()


def _navigate_to_panel(page, panel: str) -> None:
    nav_text = PANEL_TO_NAV[panel]
    page.locator(f"#bnav button:has-text('{nav_text}')").click()
    # Give a moment for the panel's data fetches to settle
    page.wait_for_timeout(800)


def _check_intent(page, intent) -> list[str]:
    """Return a list of failure messages (empty = pass)."""
    failures = []
    for sel in intent.must_show:
        if not page.locator(sel).is_visible():
            failures.append(f"must_show {sel} but it's hidden")
    for sel in intent.must_hide:
        if page.locator(sel).is_visible():
            failures.append(f"must_hide {sel} but it's visible")
    for sel in intent.must_be_disabled:
        loc = page.locator(sel)
        if loc.count() == 0:
            failures.append(f"must_be_disabled {sel} — element not found")
        elif not loc.evaluate("el => el.disabled"):
            failures.append(f"must_be_disabled {sel} but it's enabled")
    for sel in intent.must_be_enabled:
        loc = page.locator(sel)
        if loc.count() == 0:
            failures.append(f"must_be_enabled {sel} — element not found")
        elif loc.evaluate("el => el.disabled"):
            failures.append(f"must_be_enabled {sel} but it's disabled")

    body_text = page.locator("body").inner_text()
    for needle in intent.must_contain_text:
        if needle not in body_text:
            failures.append(f"must_contain_text {needle!r} — not found")
    for needle in intent.must_not_contain_text:
        if needle in body_text:
            failures.append(f"must_not_contain_text {needle!r} — found")

    if intent.custom_check is not None:
        ok, msg = intent.custom_check(page)
        if not ok:
            failures.append(msg.strip())

    return failures


def main():
    from playwright.sync_api import sync_playwright

    # Group intents by scenario so we restart the mock once per scenario
    by_scenario = defaultdict(list)
    for it in INTENTS:
        by_scenario[it.scenario].append(it)

    pass_count = 0
    fail_count = 0
    failures = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        for scenario, intents in by_scenario.items():
            print(f"\n┌── Scenario: {scenario}")
            srv = _start_server(scenario)
            try:
                ctx = browser.new_context(viewport={"width": 390, "height": 844})
                page = ctx.new_page()
                page.goto(URL)
                page.wait_for_load_state("networkidle")
                page.wait_for_timeout(800)

                for intent in intents:
                    _navigate_to_panel(page, intent.panel)
                    fs = _check_intent(page, intent)
                    if not fs:
                        pass_count += 1
                        print(f"│ ✓ {intent.name}")
                    else:
                        fail_count += 1
                        print(f"│ ✗ {intent.name}")
                        for f in fs:
                            print(f"│     {f}")
                        # Save a screenshot for first 5 failures
                        if len(failures) < 5:
                            sp = f"/tmp/fail_{intent.name}.png"
                            page.screenshot(path=sp)
                            failures.append((intent.name, fs, sp))

                ctx.close()
            finally:
                _stop_server(srv)

        browser.close()

    total = pass_count + fail_count
    print(f"\n══ Result: {pass_count}/{total} intents pass, {fail_count} fail")
    if failures:
        print(f"\nScreenshots saved for first {len(failures)} failures:")
        for name, _, path in failures:
            print(f"  {path} — {name}")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
