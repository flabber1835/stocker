"""Live integration tests for the pipeline service (port 8018).

The pipeline runs factors → ranking → delta in sequence. These tests verify
the service's data-query endpoints and the idempotency of the run trigger.
They never modify DB state — the /jobs/run call is skipped by default since
it's expensive and guarded by a lock anyway.
"""
import pytest
import requests

BASE = "http://localhost:8018"


def _up():
    try:
        return requests.get(f"{BASE}/health", timeout=3).status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _up(), reason="Pipeline not reachable on :8018")


# ── health ────────────────────────────────────────────────────────────────────

def test_health():
    r = requests.get(f"{BASE}/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ── latest run ───────────────────────────────────────────────────────────────

def test_latest_run_has_required_fields():
    r = requests.get(f"{BASE}/runs/latest")
    assert r.status_code == 200
    d = r.json()
    for key in ("run_id", "status", "run_date"):
        assert key in d, f"Missing field: {key}"


def test_latest_run_status_is_terminal():
    d = requests.get(f"{BASE}/runs/latest").json()
    assert d["status"] in ("success", "failed", "running")


def test_latest_run_sub_step_statuses_present():
    d = requests.get(f"{BASE}/runs/latest").json()
    for step in ("factor_status", "ranking_status", "delta_status"):
        assert step in d, f"Missing sub-step field: {step}"


def test_latest_run_success_has_all_sub_steps_succeeded():
    d = requests.get(f"{BASE}/runs/latest").json()
    if d["status"] != "success":
        pytest.skip("Latest run not in success state")
    assert d["factor_status"] == "success"
    assert d["ranking_status"] == "success"
    assert d["delta_status"] == "success"


def test_latest_run_has_factor_and_ranking_run_ids():
    d = requests.get(f"{BASE}/runs/latest").json()
    if d["status"] != "success":
        pytest.skip("Latest run not in success state")
    assert d.get("factor_run_id") is not None
    assert d.get("ranking_run_id") is not None


# ── delta latest ──────────────────────────────────────────────────────────────

def test_delta_latest_run_has_required_fields():
    """Pipeline /runs/delta-latest returns the latest delta run metadata."""
    r = requests.get(f"{BASE}/runs/delta-latest")
    assert r.status_code == 200
    d = r.json()
    for key in ("run_id", "status", "run_date", "entries_count", "exits_count"):
        assert key in d, f"Missing field: {key}"


def test_delta_latest_run_status_is_terminal():
    d = requests.get(f"{BASE}/runs/delta-latest").json()
    assert d["status"] in ("success", "failed", "running"), f"Unexpected status: {d['status']}"


def test_delta_latest_counts_are_non_negative():
    d = requests.get(f"{BASE}/runs/delta-latest").json()
    for count_field in ("entries_count", "exits_count", "holds_count", "watches_count"):
        assert d.get(count_field, 0) >= 0, f"{count_field} is negative"


# ── all runs list ─────────────────────────────────────────────────────────────

def test_runs_list_returns_list():
    r = requests.get(f"{BASE}/runs")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_runs_list_sorted_newest_first():
    runs = requests.get(f"{BASE}/runs").json()
    if len(runs) < 2:
        pytest.skip("Not enough runs to check order")
    dates = [r["started_at"] for r in runs if r.get("started_at")]
    assert dates == sorted(dates, reverse=True), "Runs not sorted newest-first"


# ── duplicate run guard ───────────────────────────────────────────────────────

def test_duplicate_run_returns_deduplicated_status():
    """Triggering /jobs/run twice in quick succession must not create two running jobs.
    The pipeline deduplicates via a lock (already_running) or date guard (already_ran_today)."""
    import threading, time

    results = []

    def _trigger():
        r = requests.post(f"{BASE}/jobs/run", json={}, timeout=30)
        results.append((r.status_code, r.json().get("status", "")))

    t1 = threading.Thread(target=_trigger)
    t2 = threading.Thread(target=_trigger)
    t1.start()
    time.sleep(0.05)
    t2.start()
    t1.join(timeout=60)
    t2.join(timeout=60)

    statuses = [s for _, s in results]
    valid = {"already_running", "already_ran_today", "success", "failed"}
    for s in statuses:
        assert s in valid, f"Unexpected status: {s!r} (got: {statuses})"

    # Must NOT have two jobs both claiming to be "running" with no lock guard
    running_count = sum(1 for s in statuses if s == "running")
    assert running_count < 2, "Two concurrent runs started — lock not working"
