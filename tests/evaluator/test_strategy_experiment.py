"""queue_strategy_experiment — the evaluator's ONLY write to the wind tunnel.

A COMPLETE candidate StrategyConfig is the single currency: to change one field
the evaluator sends the whole YAML with that field changed, so what gets tested
is exactly what may go live. (The old single-field queue_experiment tool and the
recommendation harvest were removed with the human one-click apply path.)
"""
import asyncio
import json
import os

import pytest

import app.tools as tools

STRAT = os.path.join(os.path.dirname(__file__), "..", "..",
                     "strategies", "quality_core_v1.yaml")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACTS_PATH", str(tmp_path))
    monkeypatch.setattr(tools, "STRATEGY_CONFIG_PATH", STRAT)
    return tmp_path


def _entries(tmp_path):
    with open(tmp_path / "bt" / "proposals.json") as f:
        return json.load(f)["proposals"]


# ── queue_strategy_experiment (Phase 6c full-config lane) ────────────────────

def _call_full(args, budget):
    return asyncio.run(tools.execute_tool(
        "queue_strategy_experiment", args, engine=None, budget=budget))


def _active_config():
    from stock_strategy_shared.loader import load_strategy
    cfg, _h = load_strategy(STRAT)
    return cfg.model_dump(mode="json")


def test_full_config_candidate_queued_with_auto_diff(env):
    budget = tools.BacktestBudget()
    cand = _active_config()
    cand["max_positions"] = 20
    out = _call_full({"config": cand, "hypothesis": "concentration lifts CAGR",
                      "mechanism": "concentration_control"},
                     budget)
    assert "queued full-config candidate" in out
    (entry,) = _entries(env)
    assert entry["kind"] == "full_config" and entry["status"] == "pending"
    assert entry["diff"]["max_positions"] == {"from": 30, "to": 20}
    assert entry["config"]["max_positions"] == 20
    assert budget.experiment_used == 1


def test_full_config_identical_to_active_rejected(env):
    budget = tools.BacktestBudget()
    out = _call_full({"config": _active_config(), "hypothesis": "h",
                            "mechanism": "risk_control"}, budget)
    assert "identical to the active config" in out
    assert budget.experiment_used == 0


def test_full_config_duplicate_refunds_budget(env):
    budget = tools.BacktestBudget()
    cand = _active_config()
    cand["max_positions"] = 20
    _call_full({"config": cand, "hypothesis": "h1", "mechanism": "risk_control"}, budget)
    out = _call_full({"config": cand, "hypothesis": "h2 different",
                      "mechanism": "risk_control"}, budget)
    assert "already queued" in out
    assert len(_entries(env)) == 1
    assert budget.experiment_used == 1


def test_full_config_schema_invalid_rejected_before_budget(env):
    budget = tools.BacktestBudget()
    cand = _active_config()
    cand["max_positions"] = -5                    # schema violation
    out = _call_full({"config": cand, "hypothesis": "h",
                      "mechanism": "risk_control"}, budget)
    assert "schema validation" in out
    assert budget.experiment_used == 0


def test_second_candidate_on_the_same_mechanism_is_refused_end_to_end(env):
    """Independence enforced through the REAL queue path, not just the pure
    helper: two different configs, same mechanism, second one refused and its
    budget refunded. This is what stops five slots holding one hypothesis."""
    budget = tools.BacktestBudget()
    a = _active_config(); a["max_positions"] = 20
    b = _active_config(); b["max_positions"] = 22
    assert "queued full-config candidate" in _call_full(
        {"config": a, "hypothesis": "tighter book", "mechanism": "concentration_control"},
        budget)
    out = _call_full(
        {"config": b, "hypothesis": "even tighter", "mechanism": "concentration_control"},
        budget)
    assert "already queued this cycle" in out
    assert len(_entries(env)) == 1
    assert budget.experiment_used == 1, "a refused draw must not burn budget"


def test_a_different_mechanism_still_queues(env):
    """The refusal must not be a blanket second-candidate block — breadth is
    the entire point of the raised budget."""
    budget = tools.BacktestBudget()
    a = _active_config(); a["max_positions"] = 20
    b = _active_config(); b["delta_engine"]["orphan_confirmation_days"] = 5
    _call_full({"config": a, "hypothesis": "h", "mechanism": "concentration_control"},
               budget)
    out = _call_full({"config": b, "hypothesis": "slower exits",
                      "mechanism": "exit_hysteresis"}, budget)
    assert "queued full-config candidate" in out, out
    entries = _entries(env)
    assert len(entries) == 2
    assert {e["mechanism"] for e in entries} == {"concentration_control",
                                                 "exit_hysteresis"}
    assert entries[1]["changed_fields"] == ["delta_engine.orphan_confirmation_days"]


def test_the_queue_reply_reports_remaining_slots(env):
    """The model has to know how much capacity is left to decide whether to
    keep going — and is told to account for what it leaves idle."""
    budget = tools.BacktestBudget()
    cand = _active_config(); cand["max_positions"] = 20
    out = _call_full({"config": cand, "hypothesis": "h",
                      "mechanism": "concentration_control"}, budget)
    assert f"{tools.MAX_QUEUED_EXPERIMENTS - 1} experiment slot(s) left" in out
    assert "unused" in out


def test_full_config_missing_hypothesis_rejected(env):
    budget = tools.BacktestBudget()
    out = _call_full({"config": _active_config()}, budget)
    assert "hypothesis" in out
    assert budget.experiment_used == 0


# ── queue growth ─────────────────────────────────────────────────────────────

def test_finished_entries_are_trimmed_but_live_work_never_is():
    """Every entry embeds a COMPLETE StrategyConfig, and BOTH stacks read and
    rewrite the whole file under a lock on every queue write and lifecycle
    mark. RETAIN existed but was never applied, so the file grew forever and
    each write got slower. Pending/testing entries are live work — trimming one
    would drop a candidate the lane still has to run."""
    from app.proposals import trim_proposals
    old_done = [{"id": f"d{i}", "status": "tested"} for i in range(50)]
    live = [{"id": "p1", "status": "pending"}, {"id": "t1", "status": "testing"}]
    kept = trim_proposals(old_done + live, retain=10)
    ids = [e["id"] for e in kept]
    assert {"p1", "t1"} <= set(ids), "live work was trimmed"
    assert len([e for e in kept if e["status"] == "tested"]) == 10
    assert ids[-2:] == ["p1", "t1"], "order must be preserved"
    # the OLDEST finished entries are the ones dropped
    assert "d49" in ids and "d0" not in ids
    # under the cap nothing is touched
    assert trim_proposals(live, retain=10) == live
