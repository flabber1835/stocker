"""config_pin_mismatch — the portfolio-builder's side of chain-level config pinning
(audit finding #5): a stale expected_config_hash must refuse the job (409
config_mismatch) BEFORE any run row is reserved."""
import os

from fastapi.testclient import TestClient

import app.main as m
from app.main import app, config_pin_mismatch

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
V2 = os.path.join(ROOT, "strategies", "momentum_rotation_v2.yaml")


def test_no_pin_no_check():
    assert config_pin_mismatch(None) is None
    assert config_pin_mismatch("") is None


def test_matching_pin_passes(monkeypatch):
    monkeypatch.setattr(m, "STRATEGY_CONFIG_PATH", V2)
    from stock_strategy_shared.loader import load_strategy
    _, live = load_strategy(V2)
    assert config_pin_mismatch(live) is None


def test_stale_pin_reports_mismatch(monkeypatch):
    monkeypatch.setattr(m, "STRATEGY_CONFIG_PATH", V2)
    out = config_pin_mismatch("deadbeefdeadbeef")
    assert out["status"] == "config_mismatch"
    assert out["expected"] == "deadbeefdeadbeef" and out["loaded"]


def test_unreadable_config_counts_as_mismatch(monkeypatch):
    monkeypatch.setattr(m, "STRATEGY_CONFIG_PATH", "/nonexistent.yaml")
    out = config_pin_mismatch("deadbeefdeadbeef")
    assert out["status"] == "config_mismatch" and out["loaded"] is None


def test_jobs_build_409_on_stale_pin(monkeypatch):
    """Wiring: /jobs/build refuses before UUID validation / any DB read."""
    monkeypatch.setattr(m, "STRATEGY_CONFIG_PATH", V2)
    client = TestClient(app)
    r = client.post("/jobs/build", params={"expected_config_hash": "deadbeefdeadbeef"})
    assert r.status_code == 409
    assert r.json()["status"] == "config_mismatch"
