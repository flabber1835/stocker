"""Capacity-gate parity with the risk service (the 'proposed-then-rejected' fix).

Reproduces the production symptom: the planner admitted a NEW entry that the risk
gate then rejected at the open with "Portfolio at capacity", because the gate
counts in-flight (queued, unfilled) ENTRY orders as already occupying a slot while
the planner saw only live_positions. The engine now receives the same in-flight
view, so it defers the entry to `watch` instead of generating a doomed order.
"""
from datetime import date, timedelta
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../services/pipeline/app"))

from engine import evaluate_target_vs_live, RankObservation  # noqa: E402


def _obs(rank: int, days: int = 3, base: date = date(2025, 1, 1)):
    return [
        RankObservation(run_date=base + timedelta(days - 1 - i), rank=rank,
                        composite_score=round(1.0 / rank, 6))
        for i in range(days)
    ]


# A clean, full-ish book: two holds in the target, one NEW entry candidate.
MAX_POS = 3
TARGET = {"H1": 0.3, "H2": 0.3, "NEW": 0.3}
LIVE = {"H1", "H2"}
UNIVERSE = {"H1": _obs(1), "H2": _obs(2), "NEW": _obs(3)}


def _decide(**kw):
    return evaluate_target_vs_live(
        target_portfolio=TARGET,
        live_positions=LIVE,
        universe=UNIVERSE,
        confirmation_days=3,
        max_positions=MAX_POS,
        orphan_confirmation_days=2,
        # account_value/buying_power left None → cash gate skipped, capacity isolated
        **kw,
    )


def test_new_entry_admitted_when_no_inflight():
    """Control: 2 held + 1 free slot → NEW is a real entry."""
    decisions = _decide()
    assert decisions["NEW"].action == "entry"


def test_new_entry_deferred_when_inflight_entry_takes_last_slot():
    """THE FIX: a queued-but-unfilled entry (Q1) already claims slot 3, so NEW no
    longer fits — the planner defers it to `watch` instead of emitting an order the
    gate would reject at the open."""
    decisions = _decide(inflight_entries={"Q1"})
    assert decisions["NEW"].action == "watch"
    assert "capacity" in decisions["NEW"].reason.lower()


def test_inflight_exit_frees_a_slot_for_the_new_entry():
    """An orphan held at the broker with a queued EXIT order frees its slot, so a
    new entry fits even though the book looks full."""
    live = {"H1", "H2", "ORPH"}              # 3 held = full at MAX_POS=3
    decisions = evaluate_target_vs_live(
        target_portfolio={"H1": 0.3, "H2": 0.3, "NEW": 0.3},  # ORPH dropped → orphan
        live_positions=live,
        universe={"H1": _obs(1), "H2": _obs(2), "NEW": _obs(3), "ORPH": _obs(50)},
        confirmation_days=3,
        max_positions=3,
        orphan_confirmation_days=2,
        inflight_exits={"ORPH"},             # its sell is already queued → slot freeing
    )
    assert decisions["NEW"].action == "entry"


def test_inflight_entry_already_for_same_ticker_is_not_re_emitted():
    """If NEW itself already has a queued entry order, the planner must not emit a
    second entry for it (duplicate) — it defers to `watch`."""
    decisions = _decide(inflight_entries={"NEW"})
    assert decisions["NEW"].action == "watch"
