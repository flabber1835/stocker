from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])
SCRIPTS = ROOT / "scripts"
DRIVER = SCRIPTS / "sentinel_autonomous_deploy_driver.py"
sys.path.insert(0, str(SCRIPTS))
core = importlib.import_module("sentinel_autonomous_deploy")
driver = importlib.import_module("sentinel_autonomous_deploy_driver")


SESSION = "2026-08-03"
PRIOR_FRONTIER = 6256
AUTHORITATIVE_FLOOR = 5005  # ceil(6256 * readiness's unchanged 80% floor)


def _deploy(tmp_path):
    cfg = SimpleNamespace(data_retry_seconds=30, data_wait_timeout_seconds=300)
    obj = driver.AutonomousDeploy(cfg, SimpleNamespace(env={}), tmp_path)
    obj.commit = "a" * 40
    obj.base_compose = ["docker", "compose", "-f", "base.yml"]
    obj.phase = lambda _text: None
    return obj


def _freshness_verdict():
    freshness = {
        "name": "freshness",
        "status": "FAIL",
        "detail": "missing latest closed session",
        "value": {
            "evaluable": True,
            "ahead": False,
            "expected_session": SESSION,
            "frontier": "2026-07-31",
            "missing_sessions": [SESSION],
        },
    }
    return {
        "ready": False,
        "checks": [
            {
                "name": "frontier population",
                "status": "PASS",
                "detail": "healthy prior frontier",
                "value": {
                    "frontier": PRIOR_FRONTIER,
                    "minimum": AUTHORITATIVE_FLOOR,
                    "recent_median": float(PRIOR_FRONTIER),
                },
            },
            freshness,
        ],
        "failures": [freshness],
    }


def _ready_verdict():
    return {"ready": True, "checks": [], "failures": []}


def _probe(count: int, *, ready: bool = False):
    return {
        "ready": ready,
        "minimum_resolved_positive_securities": AUTHORITATIVE_FLOOR,
        "vendor_ticker_rows_total": 50000,
        "vendor_sep_ticker_rows_reaching_window": 6000,
        "sep_resolved_positive_securities": {SESSION: count},
        "spy_sessions": [SESSION],
    }


def _probe_runner(count: int):
    payload = {
        "ticker_rows_total": 50000,
        "sep_ticker_rows_reaching_window": 6000,
        "sep_resolved_positive_securities": {SESSION: count},
        "spy_sessions": [SESSION],
    }
    return SimpleNamespace(
        run=lambda *_args, **_kwargs: SimpleNamespace(
            stdout=json.dumps(payload), stderr="", returncode=0))


@pytest.mark.parametrize("published", [6000, 5924])
def test_normal_and_ground_truth_contraction_fire_non_authoritative_probe(
        tmp_path, published):
    obj = _deploy(tmp_path)
    sessions, floor = obj._freshness_wait_requirements(_freshness_verdict())
    obj.runner = _probe_runner(published)

    evidence = obj._vendor_publication_probe(sessions, floor)

    assert 5924 / PRIOR_FRONTIER < 0.95
    assert floor == AUTHORITATIVE_FLOOR
    assert evidence["ready"] is True


def test_genuinely_partial_publication_does_not_fire_ratio_probe(tmp_path):
    obj = _deploy(tmp_path)
    sessions, floor = obj._freshness_wait_requirements(_freshness_verdict())
    obj.runner = _probe_runner(4000)

    evidence = obj._vendor_publication_probe(sessions, floor)

    assert evidence["ready"] is False


def test_stable_positive_frontier_below_probe_floor_triggers_authoritative_check(
        tmp_path, monkeypatch):
    obj = _deploy(tmp_path)
    stale = _freshness_verdict()
    verdicts = [stale, stale, _ready_verdict()]
    probes = []
    calls = []

    obj._automation_status = lambda: {
        "enabled": False, "kill_switch_engaged": True}
    obj._readiness_verdict = lambda: verdicts.pop(0)

    def probe(*_args):
        probes.append(4000)
        return _probe(4000, ready=False)

    obj._vendor_publication_probe = probe
    obj._base_cli = lambda args, *, capture=False, check=True: (
        calls.append((list(args), check))
        or SimpleNamespace(stdout="", stderr="", returncode=0))
    sleeps = []
    monkeypatch.setattr(driver.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(driver.time, "sleep", lambda seconds: sleeps.append(seconds))

    obj._wait_for_data(deadline=1000.0)

    assert probes == [4000, 4000]
    assert sleeps == [30]
    assert [call for call in calls if call[0] == ["feed-daily"]] == [
        (["feed-daily"], True)]
    assert [call for call in calls if call[0] == ["check-data"]] == [
        (["check-data"], True)]


def test_stabilization_never_overrides_authoritative_refusal(
        tmp_path, monkeypatch):
    obj = _deploy(tmp_path)
    stale = _freshness_verdict()
    authoritative_failure = {
        "ready": False,
        "checks": [{
            "name": "frontier population",
            "status": "FAIL",
            "detail": "partial newest cross-section",
            "value": {"frontier": 4000, "minimum": AUTHORITATIVE_FLOOR},
        }],
        "failures": [{
            "name": "frontier population",
            "status": "FAIL",
            "detail": "partial newest cross-section",
            "value": {"frontier": 4000, "minimum": AUTHORITATIVE_FLOOR},
        }],
    }
    verdicts = [stale, stale, authoritative_failure]
    calls = []

    obj._automation_status = lambda: {
        "enabled": False, "kill_switch_engaged": True}
    obj._readiness_verdict = lambda: verdicts.pop(0)
    obj._vendor_publication_probe = lambda *_args: _probe(4000, ready=False)
    obj._base_cli = lambda args, *, capture=False, check=True: (
        calls.append((list(args), check))
        or SimpleNamespace(stdout="", stderr="", returncode=0))
    monkeypatch.setattr(driver.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(driver.time, "sleep", lambda _seconds: None)

    with pytest.raises(core.DeployRefused, match="corpus remained unready"):
        obj._wait_for_data(deadline=1000.0)

    assert [call for call in calls if call[0] == ["feed-daily"]] == [
        (["feed-daily"], True)]
    assert (["check-data"], False) in calls


def test_publication_probe_has_no_strategy_eligibility_dependency():
    source = DRIVER.read_text(encoding="utf-8")
    start = source.index("def _vendor_publication_probe")
    end = source.index("def _write_deployment_state", start)
    assert "wealth_core.eligibility" not in source[start:end]
