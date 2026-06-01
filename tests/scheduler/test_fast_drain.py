"""Tests for the fast-drain freshness gate (_chain_is_active).

Root cause of the stale-UI symptom family: the cron path ticked every 300s, so
the authoritative _chain_status the dashboard renders was up to 5 min stale during
the after-close chain. The fix fast-ticks the supervisor WHILE a chain is active.
_chain_is_active is the pure gate that decides "keep fast-draining"; these tests
pin it so the drain neither stops early (mid-chain) nor spins forever (after done).
"""
from app.main import _chain_is_active


def test_active_when_running_with_run_id():
    assert _chain_is_active({"status": "running", "current_run_id": "abc"}) is True


def test_active_when_running_even_without_run_id_yet():
    # Status flipped to running before current_run_id is recorded — still active.
    assert _chain_is_active({"status": "running", "current_run_id": None}) is True


def test_inactive_when_success():
    assert _chain_is_active({"status": "success", "current_run_id": "abc"}) is False


def test_inactive_when_failed():
    assert _chain_is_active({"status": "failed", "current_run_id": "abc"}) is False


def test_inactive_when_idle_no_run():
    assert _chain_is_active({"status": None, "current_run_id": None}) is False


def test_active_with_run_id_and_no_status():
    # A run is in flight (run id set) but status not yet "running" — keep draining.
    assert _chain_is_active({"status": None, "current_run_id": "abc"}) is True
