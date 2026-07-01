"""U1/U6: the client-side monotonic phase latch never renders the chain going
backwards within a run — the fix for the "vetter → calculating factors / 100% → 99%"
flicker. Extracts the REAL _latchPhase + _PHASE_RANK from dashboard.js and drives it
through Node so a regression (dropping the latch, or a bad rank map) fails CI.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DASH_JS = ROOT / "services" / "dashboard" / "static" / "dashboard.js"


def _extract(name_pattern: str) -> str:
    src = DASH_JS.read_text()
    m = re.search(name_pattern, src, re.S)
    assert m, f"could not find {name_pattern} in dashboard.js"
    return m.group(0)


_HARNESS = r"""
let _phaseLatch = null;
__PHASE_RANK__
__LATCH_FN__
// feed a sequence of [text, cls] through the latch; print the resulting texts
const seq = __SEQ__;
const out = [];
for (const [t, c] of seq) { out.push(_latchPhase(t, c).text); }
console.log(JSON.stringify(out));
"""


def _run(seq, tmp_path):
    phase_rank = _extract(r"const _PHASE_RANK = \{.*?\};")
    latch_fn = _extract(r"function _latchPhase\(text, textCls\) \{.*?\n\}")
    import json
    js = (_HARNESS
          .replace("__PHASE_RANK__", phase_rank)
          .replace("__LATCH_FN__", latch_fn)
          .replace("__SEQ__", json.dumps(seq)))
    h = tmp_path / "h.js"
    h.write_text(js)
    out = subprocess.run(["node", str(h)], capture_output=True, text=True, timeout=20)
    assert out.returncode == 0, f"node failed: {out.stderr[:600]}"
    return json.loads(out.stdout.strip().splitlines()[-1])


pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")


def test_phase_never_regresses_within_run(tmp_path):
    # vetter (5) then a stale-source blip back to factors (3) → must HOLD vetter.
    out = _run([
        ["CALCULATING FACTORS  40%", "sb-amber"],
        ["RANKING STOCKS  80%", "sb-amber"],
        ["VETTER", "sb-purple"],
        ["CALCULATING FACTORS  10%", "sb-amber"],   # regression → held
        ["BUILDING PORTFOLIO", "sb-blue"],
    ], tmp_path)
    assert out == [
        "CALCULATING FACTORS  40%",
        "RANKING STOCKS  80%",
        "VETTER",
        "VETTER",                # held, not regressed to factors
        "BUILDING PORTFOLIO",    # forward move allowed
    ]


def test_pct_never_drops_within_a_phase(tmp_path):
    out = _run([
        ["FETCHING DATA  100%", "sb-amber"],
        ["FETCHING DATA  99%", "sb-amber"],   # the reported symptom → held at 100
    ], tmp_path)
    assert out == ["FETCHING DATA  100%", "FETCHING DATA  100%"]


def test_new_run_resets_latch(tmp_path):
    # A drop back to a FETCH phase is a legitimate NEW run → latch resets.
    out = _run([
        ["VETTER", "sb-purple"],
        ["FETCHING DATA  5%", "sb-amber"],    # new run — allowed to go "back"
        ["CALCULATING FACTORS  20%", "sb-amber"],
    ], tmp_path)
    assert out == ["VETTER", "FETCHING DATA  5%", "CALCULATING FACTORS  20%"]


def test_terminal_resets_latch(tmp_path):
    out = _run([
        ["DELTA EVAL  50%", "sb-amber"],
        ["READY", "sb-green"],                # terminal → reset
        ["FETCHING DATA  10%", "sb-amber"],   # next run starts clean
    ], tmp_path)
    assert out == ["DELTA EVAL  50%", "READY", "FETCHING DATA  10%"]
