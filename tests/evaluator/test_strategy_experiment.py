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
    out = _call_full({"config": cand, "hypothesis": "concentration lifts CAGR"},
                     budget)
    assert "queued full-config candidate" in out
    (entry,) = _entries(env)
    assert entry["kind"] == "full_config" and entry["status"] == "pending"
    assert entry["diff"]["max_positions"] == {"from": 30, "to": 20}
    assert entry["config"]["max_positions"] == 20
    assert budget.experiment_used == 1


def test_full_config_identical_to_active_rejected(env):
    budget = tools.BacktestBudget()
    out = _call_full({"config": _active_config(), "hypothesis": "h"}, budget)
    assert "identical to the active config" in out
    assert budget.experiment_used == 0


def test_full_config_duplicate_refunds_budget(env):
    budget = tools.BacktestBudget()
    cand = _active_config()
    cand["max_positions"] = 20
    _call_full({"config": cand, "hypothesis": "h1"}, budget)
    out = _call_full({"config": cand, "hypothesis": "h2 different"}, budget)
    assert "already queued" in out
    assert len(_entries(env)) == 1
    assert budget.experiment_used == 1


def test_full_config_schema_invalid_rejected_before_budget(env):
    budget = tools.BacktestBudget()
    cand = _active_config()
    cand["max_positions"] = -5                    # schema violation
    out = _call_full({"config": cand, "hypothesis": "h"}, budget)
    assert "schema validation" in out
    assert budget.experiment_used == 0


def test_full_config_missing_hypothesis_rejected(env):
    budget = tools.BacktestBudget()
    out = _call_full({"config": _active_config()}, budget)
    assert "hypothesis" in out
    assert budget.experiment_used == 0
