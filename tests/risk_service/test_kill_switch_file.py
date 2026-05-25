"""
Kill switch control file integration tests for risk-service.

The kill switch has two activation paths:
  A. KILL_SWITCH env var set to "true" at container startup
  B. /tmp/kill_switch file present at runtime (hot-flip without restart)

Path B is the primary operational mechanism documented in CLAUDE.md:
  docker exec stocker-risk-service-1 touch /tmp/kill_switch   # activate
  docker exec stocker-risk-service-1 rm    /tmp/kill_switch   # deactivate

These tests use real tempfiles (not env-var monkeypatching) so the
os.path.exists() code path in _safety_env() is exercised directly.

The critical invariant: with the kill switch active — by EITHER mechanism —
NO trade should receive approved=True from /check.
"""
from __future__ import annotations

import os
import sys
import tempfile
import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_RS_PATH = os.path.join(ROOT, "services", "risk-service")

# Ensure risk-service is on sys.path (handle test ordering with other services)
_app_mod = sys.modules.get("app")
if _app_mod is None or _RS_PATH not in os.path.abspath(getattr(_app_mod, "__file__", "") or ""):
    for _k in list(sys.modules.keys()):
        if _k == "app" or _k.startswith("app."):
            del sys.modules[_k]
    if _RS_PATH not in sys.path:
        sys.path.insert(0, _RS_PATH)
    if os.path.join(ROOT, "shared") not in sys.path:
        sys.path.insert(0, os.path.join(ROOT, "shared"))

from app.main import _safety_env  # noqa: E402
import app.main as risk_main       # noqa: E402
from app.main import app            # noqa: E402


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _stub_persist(monkeypatch):
    """Stub DB persistence so /check works without Postgres."""
    async def _fake(req, *, approved, reason, rule, env):
        return str(uuid.uuid4())
    monkeypatch.setattr(risk_main, "_persist_decision", _fake)


@pytest.fixture()
def client():
    return TestClient(app)


def _valid_payload(**overrides):
    base = {
        "ticker": "AAPL", "action": "entry", "side": "buy",
        "qty": 10, "notional": 1000.0,
        "mode": "immediate", "trade_type": "paper",
    }
    base.update(overrides)
    return base


def _temp_kill_switch_file():
    """Create a real non-/tmp file and return its path.

    We avoid /tmp/kill_switch itself so parallel tests don't interfere;
    each test patches _KILL_SWITCH_FILE to point at this unique path.
    """
    fd, path = tempfile.mkstemp(prefix="ks_test_")
    os.close(fd)
    return path


# ── Unit tests: _safety_env() with real file ─────────────────────────────────

def test_safety_env_kill_switch_off_when_no_file_and_no_env(monkeypatch, tmp_path):
    """Baseline: neither file nor env var → kill_switch=False."""
    fake_path = str(tmp_path / "no_such_file")   # does not exist
    monkeypatch.setattr(risk_main, "_KILL_SWITCH_FILE", fake_path)
    monkeypatch.setenv("KILL_SWITCH", "false")
    env = _safety_env()
    assert env["kill_switch"] is False


def test_safety_env_kill_switch_on_when_file_exists(monkeypatch, tmp_path):
    """Creating the control file activates the kill switch immediately."""
    fake_path = str(tmp_path / "kill_switch")
    fake_path_obj = tmp_path / "kill_switch"
    fake_path_obj.touch()
    monkeypatch.setattr(risk_main, "_KILL_SWITCH_FILE", fake_path)
    monkeypatch.setenv("KILL_SWITCH", "false")   # env var says off — file wins
    env = _safety_env()
    assert env["kill_switch"] is True


def test_safety_env_file_takes_precedence_over_env_var(monkeypatch, tmp_path):
    """File ON + env OFF → kill_switch active (file takes precedence)."""
    fake_path = str(tmp_path / "kill_switch")
    (tmp_path / "kill_switch").touch()
    monkeypatch.setattr(risk_main, "_KILL_SWITCH_FILE", fake_path)
    monkeypatch.setenv("KILL_SWITCH", "false")
    assert _safety_env()["kill_switch"] is True


def test_safety_env_delete_file_deactivates_switch(monkeypatch, tmp_path):
    """Removing the control file deactivates the kill switch on the NEXT call."""
    fake_path = str(tmp_path / "kill_switch")
    ks_file = tmp_path / "kill_switch"
    ks_file.touch()
    monkeypatch.setattr(risk_main, "_KILL_SWITCH_FILE", fake_path)
    monkeypatch.setenv("KILL_SWITCH", "false")

    assert _safety_env()["kill_switch"] is True   # file present → ON

    ks_file.unlink()                              # delete the file
    assert _safety_env()["kill_switch"] is False  # next call → OFF


def test_safety_env_env_var_alone_activates_switch(monkeypatch, tmp_path):
    """env KILL_SWITCH=true activates switch even without the file."""
    fake_path = str(tmp_path / "no_such_file")   # does not exist
    monkeypatch.setattr(risk_main, "_KILL_SWITCH_FILE", fake_path)
    monkeypatch.setenv("KILL_SWITCH", "true")
    assert _safety_env()["kill_switch"] is True


# ── End-to-end: /check rejects all trades when kill switch active ─────────────

def test_check_rejects_when_kill_switch_file_present(monkeypatch, tmp_path, client):
    """/check must return approved=False and rule_triggered='kill_switch'
    when the control file exists, regardless of env var."""
    fake_path = str(tmp_path / "kill_switch")
    (tmp_path / "kill_switch").touch()
    monkeypatch.setattr(risk_main, "_KILL_SWITCH_FILE", fake_path)
    monkeypatch.setenv("KILL_SWITCH", "false")   # env says off — file wins

    resp = client.post("/check", json=_valid_payload())
    assert resp.status_code == 200
    body = resp.json()
    assert body["approved"] is False
    assert body["rule_triggered"] == "kill_switch"


def test_check_approves_after_kill_switch_file_deleted(monkeypatch, tmp_path, client):
    """After the file is removed, /check resumes approving valid paper trades."""
    fake_path = str(tmp_path / "kill_switch")
    ks_file = tmp_path / "kill_switch"
    ks_file.touch()
    monkeypatch.setattr(risk_main, "_KILL_SWITCH_FILE", fake_path)
    monkeypatch.setenv("KILL_SWITCH", "false")

    # First call: switch ON → reject
    r1 = client.post("/check", json=_valid_payload())
    assert r1.json()["approved"] is False

    # Delete file: switch OFF → approve
    ks_file.unlink()
    r2 = client.post("/check", json=_valid_payload())
    assert r2.json()["approved"] is True
    assert r2.json()["rule_triggered"] == "ok"


def test_check_rejects_all_actions_when_kill_switch_active(monkeypatch, tmp_path, client):
    """Kill switch blocks every action type — not just entries."""
    fake_path = str(tmp_path / "kill_switch")
    (tmp_path / "kill_switch").touch()
    monkeypatch.setattr(risk_main, "_KILL_SWITCH_FILE", fake_path)

    cases = [
        {"action": "entry",     "side": "buy"},
        {"action": "exit",      "side": "sell"},
        {"action": "buy_add",   "side": "buy"},
        {"action": "sell_trim", "side": "sell"},
    ]
    for case in cases:
        resp = client.post("/check", json=_valid_payload(**case))
        body = resp.json()
        assert body["approved"] is False, f"Kill switch did not block action={case['action']}"
        assert body["rule_triggered"] == "kill_switch"


def test_kill_switch_evaluated_on_every_call(monkeypatch, tmp_path, client):
    """_safety_env() re-reads the file on EVERY /check call — not once at startup.

    This is the whole point of the file mechanism: flip the switch at runtime
    without a container restart and have it take effect on the very next trade.
    """
    fake_path = str(tmp_path / "kill_switch")
    ks_file = tmp_path / "kill_switch"
    monkeypatch.setattr(risk_main, "_KILL_SWITCH_FILE", fake_path)
    monkeypatch.setenv("KILL_SWITCH", "false")

    # Call 1: no file → approved
    r1 = client.post("/check", json=_valid_payload())
    assert r1.json()["approved"] is True

    # Create file mid-session
    ks_file.touch()

    # Call 2: file now present → rejected (same client session, same process)
    r2 = client.post("/check", json=_valid_payload())
    assert r2.json()["approved"] is False
    assert r2.json()["rule_triggered"] == "kill_switch"

    # Remove file mid-session
    ks_file.unlink()

    # Call 3: file gone → approved again
    r3 = client.post("/check", json=_valid_payload())
    assert r3.json()["approved"] is True
