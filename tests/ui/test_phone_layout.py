"""The Lab and Review tabs must render correctly on an iPhone X (375x812).

The dashboard is phone-first and these are its two densest screens — the Lab
carries a leaderboard genuinely wider than the viewport, the Review carries
prose full of dotted config paths, hashes and SQL. Nothing in the Python suites
can see layout; it only exists in a browser.

The drivers (lab_iphone.py / review_iphone.py) are runnable standalone with
--shots to eyeball screenshots; this wrapper is what CI runs. Both skip cleanly
when Playwright or the Chromium build is unavailable.

Defects these found on their first runs:
  * `_aaStatus.pending is not iterable` — a non-200 JSON body from
    /api/auto-approve-status wiped the `pending: []` default and killed the
    refresh loop's tail until a manual page reload
  * a bare "Automation" heading with nothing under it
  * "-746m ago" — negative relative ages from NAS/phone clock skew
  * the Lab's "AS OF" date wrapping mid-value, leaving one stat tile taller
  * the Review's evidence text CLIPPED: long dotted paths pushed the text-only
    .tbl-scroll into horizontal scrolling
  * the Review verdict sitting in a 163px-tall empty box — the `tbl-empty`
    placeholder style was never removed once a report rendered
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
CHROMIUM = Path("/opt/pw-browsers/chromium")


def _have_playwright() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


pytestmark = [
    pytest.mark.skipif(not _have_playwright(), reason="playwright not installed"),
    pytest.mark.skipif(not CHROMIUM.exists(), reason="chromium build unavailable"),
]

# (driver, tab name as printed, variants that must have run)
TABS = [
    ("lab_iphone.py", "lab", ("idle", "engine-busy", "running", "clock-skew")),
    ("review_iphone.py", "review",
     ("full", "running", "failed", "none", "parse-fallback", "clock-skew")),
]


@pytest.mark.parametrize("driver,tab,variants", TABS, ids=[t[1] for t in TABS])
def test_tab_renders_correctly_on_iphone_x(driver, tab, variants):
    res = subprocess.run([sys.executable, str(HERE / driver)], cwd=ROOT,
                         capture_output=True, text=True, timeout=300)
    report = "\n".join(ln for ln in res.stdout.splitlines()
                       if not ln.startswith("127.0.0.1"))
    assert res.returncode == 0, (
        f"{tab} tab layout regressed on iPhone X:\n{report}\n{res.stderr[-2000:]}")
    # Every variant must actually have run — a driver that silently skipped one
    # would still exit 0. (This assertion already caught a header-text drift.)
    for variant in variants:
        assert f"({variant}) ──" in report, f"variant {variant!r} did not run:\n{report}"
    assert "0 failed" in report


def test_both_tabs_share_one_audit():
    """The layout rules must not drift apart per tab: the assertions live in
    phone_audit.py and each driver supplies only payloads + tab-specific
    checks."""
    for driver, _, _ in TABS:
        src = (HERE / driver).read_text()
        assert "from phone_audit import" in src, f"{driver} re-implements the audit"


def test_drivers_are_loadable():
    """A typo in a driver should read as a harness problem, not a UI regression."""
    import ast
    for name in ("phone_audit.py", *(d for d, _, _ in TABS)):
        ast.parse((HERE / name).read_text())
