"""The evaluator's feedback loop: can a review SEE the outcome of its own
candidates, and is it told the truth about how a config change happens?

The loop is: author a complete candidate (queue_strategy_experiment) → wind
tunnel scores it on tune + held-out validate → a deterministic gate promotes a
winner as the LIVE config. Every step of that is invisible to the next review
unless the packet carries it, and unavailable unless the prompt names the right
tool. Both had silently drifted; these tests pin them.
"""
import json
import os

import pytest

from app.packet import _backtest_lab, _experiment_lane, _experiment_queue


def _write(tmp_path, name, obj):
    os.makedirs(tmp_path / "bt", exist_ok=True)
    with open(tmp_path / "bt" / name, "w") as f:
        json.dump(obj, f)


# ── experiment_lane must carry the gate's verdict ────────────────────────────

def _lane_entry(**over):
    """An entry shaped EXACTLY as bt-scheduler's _experiment_lane writes it."""
    e = {
        "id": "cand-1", "kind": "full_config", "status": "success",
        "hypothesis": "fewer names concentrate the edge",
        "config_hash": "abc123", "diff_vs_active": {"portfolio_builder.max_positions":
                                                    {"from": 30, "to": 17}},
        "windows": {"tune_start": "2023-07-25", "tune_end": "2025-07-25",
                    "validate_start": "2025-07-25", "validate_end": "2026-07-25"},
        "fired_at": "2026-07-20T22:00:00", "completed_at": "2026-07-20T23:10:00",
        "result": {"tune": {"annualized_return": 0.21},
                   "validate": {"annualized_return": 0.18}},
        "promotion": {"eligible": False,
                      "reason": "edge does NOT survive validation: out-of-sample "
                                "CAGR -0.0300 vs baseline (tol 0.0000)"},
    }
    e.update(over)
    return e


def test_lane_surfaces_the_promotion_verdict(tmp_path, monkeypatch):
    """The system prompt tells the model to read the gate's verdict + reason
    here and to note which candidates were auto-promoted. The projection used
    to drop `promotion` entirely, so the model saw a CAGR and never learned
    whether — or why — its own candidate was refused."""
    monkeypatch.setenv("ARTIFACTS_PATH", str(tmp_path))
    _write(tmp_path, "experiments.json", {"experiments": [_lane_entry()]})
    out = _experiment_lane()
    assert out["available"] is True
    row = out["experiments"][0]
    assert row["promotion"]["eligible"] is False
    assert "survive validation" in row["promotion"]["reason"]
    # and the windows it was judged on, and the join key back to the queue
    assert row["windows"]["validate_end"] == "2026-07-25"
    assert row["config_hash"] == "abc123"


def test_lane_shows_an_auto_promoted_candidate_as_such(tmp_path, monkeypatch):
    monkeypatch.setenv("ARTIFACTS_PATH", str(tmp_path))
    _write(tmp_path, "experiments.json", {"experiments": [
        _lane_entry(promotion={"eligible": True, "reason": "tune edge +0.0400 >= "
                                                           "+0.0100 AND validate edge "
                                                           "+0.0200 holds"})]})
    row = _experiment_lane()["experiments"][0]
    assert row["promotion"]["eligible"] is True
    assert "eligible=true" in _experiment_lane()["note"]


# ── the queue must not be buried in a section the model is told to skip ──────

def test_experiment_queue_is_reachable_without_the_retired_lab_section(tmp_path, monkeypatch):
    """backtest_lab's own note says the grid is RETIRED and not to expect it.
    The queue used to live ONLY inside that section, so the record of what the
    evaluator had queued sat behind an instruction to skip it."""
    monkeypatch.setenv("ARTIFACTS_PATH", str(tmp_path))
    _write(tmp_path, "proposals.json", {"proposals": [
        {"id": "p1", "kind": "full_config", "status": "pending",
         "hypothesis": "h", "config_hash": "abc123",
         "queued_against_config_hash": "live-1",
         "diff": {"portfolio_builder.max_positions": {"from": 30, "to": 17}}}]})
    top = _experiment_queue()
    assert top["available"] is True and top["counts"]["pending"] == 1
    row = top["recent"][0]
    assert row["id"] == "p1", "no join key back to experiment_lane"
    assert row["changes"]["portfolio_builder.max_positions"].endswith("-> 17")
    # still mirrored inside backtest_lab for back-compat
    assert _backtest_lab()["experiment_queue"]["counts"]["pending"] == 1


def test_pending_candidate_is_flagged_stale_after_a_promotion(tmp_path, monkeypatch):
    """A candidate is a WHOLE config frozen at queue time. If a promotion made a
    different config live meanwhile, promoting this one would silently REVERT
    that change — and its stored diff was computed against a config that is no
    longer active. The review has to be able to see that."""
    monkeypatch.setenv("ARTIFACTS_PATH", str(tmp_path))
    strat = os.path.join(os.path.dirname(__file__), "..", "..",
                         "strategies", "quality_core_v1.yaml")
    monkeypatch.setenv("STRATEGY_CONFIG_PATH", os.path.abspath(strat))
    _write(tmp_path, "proposals.json", {"proposals": [
        {"id": "stale", "kind": "full_config", "status": "pending", "hypothesis": "h",
         "config_hash": "c1", "queued_against_config_hash": "a-superseded-hash"},
        {"id": "done", "kind": "full_config", "status": "tested", "hypothesis": "h",
         "config_hash": "c2", "queued_against_config_hash": "a-superseded-hash"},
    ]})
    rows = {r["id"]: r for r in _experiment_queue()["recent"]}
    assert rows["stale"]["stale_vs_active_config"] is True
    # only PENDING work can still be affected — a finished run isn't flagged
    assert "stale_vs_active_config" not in rows["done"]


def test_queue_writes_record_the_config_they_were_authored_against(tmp_path, monkeypatch):
    """The staleness flag above is only possible if the tool stamps it."""
    import asyncio

    import yaml

    import app.tools as tools
    monkeypatch.setenv("ARTIFACTS_PATH", str(tmp_path))
    strat = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..",
                                         "strategies", "quality_core_v1.yaml"))
    monkeypatch.setattr(tools, "STRATEGY_CONFIG_PATH", strat)
    cand = yaml.safe_load(open(strat))
    cand["portfolio_builder"]["max_positions"] = 19
    out = asyncio.run(tools.queue_strategy_experiment(
        {"config": cand, "hypothesis": "concentration"}, budget=tools.BacktestBudget()))
    assert "queued full-config candidate" in out, out
    entry = json.load(open(tmp_path / "bt" / "proposals.json"))["proposals"][0]
    assert entry["queued_against_config_hash"], "no lineage stamp on the candidate"


# ── the prompt must name the tool that actually exists ───────────────────────

def test_tool_addendum_names_the_real_config_change_tool(monkeypatch):
    """The addendum advertised `queue_experiment` — deleted with the one-click
    apply — and never mentioned queue_strategy_experiment, while ALSO telling
    the model its recommendations were queued automatically (they are not).
    Net effect: the only lever on the live config was undocumented and the
    model was told not to pull it."""
    import app.tools as tools
    from app.agent import TOOLS_ADDENDUM
    # web_search is key-gated; enable it so the full surface is compared (its
    # absence is separately announced by WEB_SEARCH_UNAVAILABLE_NOTE).
    monkeypatch.setattr(tools, "TAVILY_API_KEY", "test-key")
    names = {t["name"] for t in tools.tool_definitions()}
    assert "queue_strategy_experiment" in TOOLS_ADDENDUM
    assert "queued automatically" not in TOOLS_ADDENDUM
    # every tool the addendum's tool list documents must actually be callable
    # (the list runs from "Available tools:" to the "Discipline:" bullets)
    tool_list = TOOLS_ADDENDUM.split("Available tools:", 1)[1].split("Discipline:", 1)[0]
    documented = {line[2:].split(":", 1)[0].strip()
                  for line in tool_list.splitlines() if line.startswith("- ")}
    assert documented, "could not parse the addendum's tool list"
    assert documented <= names, f"addendum documents non-existent tool(s) {documented - names}"


@pytest.mark.parametrize("phrase", [
    "queue_strategy_experiment",     # the lever
    "auto-applied as the live config",  # what winning does
])
def test_system_prompt_states_how_a_config_change_happens(phrase):
    from app.report import SYSTEM_PROMPT
    assert phrase in SYSTEM_PROMPT


def test_system_prompt_does_not_claim_a_human_applies_changes():
    """It used to say 'a human applies them' one line above 'nothing is applied
    by a human click' — contradictory instructions about the only lever."""
    from app.report import SYSTEM_PROMPT
    assert "a human applies them" not in SYSTEM_PROMPT
