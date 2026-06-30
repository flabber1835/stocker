"""approveSelected sends the whole selection as ONE durable batch enqueue.

Approval is now a durable batch: the dashboard POSTs the entire approvable selection
to /api/trade/approve-batch in a SINGLE request, and the trade-executor's
single-consumer worker sizes/risk-checks/submits each off the request path. This
replaces the old client-side loop — Promise.all (→ submit-lock timeouts on big
rotations) and its for-await successor (→ a browser refresh stranded the tail).

These extract the REAL approveSelected() from dashboard.js so a regression (going
back to per-intent client submission, or dropping the batch endpoint) fails CI.
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
let _approvalState = {};
function renderTrader() {}
function _enqueueState(res) { return { status: (res && res.status) || 'err' }; }

function _isApprovable(r) {
  return ['entry','exit','buy_add','sell_trim'].includes(r.action)
      && !r.order_status && !r.approved_at && !r.rejected_at
      && !(r.vetter_excluded && (r.action==='entry'||r.action==='buy_add'));
}

// record every fetch call (url + parsed body)
const fetchCalls = [];
async function fetch(url, opts) {
  fetchCalls.push({ url, body: JSON.parse(opts.body) });
  return { ok: true, json: async () => ({ results:
    JSON.parse(opts.body).intent_ids.map(id => ({ intent_id: id, status: 'queued' })),
    queued: JSON.parse(opts.body).intent_ids.length }) };
}

// --- the real shipped function ---
__APPROVE_SELECTED__

(async () => { await approveSelected(); console.log(JSON.stringify(fetchCalls)); })();
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
def test_whole_selection_sent_as_one_batch(tmp_path):
    data = [
        {"id": "B1", "action": "entry",     "order_status": None, "rejected_at": None, "vetter_excluded": False},
        {"id": "S1", "action": "exit",      "order_status": None, "rejected_at": None, "vetter_excluded": False},
        {"id": "B2", "action": "buy_add",   "order_status": None, "rejected_at": None, "vetter_excluded": False},
        {"id": "S2", "action": "sell_trim", "order_status": None, "rejected_at": None, "vetter_excluded": False},
    ]
    calls = _run(data, ["B1", "S1", "B2", "S2"], tmp_path)
    # EXACTLY ONE request (not one-per-intent — that was the lock-timeout/refresh bug).
    assert len(calls) == 1, f"expected a single batch request, got {len(calls)}"
    assert calls[0]["url"] == "/api/trade/approve-batch"
    assert set(calls[0]["body"]["intent_ids"]) == {"B1", "S1", "B2", "S2"}
    assert calls[0]["body"]["mode"] == "immediate"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_one_request_regardless_of_count(tmp_path):
    """A large rotation still produces exactly ONE request (no client-side fan-out)."""
    data = [{"id": f"I{i}", "action": "entry", "order_status": None,
             "rejected_at": None, "vetter_excluded": False} for i in range(30)]
    calls = _run(data, [d["id"] for d in data], tmp_path)
    assert len(calls) == 1, f"30 approvals must be ONE batch request, got {len(calls)}"
    assert len(calls[0]["body"]["intent_ids"]) == 30


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_non_approvable_intents_excluded(tmp_path):
    """Already-ordered / rejected / vetter-excluded-buy / already-queued intents are
    not included in the batch."""
    data = [
        {"id": "OK",   "action": "entry",     "order_status": None,       "rejected_at": None, "vetter_excluded": False},
        {"id": "DONE", "action": "entry",     "order_status": "deferred", "rejected_at": None, "vetter_excluded": False},
        {"id": "REJ",  "action": "sell_trim", "order_status": None,       "rejected_at": "x",  "vetter_excluded": False},
        {"id": "VEX",  "action": "buy_add",   "order_status": None,       "rejected_at": None, "vetter_excluded": True},
        {"id": "QUE",  "action": "entry",     "order_status": None,       "rejected_at": None, "vetter_excluded": False, "approved_at": "2026-06-30T00:00:00Z"},
    ]
    calls = _run(data, ["OK", "DONE", "REJ", "VEX", "QUE"], tmp_path)
    assert len(calls) == 1
    assert calls[0]["body"]["intent_ids"] == ["OK"], f"only OK should enqueue: {calls}"
