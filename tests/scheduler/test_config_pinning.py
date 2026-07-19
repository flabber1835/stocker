"""Chain-level config pinning (audit finding #5).

The supervisor pins the active strategy hash at the first strategy-consuming
trigger of a chain and passes expected_config_hash on pipeline/vet/build/delta
triggers. A service 409 config_mismatch (mid-chain one-click apply) makes it
re-pin and force-re-run the whole strategy segment so the chain converges on
ONE config instead of mixing two.
"""
import os
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from tests.scheduler.test_manual_run_cancel import _make_apscheduler_stubs  # noqa: E402,F401

from app.main import (  # noqa: E402
    _STEPS,
    _STRATEGY_STEPS,
    _active_config_hash,
    _chain_status,
    _force_pending,
    _trigger_step,
)

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
V2 = os.path.join(ROOT, "strategies", "momentum_rotation_v2.yaml")


def _step(name):
    return next(s for s in _STEPS if s.name == name)


def _mock_resp(status_code=200, payload=None):
    r = MagicMock()
    r.status_code = status_code
    r.json.return_value = payload or {}
    r.text = ""
    return r


# Patch through the FUNCTION's globals: the root conftest re-imports app.main
# per test, so monkeypatch.setattr("app.main....") would land on a different
# module instance than the one our imported functions read from.
_G = _trigger_step.__globals__


@pytest.fixture(autouse=True)
def _reset_pin():
    saved_path = _G["STRATEGY_CONFIG_PATH"]
    _G["STRATEGY_CONFIG_PATH"] = V2
    assert _active_config_hash(), "pin source unreadable — tests would be vacuous"
    saved_hash = _chain_status.get("config_hash")
    saved_force = set(_force_pending)
    _chain_status["config_hash"] = None
    _force_pending.clear()
    yield
    _G["STRATEGY_CONFIG_PATH"] = saved_path
    _chain_status["config_hash"] = saved_hash
    _force_pending.clear()
    _force_pending.update(saved_force)


def test_active_config_hash_matches_shared_loader():
    from stock_strategy_shared.loader import load_strategy
    _, loader_hash = load_strategy(V2)
    assert _active_config_hash() == loader_hash


def test_active_config_hash_none_when_unreadable():
    _G["STRATEGY_CONFIG_PATH"] = "/nonexistent.yaml"
    assert _active_config_hash() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["pipeline", "vet", "portfolio-builder", "delta"])
async def test_strategy_steps_carry_the_pinned_hash(name, monkeypatch):
    async def _ok(*a, **k):
        return True
    monkeypatch.setitem(_G, "_cancel_deferred_orders", _ok)
    captured = {}

    async def fake_post(url, timeout=None, params=None):
        captured["params"] = params or {}
        return _mock_resp(200, {"status": "started"})

    client = MagicMock()
    client.post = fake_post
    assert await _trigger_step(client, _step(name)) is True
    expect = _active_config_hash()
    assert expect and captured["params"].get("expected_config_hash") == expect
    # pinned once, reused for the whole chain
    assert _chain_status["config_hash"] == expect


@pytest.mark.asyncio
async def test_fetch_data_is_not_pinned():
    captured = {}

    async def fake_post(url, timeout=None, params=None):
        captured["params"] = params or {}
        return _mock_resp(200, {"status": "started"})

    client = MagicMock()
    client.post = fake_post
    await _trigger_step(client, _step("fetch-data"))
    assert "expected_config_hash" not in captured["params"]
    assert _chain_status["config_hash"] is None       # fetch never pins


@pytest.mark.asyncio
async def test_config_mismatch_repins_and_forces_strategy_segment():
    _chain_status["config_hash"] = "stalehash0000000"

    async def fake_post(url, timeout=None, params=None):
        return _mock_resp(409, {"status": "config_mismatch",
                                "expected": "stalehash0000000",
                                "loaded": "newhash"})

    client = MagicMock()
    client.post = fake_post
    ok = await _trigger_step(client, _step("vet"))
    assert ok is False                                   # retried next tick
    assert _chain_status["config_hash"] == _active_config_hash()   # re-pinned to file
    assert set(_STRATEGY_STEPS) <= _force_pending        # whole segment re-runs


@pytest.mark.asyncio
async def test_plain_409_still_means_already_running():
    _chain_status["config_hash"] = _active_config_hash()

    async def fake_post(url, timeout=None, params=None):
        return _mock_resp(409, {"detail": "already running"})

    client = MagicMock()
    client.post = fake_post
    assert await _trigger_step(client, _step("vet")) is True
    assert not _force_pending
