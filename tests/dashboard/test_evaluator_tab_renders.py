"""The Review tab must actually RENDER — not just be free of forbidden strings.

dashboard.js has no JS test runner, so a ReferenceError in a render path was
only discovered when a human opened the tab. Worse, the tab's catch reported it
as "Evaluator unreachable", pointing blame at a service that was healthy. That
is how a leftover `applyUi` (deleted with the one-click apply) shipped: it sits
in the branch taken ONLY by a valid single-field recommendation, so every
static check and every other card shape passed.

render_evaluator_tab.js loads the real file into a node vm with a stub DOM and
calls _renderEvalReport across every report shape the evaluator can produce.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HARNESS = Path(__file__).parent / "render_evaluator_tab.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None,
                                reason="node unavailable")


def _run(harness: Path = HARNESS) -> subprocess.CompletedProcess:
    return subprocess.run(["node", str(harness)], cwd=ROOT,
                          capture_output=True, text=True, timeout=60)


def test_every_report_shape_renders_without_throwing():
    res = _run()
    assert res.returncode == 0, (
        "the Review tab throws while rendering — the UI would show "
        f"'Evaluator unreachable' for a healthy service:\n{res.stdout}\n{res.returncode}"
    )
    # every fixture must have been exercised, not silently skipped
    assert "OK   valid single-field edit" in res.stdout
    assert "FAIL" not in res.stdout


def test_harness_actually_detects_a_broken_render(tmp_path):
    """A guard that passes when the code is broken is worse than none. Inject
    the exact regression (an undefined identifier in the valid-edit branch) and
    require the harness to fail on it."""
    src = (ROOT / "services" / "dashboard" / "static" / "dashboard.js").read_text()
    marker = "not actionable</span>' : '') +"
    assert marker in src, "render branch moved — update this regression probe"
    broken_dir = tmp_path / "services" / "dashboard" / "static"
    broken_dir.mkdir(parents=True)
    (broken_dir / "dashboard.js").write_text(
        src.replace(marker, "not actionable</span>' : applyUi) +", 1))
    # the harness resolves dashboard.js relative to itself → copy it alongside
    harness_dir = tmp_path / "tests" / "dashboard"
    harness_dir.mkdir(parents=True)
    shutil.copy(HARNESS, harness_dir / HARNESS.name)

    res = subprocess.run(["node", str(harness_dir / HARNESS.name)], cwd=tmp_path,
                         capture_output=True, text=True, timeout=60)
    assert res.returncode == 1, "harness did not catch an undefined identifier"
    assert "ReferenceError: applyUi is not defined" in res.stdout


def test_render_crash_is_not_reported_as_service_unreachable():
    """A UI exception said 'Evaluator unreachable', which sent the owner
    debugging a service that was fine."""
    src = (ROOT / "services" / "dashboard" / "static" / "dashboard.js").read_text()
    assert "Dashboard render error" in src
    assert "e instanceof ReferenceError" in src
