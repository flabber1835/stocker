"""approveSelected must submit SELLS before BUYS.

Alpaca validates buying power at submission time, per order — a not-yet-executed
sell does not raise buying power, so a buy submitted before its funding sell is
rejected on a fully-invested account ("insufficient buying power"). The batch
"Approve Selected" therefore submits all sells (exit/sell_trim), awaits them, then
submits buys (entry/buy_add).

This extracts the real approveSelected() source from dashboard.js (so the test
tracks the shipped code, not a copy) and runs it in Node with tiny stubs for its
dependencies, recording the order in which approveTrade is invoked.
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

// an intent is approvable iff it's a tradeable action with no order yet
function _isApprovable(r) {
  return ['entry','exit','buy_add','sell_trim'].includes(r.action)
      && !r.order_status && !r.rejected_at && !(r.vetter_excluded && (r.action==='entry'||r.action==='buy_add'));
}

const submitted = [];
async function approveTrade(intentId, mode) {
  // varying microtask delay so a buggy parallel submission would interleave
  for (let k = 0; k < ((submitted.length % 3) + 2); k++) await Promise.resolve();
  submitted.push(intentId);
}

// --- the real shipped function ---
__APPROVE_SELECTED__

(async () => { await approveSelected(); console.log(JSON.stringify(submitted)); })();
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_sells_submitted_before_buys(tmp_path):
    data = [
        {"id": "B1", "action": "entry",     "order_status": None, "rejected_at": None, "vetter_excluded": False},
        {"id": "S1", "action": "exit",      "order_status": None, "rejected_at": None, "vetter_excluded": False},
        {"id": "B2", "action": "buy_add",   "order_status": None, "rejected_at": None, "vetter_excluded": False},
        {"id": "S2", "action": "sell_trim", "order_status": None, "rejected_at": None, "vetter_excluded": False},
    ]
    # Selected buy-first to prove the function REORDERS, not preserves selection order.
    selected = ["B1", "S1", "B2", "S2"]
    js = (_HARNESS_TMPL
          .replace("__DATA__", json.dumps(data))
          .replace("__SELECTED__", json.dumps(selected))
          .replace("__APPROVE_SELECTED__", _extract_approve_selected()))
    harness = tmp_path / "h.js"
    harness.write_text(js)

    out = subprocess.run(["node", str(harness)], capture_output=True, text=True, timeout=20)
    assert out.returncode == 0, f"node failed: {out.stderr[:600]}"
    order = json.loads(out.stdout.strip().splitlines()[-1])

    assert set(order) == {"B1", "S1", "B2", "S2"}, f"not all submitted: {order}"
    sells = {"S1", "S2"}
    last_sell = max(i for i, x in enumerate(order) if x in sells)
    first_buy = min(i for i, x in enumerate(order) if x not in sells)
    assert last_sell < first_buy, f"a buy was submitted before a sell: {order}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_only_sells_or_only_buys_still_submits_all(tmp_path):
    """No exits in the batch → all buys still submit (no empty-sell-phase deadlock)."""
    data = [
        {"id": "B1", "action": "entry",   "order_status": None, "rejected_at": None, "vetter_excluded": False},
        {"id": "B2", "action": "buy_add", "order_status": None, "rejected_at": None, "vetter_excluded": False},
    ]
    js = (_HARNESS_TMPL
          .replace("__DATA__", json.dumps(data))
          .replace("__SELECTED__", json.dumps(["B1", "B2"]))
          .replace("__APPROVE_SELECTED__", _extract_approve_selected()))
    harness = tmp_path / "h.js"
    harness.write_text(js)
    out = subprocess.run(["node", str(harness)], capture_output=True, text=True, timeout=20)
    assert out.returncode == 0, f"node failed: {out.stderr[:600]}"
    order = json.loads(out.stdout.strip().splitlines()[-1])
    assert set(order) == {"B1", "B2"}
