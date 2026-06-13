"""Regression: a DEAD order (risk_rejected/failed/expired/canceled) must not wedge
its intent — the operator can retry the trade manually.

Root cause (2026-06-13): within a single trading session, /delta/latest joined
order status by ticker+side+run_date, so a risk_rejected order from earlier in the
SAME session stuck to every fresh re-run's intent, and the /trade/approve guard
409'd on risk_rejected. Combined with the UI's _isApprovable, a bug-induced exit
rejection (the risk-service control_unavailable bug) could never be re-approved
without hand-editing the DB. Fix: only genuinely-OPEN orders block; dead attempts
stay retryable. Auto-approve (cron) still skips them — see test_auto_approve.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_MAIN = ROOT / "services" / "api" / "app" / "main.py"
DASH_JS = ROOT / "services" / "dashboard" / "static" / "dashboard.js"
DASH_MAIN = ROOT / "services" / "dashboard" / "app" / "main.py"


def _api():
    return API_MAIN.read_text()


def _js():
    return DASH_JS.read_text()


def test_approve_guard_does_not_block_risk_rejected():
    src = _api()
    # The approve idempotency guard blocks only open orders now.
    assert "status IN ('pending','submitted','deferred') " in src
    # The old list that trapped retries must be gone from that guard.
    assert "status IN ('pending','submitted','deferred','risk_rejected')" not in src


def test_delta_latest_prefers_live_over_dead_order():
    src = _api()
    # LATERAL order-status join prefers a live/filled order over a dead attempt,
    # so a stale rejection in the same session can't mask a fresh intent.
    assert "CASE WHEN ao2.status IN " in src
    assert "'partially_filled','filled') THEN 0 ELSE 1 END" in src


def test_ui_isApprovable_allows_dead_but_blocks_open():
    js = _js()
    # _isApprovable blocks only open/done statuses; dead ones are retryable.
    assert "os === 'submitted' || os === 'pending' || os === 'deferred' || os === 'filled' || os === 'partial_fill') return false;" in js
    # The OLD block-list (which trapped failed/risk_rejected/expired) must be gone.
    old = ("os === 'submitted' || os === 'pending' || os === 'deferred' || "
           "os === 'failed' || os === 'risk_rejected' || os === 'filled' || "
           "os === 'partial_fill' || os === 'expired') return false;")
    assert old not in js
    # _approvalState still guards against double-click while a retry is in flight.
    assert "if (_approvalState[r.id]) return false;" in js
    # _sectionFor SHOULD still route a rejected/failed order to Needs Attention.
    assert "os === 'failed' || os === 'risk_rejected' || os === 'expired') return 'attention'" in js


def test_auto_approve_still_skips_dead_orders():
    # Cron auto-approve must NOT retry dead orders (no loops); only the manual UI
    # path allows retry. Guard the server-side skip-list stays intact.
    dash = DASH_MAIN.read_text()
    assert '"failed", "risk_rejected", "submitted", "pending",' in dash
