"""
iOS UI intent compliance — pytest wrapper around tests/dashboard/ios_ui/runner.py.

Each intent in tests/dashboard/ios_ui/intents.py becomes one parametrized
test case. The mock dashboard server is restarted per scenario (shared
across same-scenario intents via a per-scenario fixture).

Skip the whole module if Playwright or its chromium aren't available so
local pytest runs without the browser still work.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "dashboard" / "ios_ui"))

try:
    from playwright.sync_api import sync_playwright  # noqa: F401
    _HAVE_PW = True
except ImportError:
    _HAVE_PW = False

try:
    from intents import INTENTS  # noqa: E402
except ImportError as e:
    INTENTS = []
    _IMPORT_ERR = str(e)
else:
    _IMPORT_ERR = None


pytestmark = pytest.mark.skipif(
    not _HAVE_PW,
    reason="Playwright not installed (pip install playwright + playwright install chromium)",
)


PORT = 8771  # different from the runner so they don't collide
URL = f"http://127.0.0.1:{PORT}"


# ── per-scenario server fixture ───────────────────────────────────────────────

def _start_mock(scenario: str) -> subprocess.Popen:
    env = {**os.environ, "STOCKER_SCENARIO": scenario}
    env.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
    p = subprocess.Popen(
        [sys.executable,
         str(ROOT / "tests" / "dashboard" / "ios_ui" / "mock_dashboard.py"),
         str(PORT)],
        env=env, cwd="/tmp",
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    for _ in range(50):
        try:
            urllib.request.urlopen(f"{URL}/health", timeout=0.3)
            return p
        except Exception:
            time.sleep(0.1)
    p.terminate()
    err = p.stderr.read(2000).decode()
    raise RuntimeError(f"mock dashboard didn't start: {err}")


def _stop_mock(p: subprocess.Popen):
    try:
        p.terminate()
        p.wait(timeout=3)
    except Exception:
        p.kill()


# One server at a time, on the same port. Switch scenarios by stop+start.
_current_server: dict = {"scenario": None, "proc": None}


@pytest.fixture(scope="module")
def browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        try:
            yield b
        finally:
            b.close()


@pytest.fixture(scope="module", autouse=True)
def _stop_at_end():
    yield
    if _current_server["proc"]:
        _stop_mock(_current_server["proc"])
        _current_server["proc"] = None
        _current_server["scenario"] = None


def _ensure_server(scenario: str):
    if _current_server["scenario"] == scenario and _current_server["proc"]:
        return
    if _current_server["proc"]:
        _stop_mock(_current_server["proc"])
    _current_server["proc"] = _start_mock(scenario)
    _current_server["scenario"] = scenario


PANEL_TO_NAV = {"screener": "SCREENER", "trader": "TRADER", "portfolio": "PORTFOLIO"}


def _navigate(page, panel: str):
    page.locator(f"#bnav button:has-text('{PANEL_TO_NAV[panel]}')").click()
    page.wait_for_timeout(800)


def _check(page, intent) -> list[str]:
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


# Sort intents by scenario so the per-scenario server restarts only when needed
_SORTED_INTENTS = sorted(INTENTS, key=lambda it: it.scenario)


@pytest.mark.parametrize("intent", _SORTED_INTENTS,
                         ids=[it.name for it in _SORTED_INTENTS])
def test_intent(intent, browser):
    """One parametrized test per intent — assert UI matches the codified intent."""
    _ensure_server(intent.scenario)
    ctx = browser.new_context(viewport={"width": 390, "height": 844})
    page = ctx.new_page()
    try:
        page.goto(URL)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(800)
        _navigate(page, intent.panel)
        failures = _check(page, intent)
        if failures:
            pytest.fail(f"Intent violation: {intent.description}\n  "
                        + "\n  ".join(failures))
    finally:
        ctx.close()
