"""queue_experiment — the evaluator's enqueue-only wind-tunnel write.

The tool must only ever APPEND schema-validated, pending, exploratory entries
to artifacts/bt/proposals.json: same single-field diff shape, same shared
literal parser, same dedupe-any-status and PENDING_CAP as the recommendation
harvest. It can never run anything, alter existing entries, or burn budget on
a rejected call.
"""
import asyncio
import json
import os

import pytest

import app.tools as tools
from app.proposals import PENDING_CAP, proposal_id, queue_exploratory

STRAT = os.path.join(os.path.dirname(__file__), "..", "..",
                     "strategies", "quality_core_v1.yaml")
_KW = dict(run_id=None, iso_week="2026-W29", now_iso="2026-07-19T00:00:00+00:00")


# ── pure queue_exploratory ────────────────────────────────────────────────────

def test_queues_pending_exploratory_entry():
    content, result = queue_exploratory(
        "portfolio_builder.max_positions", 25, "fewer names concentrate alpha",
        None, **_KW)
    assert result["queued"] is True
    (entry,) = content["proposals"]
    assert entry["status"] == "pending"
    assert entry["origin"] == "exploratory"
    assert entry["hypothesis"] == "fewer names concentrate alpha"
    assert entry["config_field"] == "portfolio_builder.max_positions"
    assert entry["value"] == 25
    assert entry["id"] == proposal_id("portfolio_builder.max_positions", 25)


@pytest.mark.parametrize("status", ["pending", "testing", "tested", "invalid"])
def test_dedupe_against_any_status_reports_it(status):
    existing = {"proposals": [{
        "id": proposal_id("f.x", 1), "config_field": "f.x", "value": 1,
        "status": status}]}
    content, result = queue_exploratory("f.x", 1, "h", existing, **_KW)
    assert result["queued"] is False
    assert result["status"] == status
    assert len(content["proposals"]) == 1          # nothing appended


def test_pending_cap_blocks_queue():
    existing = {"proposals": [
        {"id": f"e{i}", "config_field": f"f.{i}", "value": i, "status": "pending"}
        for i in range(PENDING_CAP)]}
    content, result = queue_exploratory("f.new", 9, "h", existing, **_KW)
    assert result["queued"] is False
    assert "cap" in result["reason"]
    assert len(content["proposals"]) == PENDING_CAP


def test_hypothesis_capped_at_300_chars():
    content, result = queue_exploratory("f.x", 1, "h" * 500, None, **_KW)
    assert result["queued"] is True
    assert len(content["proposals"][0]["hypothesis"]) == 300


# ── tool level (execute_tool → file on disk) ─────────────────────────────────

@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACTS_PATH", str(tmp_path))
    monkeypatch.setattr(tools, "STRATEGY_CONFIG_PATH", STRAT)
    return tmp_path


def _call(args, budget):
    return asyncio.run(tools.execute_tool(
        "queue_experiment", args, engine=None, budget=budget))


def _entries(tmp_path):
    with open(tmp_path / "bt" / "proposals.json") as f:
        return json.load(f)["proposals"]


def test_tool_queues_and_writes_file(env):
    budget = tools.BacktestBudget()
    out = json.loads(_call({"config_field": "portfolio_builder.max_positions",
                            "suggested_value": "25",
                            "hypothesis": "smaller book concentrates alpha"}, budget))
    assert out["queued"] is True
    (entry,) = _entries(env)
    assert entry["origin"] == "exploratory"
    assert entry["value"] == 25                    # parsed literal, not the string
    assert entry["status"] == "pending"
    assert budget.experiment_used == 1
    assert "NEXT weekly" in out["note"]


def test_duplicate_reports_status_and_refunds_budget(env):
    budget = tools.BacktestBudget()
    args = {"config_field": "portfolio_builder.max_positions",
            "suggested_value": "25", "hypothesis": "h"}
    _call(args, budget)
    out = json.loads(_call(args, budget))
    assert out["queued"] is False and out["status"] == "pending"
    assert len(_entries(env)) == 1
    assert budget.experiment_used == 1             # second call refunded


def test_invalid_diff_rejected_without_queueing(env):
    budget = tools.BacktestBudget()
    out = _call({"config_field": "no_such_section.knob",
                 "suggested_value": "1", "hypothesis": "h"}, budget)
    assert "INVALID" in out
    assert budget.experiment_used == 0             # refunded
    assert not os.path.exists(env / "bt" / "proposals.json")


def test_prose_value_rejected_before_budget(env):
    budget = tools.BacktestBudget()
    out = _call({"config_field": "portfolio_builder.max_positions",
                 "suggested_value": "reduce by half", "hypothesis": "h"}, budget)
    assert "not a literal" in out
    assert budget.experiment_used == 0


def test_missing_hypothesis_rejected(env):
    budget = tools.BacktestBudget()
    out = _call({"config_field": "portfolio_builder.max_positions",
                 "suggested_value": "25"}, budget)
    assert "hypothesis" in out
    assert budget.experiment_used == 0


def test_budget_exhaustion_message(env):
    budget = tools.BacktestBudget()
    budget.experiment_limit = 1
    _call({"config_field": "portfolio_builder.max_positions",
           "suggested_value": "25", "hypothesis": "h"}, budget)
    out = _call({"config_field": "portfolio_builder.max_positions",
                 "suggested_value": "20", "hypothesis": "h"}, budget)
    assert "EXPERIMENT BUDGET EXHAUSTED" in out
    assert len(_entries(env)) == 1


def test_pending_cap_at_tool_level_refunds_budget(env):
    os.makedirs(env / "bt", exist_ok=True)
    with open(env / "bt" / "proposals.json", "w") as f:
        json.dump({"proposals": [
            {"id": f"e{i}", "config_field": f"f.{i}", "value": i,
             "status": "pending"} for i in range(PENDING_CAP)]}, f)
    budget = tools.BacktestBudget()
    out = json.loads(_call({"config_field": "portfolio_builder.max_positions",
                            "suggested_value": "25", "hypothesis": "h"}, budget))
    assert out["queued"] is False and "cap" in out["reason"]
    assert budget.experiment_used == 0
    assert len(_entries(env)) == PENDING_CAP


def test_tool_definition_present_with_required_params():
    (tdef,) = [t for t in tools.tool_definitions() if t["name"] == "queue_experiment"]
    assert set(tdef["parameters"]["required"]) == {
        "config_field", "suggested_value", "hypothesis"}
    assert "WITHOUT recommending" in tdef["description"]


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
