"""
Tests for the risk-service /check endpoint.

The service is a stateless FastAPI app; these tests exercise the pure /check
logic (no DB). Module-level constants (KILL_SWITCH, LIVE_TRADING_ENABLED,
PAPER_ONLY, MAX_ORDER_NOTIONAL) are read at import time, so tests that need
to flip them use monkeypatch on `app.main`.
"""
import os as _os
import sys as _sys

# Ensure risk-service's 'app' package is on sys.path regardless of which other
# service's test files ran first and cached a different 'app' module.
_RISK_PATH = _os.path.abspath(
    _os.path.join(_os.path.dirname(__file__), "..", "..", "services", "risk-service")
)
_app = _sys.modules.get("app")
if _app is None or _RISK_PATH not in _os.path.abspath(getattr(_app, "__file__", "") or ""):
    for _k in list(_sys.modules.keys()):
        if _k == "app" or _k.startswith("app."):
            del _sys.modules[_k]
    if _RISK_PATH not in _sys.path:
        _sys.path.insert(0, _RISK_PATH)

import uuid

import pytest
from fastapi.testclient import TestClient

from app import main as risk_main
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _stub_persist(monkeypatch):
    """Stub _persist_decision on the same risk_main instance the TestClient
    uses, so /check returns approvals without a real Postgres. Tests that
    verify the 'no DB' guard use monkeypatch.undo() to remove this stub
    then set engine to None."""
    async def _fake_persist(req, *, approved, reason, rule, env):
        return str(uuid.uuid4())
    monkeypatch.setattr(risk_main, "_persist_decision", _fake_persist)
    yield


def _valid_payload(**overrides):
    base = {
        "ticker": "AAPL",
        "action": "entry",
        "side": "buy",
        "qty": 10,
        "notional": 1000.0,
        "mode": "immediate",
        "trade_type": "paper",
    }
    base.update(overrides)
    return base


# ── /health ──────────────────────────────────────────────────────────────────


def test_health_returns_ok_with_limits():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert "kill_switch" in body
    assert "paper_only" in body
    assert "live_trading_enabled" in body
    assert "max_order_notional" in body


# ── /check happy path ────────────────────────────────────────────────────────


def test_valid_paper_trade_approved():
    resp = client.post("/check", json=_valid_payload())
    assert resp.status_code == 200
    body = resp.json()
    assert body["approved"] is True
    assert "passed" in body["reason"].lower()
    # check_id must parse as a UUID
    uuid.UUID(body["check_id"])


# ── quantity/notional checks ────────────────────────────────────────────────


def test_negative_qty_rejected():
    resp = client.post("/check", json=_valid_payload(qty=-5))
    assert resp.status_code == 200
    body = resp.json()
    assert body["approved"] is False
    assert "qty" in body["reason"].lower()


def test_zero_qty_rejected():
    resp = client.post("/check", json=_valid_payload(qty=0))
    assert resp.status_code == 200
    assert resp.json()["approved"] is False


def test_notional_over_limit_rejected():
    resp = client.post("/check", json=_valid_payload(notional=60_000.0))
    assert resp.status_code == 200
    body = resp.json()
    assert body["approved"] is False
    assert "exceeds" in body["reason"].lower()


def test_zero_notional_rejected():
    resp = client.post("/check", json=_valid_payload(notional=0))
    assert resp.status_code == 200
    body = resp.json()
    assert body["approved"] is False
    assert "notional" in body["reason"].lower()


# ── live-trading guards ─────────────────────────────────────────────────────


def test_live_trade_blocked_when_disabled():
    resp = client.post("/check", json=_valid_payload(trade_type="live"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["approved"] is False
    reason = body["reason"].lower()
    assert "live" in reason or "paper" in reason


# ── check_id uniqueness ─────────────────────────────────────────────────────


def test_check_id_is_unique_uuid():
    r1 = client.post("/check", json=_valid_payload()).json()
    r2 = client.post("/check", json=_valid_payload()).json()
    id1 = uuid.UUID(r1["check_id"])
    id2 = uuid.UUID(r2["check_id"])
    assert id1 != id2


# ── pydantic 422 cases ──────────────────────────────────────────────────────


def test_invalid_action_rejected_by_pydantic():
    resp = client.post("/check", json=_valid_payload(action="invalid"))
    assert resp.status_code == 422


def test_invalid_side_rejected_by_pydantic():
    resp = client.post("/check", json=_valid_payload(side="hold"))
    assert resp.status_code == 422


def test_invalid_mode_rejected_by_pydantic():
    resp = client.post("/check", json=_valid_payload(mode="now"))
    assert resp.status_code == 422


# ── monkeypatched constants ─────────────────────────────────────────────────


def test_kill_switch_rejects_all(monkeypatch):
    monkeypatch.setenv("KILL_SWITCH", "true")
    resp = client.post("/check", json=_valid_payload())
    assert resp.status_code == 200
    body = resp.json()
    assert body["approved"] is False
    assert "kill switch" in body["reason"].lower()


def test_live_trading_enabled_allows_live(monkeypatch):
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    monkeypatch.setenv("PAPER_ONLY", "false")
    resp = client.post("/check", json=_valid_payload(trade_type="live"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["approved"] is True


# ── rule_triggered field (new in A4) ─────────────────────────────────────────


def test_rule_triggered_ok_on_approved():
    body = client.post("/check", json=_valid_payload()).json()
    assert body["rule_triggered"] == "ok"


def test_rule_triggered_qty_on_negative_qty():
    body = client.post("/check", json=_valid_payload(qty=-1)).json()
    assert body["rule_triggered"] == "qty"


def test_rule_triggered_notional_zero():
    body = client.post("/check", json=_valid_payload(notional=0)).json()
    assert body["rule_triggered"] == "notional_zero"


def test_rule_triggered_notional_limit():
    body = client.post("/check", json=_valid_payload(notional=99_999.0)).json()
    assert body["rule_triggered"] == "notional_limit"


def test_rule_triggered_kill_switch(monkeypatch):
    monkeypatch.setenv("KILL_SWITCH", "true")
    body = client.post("/check", json=_valid_payload()).json()
    assert body["rule_triggered"] == "kill_switch"


def test_rule_triggered_paper_only(monkeypatch):
    # Live enabled but paper-only still blocks
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    monkeypatch.setenv("PAPER_ONLY", "true")
    body = client.post("/check", json=_valid_payload(trade_type="live")).json()
    assert body["rule_triggered"] == "paper_only"


def test_rule_triggered_live_disabled(monkeypatch):
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
    monkeypatch.setenv("PAPER_ONLY", "false")
    body = client.post("/check", json=_valid_payload(trade_type="live")).json()
    assert body["rule_triggered"] == "live_disabled"


def test_no_db_refuses_to_approve(monkeypatch):
    """When engine is None (DATABASE_URL unset / DB down), /check returns 503
    for an approval — risk-service refuses to approve a trade without writing
    an audit row. Rejections still return 200 because rejecting is safe."""
    # Restore real _persist_decision so the engine=None guard fires
    from importlib import reload
    monkeypatch.undo()  # remove conftest's stub for this test
    monkeypatch.setattr(risk_main, "engine", None)
    # Approval path → 503
    resp = client.post("/check", json=_valid_payload())
    assert resp.status_code == 503
    # Rejection path → 200 (still safely rejects without persistence)
    monkeypatch.setenv("KILL_SWITCH", "true")
    resp = client.post("/check", json=_valid_payload())
    assert resp.status_code == 200
    body = resp.json()
    assert body["approved"] is False
    uuid.UUID(body["check_id"])
