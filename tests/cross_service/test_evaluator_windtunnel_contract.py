"""END-TO-END CONTRACT: can the evaluator actually drive the wind tunnel?

The evaluator (live stack) and bt-scheduler (backtest stack) never call each
other — they meet ONLY at artifacts/bt/proposals.json. Nothing in either suite
crosses that seam, so a field-name drift there would break the whole loop while
every unit test stayed green. This test owns the seam.

It runs the REAL producer and the REAL consumer against one temp artifacts dir,
loading each service's module by path so their identically-named `app` packages
never collide.
"""
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STRAT = ROOT / "strategies" / "quality_core_v1.yaml"


def _use_service(service: str):
    """Point the ambiguous top-level `app` package at ONE service, the way the
    per-suite conftests do. Purges any previously-loaded `app` first so the two
    stacks can be exercised in the same test."""
    for k in [k for k in sys.modules if k == "app" or k.startswith("app.")]:
        del sys.modules[k]
    svc = str(ROOT / "services" / service)
    while svc in sys.path:
        sys.path.remove(svc)
    sys.path.insert(0, svc)


def _load(module: str, service: str):
    _use_service(service)
    return importlib.import_module(module)


@pytest.fixture
def artifacts(tmp_path, monkeypatch):
    d = tmp_path / "artifacts"
    (d / "bt").mkdir(parents=True)
    monkeypatch.setenv("ARTIFACTS_PATH", str(d))
    return d


def _queue_candidate(artifacts, max_positions=17):
    """Run the REAL evaluator tool that writes the queue."""
    import asyncio

    import yaml
    tools = _load("app.tools", "evaluator")
    tools.STRATEGY_CONFIG_PATH = str(STRAT)
    cand = yaml.safe_load(open(STRAT))
    cand["portfolio_builder"]["max_positions"] = max_positions
    out = asyncio.run(tools.queue_strategy_experiment(
        {"config": cand, "hypothesis": "fewer names concentrate the edge"},
        budget=tools.BacktestBudget()))
    assert "queued full-config candidate" in out, out
    return out


def test_evaluator_queue_is_readable_by_the_lane(artifacts):
    """The producer's entry must satisfy the consumer's filter EXACTLY."""
    _queue_candidate(artifacts)

    raw = json.loads((artifacts / "bt" / "proposals.json").read_text())
    entry = raw["proposals"][0]
    # the lane's filter, verbatim
    assert entry.get("status") == "pending"
    assert entry.get("kind") == "full_config"
    assert isinstance(entry.get("config"), dict)
    # fields the lane reads when building its experiment entry
    assert entry.get("id") and entry.get("config_hash")
    assert isinstance(entry.get("diff"), dict) and entry["diff"]
    assert entry.get("hypothesis")

    sched = _load("app.main", "bt-scheduler")
    sched.ARTIFACTS_PATH = str(artifacts)
    pending = sched._pending_full_experiments()
    assert len(pending) == 1, "the lane cannot see the evaluator's candidate"
    p = pending[0]
    assert p["config"]["portfolio_builder"]["max_positions"] == 17
    # the payload the lane would POST to bt-engine is a COMPLETE config
    assert p["config"]["strategy_id"]


def test_a_queued_candidate_actually_gets_a_slot(artifacts):
    """The queue being READABLE is not enough — the lane only reaches for a
    candidate once its baseline yardstick is valid. baseline_is_valid checked a
    key the lane never writes, so it always said 'no pinned comparison window':
    every daily slot re-ran the BASELINE and no candidate was ever tested. The
    loop looked healthy (experiments firing nightly) while doing nothing.
    This asserts both halves compose — a valid baseline AND a visible candidate."""
    from datetime import date
    _queue_candidate(artifacts)
    sched = _load("app.main", "bt-scheduler")
    sched.ARTIFACTS_PATH = str(artifacts)
    from app.logic import baseline_is_valid, experiment_windows

    windows = experiment_windows(date(2026, 7, 25), 3, 12, date(2004, 1, 1))
    baseline = {"kind": "baseline", "status": "success", "windows": windows,
                "applied_promotion": None}
    base_ok, why = baseline_is_valid(baseline, None)
    assert base_ok, f"the lane would re-run the baseline forever: {why}"
    # …so the fire step falls through to the evaluator's pending candidate
    assert sched._pending_full_experiments(), "no candidate available for the slot"


def test_lane_lifecycle_marks_the_evaluators_entry(artifacts):
    """pending → testing → tested must land on the SAME row the evaluator wrote."""
    _queue_candidate(artifacts)
    sched = _load("app.main", "bt-scheduler")
    sched.ARTIFACTS_PATH = str(artifacts)

    pid = sched._pending_full_experiments()[0]["id"]
    sched._mark_full_proposal(pid, "testing")
    assert sched._pending_full_experiments() == []          # no longer pending
    raw = json.loads((artifacts / "bt" / "proposals.json").read_text())
    assert raw["proposals"][0]["status"] == "testing"
    assert raw["proposals"][0]["config"], "config must survive the status write"

    sched._mark_full_proposal(pid, "tested")
    raw = json.loads((artifacts / "bt" / "proposals.json").read_text())
    assert raw["proposals"][0]["status"] == "tested"


def test_packet_shows_what_the_candidate_actually_changes(artifacts):
    """A future review must be able to read its own queue: kind, hash, and the
    DIFF (without it the evaluator is blind to what it proposed)."""
    _queue_candidate(artifacts)
    packet = _load("app.packet", "evaluator")
    q = packet._experiment_queue()
    assert q["available"] is True
    assert q["counts"].get("pending") == 1
    row = q["recent"][0]
    assert row["kind"] == "full_config"
    assert row["hypothesis"]
    assert row["config_hash"]
    assert "portfolio_builder.max_positions" in row["changes"]
    assert row["changes"]["portfolio_builder.max_positions"].endswith("-> 17")


def test_locks_resolve_to_the_same_file_across_both_stacks(artifacts):
    """Producer and consumer must serialize on ONE lock path, or a concurrent
    queue-write and status-write can lose an entry."""
    props = _load("app.proposals", "evaluator")
    evaluator_lock = props.proposals_path() + ".lock"
    scheduler_lock = os.path.join(str(artifacts), "bt", "proposals.json.lock")
    assert os.path.realpath(evaluator_lock) == os.path.realpath(scheduler_lock)


# ── named stress regimes: the two stacks must offer the SAME set ─────────────

def test_regime_tables_match_across_the_stacks():
    """The regime table is duplicated by necessity — the stacks share no code
    path. If they drift, the evaluator offers a regime the lane will refuse and
    the candidate is silently marked invalid."""
    tools = _load("app.tools", "evaluator")
    ev = set(tools.STRESS_REGIMES)
    sched = _load("app.logic", "bt-scheduler")
    lane = set(sched.STRESS_REGIMES)
    assert ev == lane, (
        f"regime tables drifted — evaluator-only: {ev - lane}, lane-only: {lane - ev}")
    for name in sorted(lane):
        assert sched.regime_windows(name, None)[0] is not None, \
            f"{name} is offered but produces no windows"


def test_a_queued_regime_candidate_carries_its_regime_to_the_lane(artifacts):
    """The end-to-end field: the evaluator stamps `regime`, the lane reads it."""
    import asyncio

    import yaml
    tools = _load("app.tools", "evaluator")
    tools.STRATEGY_CONFIG_PATH = str(STRAT)
    cand = yaml.safe_load(open(STRAT))
    cand["portfolio_builder"]["max_positions"] = 21
    out = asyncio.run(tools.queue_strategy_experiment(
        {"config": cand, "hypothesis": "does concentration survive a crisis?",
         "regime": "gfc_2008"}, budget=tools.BacktestBudget()))
    assert "gfc_2008" in out and "never promote" in out, out

    sched = _load("app.main", "bt-scheduler")
    sched.ARTIFACTS_PATH = str(artifacts)
    pending = sched._pending_full_experiments()
    assert pending and pending[0]["regime"] == "gfc_2008"


def test_raw_date_ranges_are_not_offered(artifacts):
    """Choosing both the config and the period searches two dimensions while
    the DSR penalises one."""
    tools = _load("app.tools", "evaluator")
    spec = [t for t in tools.tool_definitions()
            if t["name"] == "queue_strategy_experiment"][0]
    props = spec["parameters"]["properties"]
    # Assert the INTENT — no free date range — not an exact parameter set. The
    # exact-set form broke the moment a legitimate new field was added, which
    # is a test coupling to the wrong thing.
    date_like = [k for k in props
                 if any(w in k.lower() for w in ("date", "start", "end", "from",
                                                 "to_", "period", "window", "year"))]
    assert not date_like, f"a raw date/period field is exposed: {date_like}"
    assert props["regime"]["enum"] == sorted(tools.STRESS_REGIMES)
    assert "config" in props and "hypothesis" in props
