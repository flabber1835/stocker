"""The Lab tab must render correctly on an iPhone X (375x812).

The dashboard is a phone-first UI and the Lab is its densest screen: live stat
tiles, a weekly-cap strip, a schedule list, and a 6-column leaderboard that is
genuinely wider than the viewport. Nothing in the Python suites can see any of
that — layout only exists in a browser — so this drives the real page with
Playwright.

lab_iphone.py holds the harness (it is also runnable standalone with --shots to
eyeball screenshots); this wrapper is what CI runs. It skips cleanly when
Playwright or the Chromium build is unavailable, so a bare runner is unaffected.

Bugs this caught the first time it ran:
  * `_aaStatus.pending is not iterable` — a non-200 JSON body from
    /api/auto-approve-status wiped the `pending: []` default and killed the
    refresh loop's tail until a manual page reload
  * a bare "Automation" heading with nothing under it whenever the status
    artifact had no scheduler block
  * "-746m ago" — negative relative ages from NAS/phone clock skew
  * the "AS OF" date wrapping mid-value, leaving one live-stat tile taller
    than its row-mates
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HARNESS = Path(__file__).parent / "lab_iphone.py"
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


def test_lab_tab_renders_correctly_on_iphone_x():
    """Runs every layout assertion in the harness across the idle, running and
    clock-skewed variants. Failure output names the exact check and offenders."""
    res = subprocess.run([sys.executable, str(HARNESS)], cwd=ROOT,
                         capture_output=True, text=True, timeout=300)
    report = "\n".join(ln for ln in res.stdout.splitlines()
                       if not ln.startswith("127.0.0.1"))
    assert res.returncode == 0, f"Lab tab layout regressed on iPhone X:\n{report}\n{res.stderr[-2000:]}"
    # the harness must actually have exercised all three variants
    for variant in ("idle", "running", "clock-skew"):
        assert f"── Lab tab @ iPhone X ({variant}) ──" in report, \
            f"variant {variant!r} did not run:\n{report}"
    assert "0 failed" in report


@pytest.mark.skipif(shutil.which("node") is None, reason="node unavailable")
def test_harness_is_syntactically_loadable():
    """Cheap guard so a typo in the harness reads as a harness problem rather
    than a UI regression."""
    import ast
    ast.parse(HARNESS.read_text())
