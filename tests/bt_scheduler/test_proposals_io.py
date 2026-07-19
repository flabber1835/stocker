"""_mark_proposals lifecycle transitions (audit F2) — pending→testing stamps
the sweep id, pending→invalid records engine-rejected proposals, testing→tested
only touches the exporting sweep's entries. All under the F1 flock."""
import importlib
import json
import os
import sys


def _main(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACTS_PATH", str(tmp_path))
    for k in list(sys.modules):
        if k == "app" or k.startswith("app."):
            del sys.modules[k]
    import app.main as m
    importlib.reload(m)
    return m


def _write(tmp_path, entries):
    os.makedirs(tmp_path / "bt", exist_ok=True)
    with open(tmp_path / "bt" / "proposals.json", "w") as f:
        json.dump({"proposals": entries}, f)


def _read(tmp_path):
    with open(tmp_path / "bt" / "proposals.json") as f:
        return {e["id"]: e for e in json.load(f)["proposals"]}


def test_fire_time_split_testing_vs_invalid(tmp_path, monkeypatch):
    m = _main(tmp_path, monkeypatch)
    _write(tmp_path, [
        {"id": "a", "config_field": "x", "value": 1, "status": "pending", "sweep_id": None},
        {"id": "b", "config_field": "y", "value": 2, "status": "pending", "sweep_id": None},
        {"id": "c", "config_field": "z", "value": 3, "status": "tested", "sweep_id": "old"},
    ])
    m._mark_proposals("pending", "testing", "s1", only_pending_ids={"a"})
    m._mark_proposals("pending", "invalid", "s1", only_pending_ids={"b"})
    got = _read(tmp_path)
    assert got["a"]["status"] == "testing" and got["a"]["sweep_id"] == "s1"
    assert got["b"]["status"] == "invalid" and got["b"]["sweep_id"] is None
    assert got["c"]["status"] == "tested" and got["c"]["sweep_id"] == "old"   # untouched


def test_export_marks_only_that_sweeps_testing_entries(tmp_path, monkeypatch):
    m = _main(tmp_path, monkeypatch)
    _write(tmp_path, [
        {"id": "a", "config_field": "x", "value": 1, "status": "testing", "sweep_id": "s1"},
        {"id": "b", "config_field": "y", "value": 2, "status": "testing", "sweep_id": "s2"},
    ])
    m._mark_proposals("testing", "tested", "s1")
    got = _read(tmp_path)
    assert got["a"]["status"] == "tested"
    assert got["b"]["status"] == "testing"        # a DIFFERENT running sweep's entry


def test_missing_file_is_a_noop(tmp_path, monkeypatch):
    m = _main(tmp_path, monkeypatch)
    m._mark_proposals("pending", "testing", "s1")     # no proposals.json → no crash
    assert not os.path.exists(tmp_path / "bt" / "proposals.json")


def test_exploratory_entries_ride_the_sweep_like_harvest_entries(tmp_path, monkeypatch):
    """queue_experiment entries carry extra fields (origin, hypothesis) — the
    scheduler must pick them up as pending experiments and lifecycle-mark them
    exactly like recommendation-origin entries, preserving the extra fields."""
    m = _main(tmp_path, monkeypatch)
    _write(tmp_path, [
        {"id": "rec", "config_field": "x", "value": 1, "status": "pending",
         "sweep_id": None},
        {"id": "exp", "config_field": "y", "value": 2, "status": "pending",
         "sweep_id": None, "origin": "exploratory",
         "hypothesis": "y=2 reduces churn without hurting OOS sharpe"},
    ])
    pending = m._pending_proposals()
    assert {p["id"] for p in pending} == {"rec", "exp"}
    m._mark_proposals("pending", "testing", "s1", only_pending_ids={"rec", "exp"})
    got = _read(tmp_path)
    assert got["exp"]["status"] == "testing" and got["exp"]["sweep_id"] == "s1"
    assert got["exp"]["origin"] == "exploratory"      # extra fields preserved
    assert got["exp"]["hypothesis"].startswith("y=2")
