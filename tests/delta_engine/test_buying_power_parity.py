"""F2 — buying-power: planner ↔ runtime gate relationship.

Unlike capacity/turnover, there is NO buying-power gate in the risk service. The
planner's `_cap_buys` defers buys that available cash (buying_power + credited
exit/trim proceeds) can't fund; the RUNTIME enforcement is the trade-executor
DRAIN (sells-first, fill-gated, re-sizes buys to fit live buying power) plus
Alpaca itself. So a planner/runtime divergence here is ABSORBED (deferred /
re-sized) rather than hard-rejected — which is why this is lower-severity than the
capacity bug. These tests lock the planner half of that contract.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../services/pipeline/app"))

from engine import _cap_buys, DeltaDecision  # noqa: E402


def _entry(ticker, rank, weight):
    return DeltaDecision(
        ticker=ticker, action="entry", rank=rank, composite_score=1.0 / rank,
        confirmation_days_met=1, current_weight=weight, reason="entry",
    )


def test_unfunded_entries_deferred_to_watch():
    # account 100k, buying_power 0, no exit proceeds → nothing affordable.
    decisions = {"A": _entry("A", 1, 0.05), "B": _entry("B", 2, 0.05)}
    _cap_buys(decisions, live_positions=set(), max_positions=35,
              actual_weights={}, account_value=100_000.0, buying_power=0.0)
    assert decisions["A"].action == "watch"
    assert decisions["B"].action == "watch"


def test_partial_buying_power_funds_best_rank_first():
    # buying_power covers ~one 5% position (5k of 100k). Best rank (A) funds; B defers.
    decisions = {"A": _entry("A", 1, 0.05), "B": _entry("B", 2, 0.05)}
    _cap_buys(decisions, live_positions=set(), max_positions=35,
              actual_weights={}, account_value=100_000.0, buying_power=5_000.0)
    assert decisions["A"].action == "entry"
    assert decisions["B"].action == "watch"


def test_exit_proceeds_fund_a_rotation_at_zero_buying_power():
    # A fully-invested rotation: 0 buying power, but an exit frees 5% → funds one entry.
    decisions = {
        "OUT": DeltaDecision(ticker="OUT", action="exit", rank=99, composite_score=0.0,
                             confirmation_days_met=2, current_weight=None, reason="exit"),
        "IN": _entry("IN", 1, 0.05),
    }
    _cap_buys(decisions, live_positions={"OUT"}, max_positions=35,
              actual_weights={"OUT": 0.05}, account_value=100_000.0, buying_power=0.0)
    assert decisions["IN"].action == "entry"   # exit proceeds funded the entry


def test_cash_gate_skipped_when_inputs_absent():
    # Without account_value/buying_power the planner leaves the executor/risk as the
    # cash backstop — entries are NOT demoted here.
    decisions = {"A": _entry("A", 1, 0.99)}
    _cap_buys(decisions, live_positions=set(), max_positions=35,
              actual_weights={}, account_value=None, buying_power=None)
    assert decisions["A"].action == "entry"
