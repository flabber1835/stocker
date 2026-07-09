"""hypothesis_ledger validation/budget + preview_ranking's pure rank-delta math."""
import asyncio

import pandas as pd
import pytest

from app.tools import (
    BacktestBudget,
    hypothesis_ledger,
    ledger_validate,
    rank_delta,
    tool_definitions,
)


# ── ledger_validate (pure) ────────────────────────────────────────────────────

def test_create_requires_hypothesis():
    assert ledger_validate({"action": "create"}) is not None
    assert ledger_validate({"action": "create", "hypothesis": "  "}) is not None
    assert ledger_validate({"action": "create", "hypothesis": "momentum IC decaying"}) is None


def test_update_requires_id_and_a_change():
    assert ledger_validate({"action": "update"}) is not None                       # no id
    assert ledger_validate({"action": "update", "id": "x"}) is not None            # bad id
    assert ledger_validate({"action": "update", "id": 3}) is not None              # no change
    assert ledger_validate({"action": "update", "id": 3, "status": "confirmed"}) is None
    assert ledger_validate({"action": "update", "id": 3, "outcome": "backtest confirmed"}) is None


def test_status_enum_enforced():
    assert ledger_validate({"action": "update", "id": 1, "status": "maybe"}) is not None
    for s in ("open", "confirmed", "refuted", "abandoned"):
        assert ledger_validate({"action": "update", "id": 1, "status": s}) is None


def test_unknown_action_rejected():
    assert ledger_validate({"action": "delete", "id": 1}) is not None
    assert ledger_validate({}) is not None


def test_ledger_budget_and_invalid_write_burns_nothing():
    b = BacktestBudget()
    b.ledger_limit = 1
    # invalid write → rejected BEFORE the budget is taken
    out = asyncio.run(hypothesis_ledger({"action": "create"}, engine=None, budget=b))
    assert "rejected" in out and b.ledger_used == 0
    # budget exhaustion path (valid args, engine never reached after cap)
    b.ledger_used = 1
    out = asyncio.run(hypothesis_ledger(
        {"action": "create", "hypothesis": "h"}, engine=None, budget=b))
    assert "BUDGET EXHAUSTED" in out


# ── rank_delta (pure) ─────────────────────────────────────────────────────────

def _ranked(order: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"ticker": order, "rank": range(1, len(order) + 1)})


def test_rank_delta_membership_and_movers():
    active = _ranked(["AAA", "BBB", "CCC", "DDD", "EEE"])
    candidate = _ranked(["BBB", "AAA", "EEE", "CCC", "DDD"])
    out = rank_delta(active, candidate, top_n=3)
    assert out["top_n"] == 3
    entered = {e["ticker"] for e in out["entered_top_n"]}
    left = {e["ticker"] for e in out["left_top_n"]}
    assert entered == {"EEE"} and left == {"CCC"}
    assert out["membership_change_count"] == 1
    movers = {m["ticker"]: m["delta"] for m in out["biggest_movers"]}
    assert movers["EEE"] == 2          # rank 5 → 3 (positive = improved)
    assert out["rank_correlation"] is not None


def test_rank_delta_identical_rankings_no_changes():
    active = _ranked(["AAA", "BBB", "CCC"])
    out = rank_delta(active, active.copy(), top_n=2)
    assert out["membership_change_count"] == 0
    assert out["biggest_movers"] == []
    assert out["rank_correlation"] == pytest.approx(1.0)


def test_rank_delta_handles_dropped_ticker():
    active = _ranked(["AAA", "BBB", "CCC"])
    candidate = _ranked(["AAA", "BBB"])   # CCC unrankable under candidate
    out = rank_delta(active, candidate, top_n=3)
    assert {e["ticker"] for e in out["left_top_n"]} == {"CCC"}
    assert out["ranked_candidate"] == 2


# ── tool defs ─────────────────────────────────────────────────────────────────

def test_new_tools_registered():
    names = {d["name"] for d in tool_definitions()}
    assert {"preview_ranking", "hypothesis_ledger"} <= names


def test_preview_budget_counts():
    b = BacktestBudget()
    b.preview_limit = 2
    assert b.take_preview() and b.take_preview()
    assert not b.take_preview()
