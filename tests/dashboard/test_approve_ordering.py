"""approveSelected enqueues every selected intent as mode='immediate'.

Single approval rule (manual or auto): submit to the broker NOW if the market is
open, else queue for the next open. The executor's `_route_to_drain('immediate')`
does exactly that — open → submit now; closed → fill-gated drain (sells first,
buys one at a time within buying power). So there is one approve action, and every
approvable selection is sent via approveTrade with mode 'immediate'. This extracts
the REAL approveSelected() from dashboard.js so a regression (reverting to the old
two-mode 'scheduled' greenlight) fails CI.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DASH_JS = ROOT / "services" / "dashboard" / "static" / "dashboard.js"


def _extract_approve_selected() -> str:
    src = DASH_JS.read_text()
    m = re.search(r"async function approveSelected\(\)\s*\{.*?\n\}", src, re.S)
    assert m, "could not find approveSelected() in dashboard.js"
    return m.group(0)


_HARNESS_TMPL = r"""
// --- stubs for approveSelected's dependencies ---
let deltaData = __DATA__;
let _selectedIntents = new Set(__SELECTED__);

function _isApprovable(r) {
  return ['entry','exit','buy_add','sell_trim'].includes(r.action)
      && !r.order_status && !r.rejected_at && !(r.vetter_excluded && (r.action==='entry'||r.action==='buy_add'));
}

// record (id, mode) for every approveTrade call
const calls = [];
async function approveTrade(intentId, mode) {
  for (let k = 0; k < ((calls.length % 3) + 2); k++) await Promise.resolve();
  calls.push({ id: intentId, mode });
}

// --- the real shipped function ---
__APPROVE_SELECTED__

(async () => { await approveSelected(); console.log(JSON.stringify(calls)); })();
"""


def _run(data, selected, tmp_path):
    js = (_HARNESS_TMPL
          .replace("__DATA__", json.dumps(data))
          .replace("__SELECTED__", json.dumps(selected))
          .replace("__APPROVE_SELECTED__", _extract_approve_selected()))
    harness = tmp_path / "h.js"
    harness.write_text(js)
    out = subprocess.run(["node", str(harness)], capture_output=True, text=True, timeout=20)
    assert out.returncode == 0, f"node failed: {out.stderr[:600]}"
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_all_selected_enqueued_as_immediate(tmp_path):
    data = [
        {"id": "B1", "action": "entry",     "order_status": None, "rejected_at": None, "vetter_excluded": False},
        {"id": "S1", "action": "exit",      "order_status": None, "rejected_at": None, "vetter_excluded": False},
        {"id": "B2", "action": "buy_add",   "order_status": None, "rejected_at": None, "vetter_excluded": False},
        {"id": "S2", "action": "sell_trim", "order_status": None, "rejected_at": None, "vetter_excluded": False},
    ]
    calls = _run(data, ["B1", "S1", "B2", "S2"], tmp_path)
    assert {c["id"] for c in calls} == {"B1", "S1", "B2", "S2"}, f"not all enqueued: {calls}"
    # Single rule: submit now if open, else queue — the executor decides via the clock.
    assert all(c["mode"] == "immediate" for c in calls), f"every approval must be 'immediate': {calls}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_non_approvable_intents_skipped(tmp_path):
    """Already-ordered / rejected / vetter-excluded-buy intents are not enqueued."""
    data = [
        {"id": "OK",   "action": "entry",     "order_status": None,       "rejected_at": None,   "vetter_excluded": False},
        {"id": "DONE", "action": "entry",     "order_status": "deferred", "rejected_at": None,   "vetter_excluded": False},
        {"id": "REJ",  "action": "sell_trim", "order_status": None,       "rejected_at": "x",    "vetter_excluded": False},
        {"id": "VEX",  "action": "buy_add",   "order_status": None,       "rejected_at": None,   "vetter_excluded": True},
    ]
    calls = _run(data, ["OK", "DONE", "REJ", "VEX"], tmp_path)
    assert {c["id"] for c in calls} == {"OK"}, f"only OK should enqueue: {calls}"
    assert calls[0]["mode"] == "immediate"
