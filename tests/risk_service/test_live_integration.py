"""Live integration tests for the risk-service (port 8011).

These exercise the running Docker container so we catch env-variable and
control-file behaviour that unit tests with monkeypatch cannot.  All tests
are safe: they read or use a /check call but never alter persistent state.
"""
import uuid
import pytest
import requests

BASE = "http://localhost:8011"


def _up():
    try:
        return requests.get(f"{BASE}/health", timeout=3).status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _up(), reason="Risk-service not reachable on :8011")


def _payload(**overrides) -> dict:
    base = {
        "ticker": "AAPL",
        "action": "entry",
        "side": "buy",
        "qty": 10,
        "notional": 1000.0,
        "trade_type": "paper",
        "mode": "immediate",
        "intent_id": str(uuid.uuid4()),
    }
    return {**base, **overrides}


# ── health ────────────────────────────────────────────────────────────────────

def test_health():
    r = requests.get(f"{BASE}/health")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "ok"
    assert d["service"] == "risk-service"


# ── basic approval ────────────────────────────────────────────────────────────

def test_valid_paper_trade_approved_or_kill_switch():
    """A valid paper trade should be either APPROVED (normal) or REJECTED due to
    kill switch being active — both are valid outcomes in this environment."""
    r = requests.post(f"{BASE}/check", json=_payload())
    assert r.status_code in (200, 409)
    d = r.json()
    assert "approved" in d
    assert "rule_triggered" in d or "rule" in d


def test_check_response_has_required_fields():
    r = requests.post(f"{BASE}/check", json=_payload())
    d = r.json()
    assert "approved" in d, "Missing 'approved' field"
    assert "reason" in d, "Missing 'reason' field"
    # rule_triggered is the actual field name in the running service
    assert "rule_triggered" in d or "rule" in d, "Missing rule field"


# ── input validation ──────────────────────────────────────────────────────────

def test_zero_qty_rejected():
    r = requests.post(f"{BASE}/check", json=_payload(qty=0))
    assert r.status_code in (200, 409)
    d = r.json()
    assert d["approved"] is False


def test_negative_qty_rejected():
    r = requests.post(f"{BASE}/check", json=_payload(qty=-5))
    assert r.status_code in (200, 409, 422)
    if r.status_code == 422:
        return  # schema validation caught it
    assert r.json()["approved"] is False


def test_zero_notional_rejected():
    r = requests.post(f"{BASE}/check", json=_payload(notional=0.0))
    assert r.status_code in (200, 409)
    d = r.json()
    assert d["approved"] is False


def test_negative_notional_rejected():
    r = requests.post(f"{BASE}/check", json=_payload(notional=-100.0))
    assert r.status_code in (200, 409, 422)
    if r.status_code == 422:
        return
    assert r.json()["approved"] is False


def test_live_trade_rejected_when_paper_only():
    """Live trades must be rejected in our paper-only environment."""
    r = requests.post(f"{BASE}/check", json=_payload(trade_type="live"))
    assert r.status_code in (200, 409)
    d = r.json()
    # Either LIVE_TRADING_ENABLED is off, or PAPER_ONLY blocks it — both reject
    assert d["approved"] is False


def test_buy_add_action_accepted_by_schema():
    """buy_add and sell_trim are valid action values (regression: was Literal["entry","exit"] only)."""
    r = requests.post(f"{BASE}/check", json=_payload(action="buy_add"))
    # 200 or 409 (kill switch), but NOT 422 (schema rejection)
    assert r.status_code in (200, 409), f"Got {r.status_code}: schema rejected 'buy_add'"


def test_sell_trim_action_accepted_by_schema():
    r = requests.post(f"{BASE}/check", json=_payload(action="sell_trim", side="sell"))
    assert r.status_code in (200, 409), f"Got {r.status_code}: schema rejected 'sell_trim'"


def test_exit_action_accepted():
    r = requests.post(f"{BASE}/check", json=_payload(action="exit", side="sell"))
    assert r.status_code in (200, 409)


def test_missing_ticker_returns_422():
    payload = _payload()
    del payload["ticker"]
    r = requests.post(f"{BASE}/check", json=payload)
    assert r.status_code == 422


def test_missing_qty_returns_422():
    payload = _payload()
    del payload["qty"]
    r = requests.post(f"{BASE}/check", json=payload)
    assert r.status_code == 422


def test_invalid_action_returns_422():
    r = requests.post(f"{BASE}/check", json=_payload(action="moon_shot"))
    assert r.status_code == 422


# ── notional limit ────────────────────────────────────────────────────────────

def test_huge_notional_rejected():
    """A notional of $10M should exceed MAX_ORDER_NOTIONAL in any sane config."""
    r = requests.post(f"{BASE}/check", json=_payload(notional=10_000_000.0, qty=100))
    assert r.status_code in (200, 409)
    d = r.json()
    assert d["approved"] is False
    # Reason should mention what was violated
    assert d.get("reason", "") != ""
