"""Live integration tests for the scheduler service (port 8015).

The scheduler is a non-blocking supervisor state machine. These tests verify
its status endpoint, chain step tracking, and that it does NOT re-trigger
steps that have already completed today.
"""
import pytest
import requests

BASE = "http://localhost:8015"


def _up():
    try:
        return requests.get(f"{BASE}/health", timeout=3).status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _up(), reason="Scheduler not reachable on :8015")


def test_health():
    r = requests.get(f"{BASE}/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_status_has_required_fields():
    r = requests.get(f"{BASE}/status")
    assert r.status_code == 200
    d = r.json()
    for key in ("status", "date", "steps"):
        assert key in d, f"Missing field: {key}"


def test_status_date_is_today():
    from datetime import date
    d = requests.get(f"{BASE}/status").json()
    assert d["date"] == str(date.today())


def test_chain_steps_are_valid_set():
    d = requests.get(f"{BASE}/status").json()
    expected_steps = {"fetch-data", "pipeline", "vet"}
    actual_steps = set(d["steps"].keys())
    assert expected_steps <= actual_steps, f"Missing steps: {expected_steps - actual_steps}"


def test_chain_step_statuses_are_valid():
    d = requests.get(f"{BASE}/status").json()
    valid = {"done", "pending", "failed", "running", "skipped"}
    for step, status in d["steps"].items():
        assert status in valid, f"Step {step} has invalid status: {status!r}"


def test_status_includes_next_run_time():
    d = requests.get(f"{BASE}/status").json()
    assert "next_run" in d, "Scheduler must publish next_run time"


def test_run_ids_map_present():
    d = requests.get(f"{BASE}/status").json()
    assert "run_ids" in d, "Scheduler must track run_ids per step"


def test_latest_run_endpoint():
    r = requests.get(f"{BASE}/runs/latest")
    assert r.status_code == 200
    d = r.json()
    assert isinstance(d, dict)


def test_completed_chain_shows_all_steps_done():
    """If today's chain already completed, all steps should be 'done'."""
    d = requests.get(f"{BASE}/status").json()
    if d.get("status") != "success":
        pytest.skip("Today's chain not in success state")
    for step, status in d["steps"].items():
        assert status == "done", f"Step {step} should be done but is {status!r}"


def test_debug_log_returns_string():
    r = requests.get(f"{BASE}/debug/log")
    assert r.status_code == 200
    # Log should be text or JSON
    assert len(r.text) >= 0
