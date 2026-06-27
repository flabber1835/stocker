"""Unit tests for the canonical capacity rule (shared by planner + risk gate).

These lock the projected-book arithmetic that the delta engine's
`_allocate_capacity` and the risk-service MAX_POSITIONS gate BOTH apply — so the
two can never drift and "planner admits" stays equivalent to "gate approves".
"""
from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "shared"))

from stock_strategy_shared.capacity import (  # noqa: E402
    projected_book_count,
    fits_within_capacity,
    select_entries_within_capacity,
)


# ── projected_book_count ─────────────────────────────────────────────────────

def test_projected_counts_held_minus_exits_plus_new():
    held = {"A", "B", "C"}
    exiting = {"C"}
    entering = {"D", "E"}
    # (3 - 1) + 2 = 4
    assert projected_book_count(held, exiting, entering) == 4


def test_projected_excludes_entering_already_held():
    held = {"A", "B"}
    # "A" is "entering" but already held → not a new slot
    assert projected_book_count(held, set(), {"A", "C"}) == 3  # A,B + C


def test_projected_exit_of_unheld_is_noop():
    # exiting a name that isn't held can't reduce the count below held
    assert projected_book_count({"A", "B"}, {"Z"}, set()) == 2


# ── fits_within_capacity ─────────────────────────────────────────────────────

def test_fits_at_boundary_rejected():
    held = {f"T{i}" for i in range(35)}  # full book
    # no exits, one brand-new name → would be 36 > 35
    assert fits_within_capacity(held, set(), set(), "NEW", 35) is False


def test_fits_when_an_exit_frees_a_slot():
    held = {f"T{i}" for i in range(35)}
    # one held name leaving frees exactly one slot for the new name → 35
    assert fits_within_capacity(held, {"T0"}, set(), "NEW", 35) is True


def test_already_held_candidate_always_fits():
    held = {f"T{i}" for i in range(35)}
    assert fits_within_capacity(held, set(), set(), "T0", 35) is True


def test_inflight_entry_consumes_the_last_slot():
    # 34 held + 1 in-flight (queued, unfilled) entry already claims slot 35.
    held = {f"T{i}" for i in range(34)}
    entering = {"QUEUED"}  # in-flight entry
    # adding another new name → 34 + 1(queued) + 1(new) = 36 > 35 → rejected.
    # THIS is the case the gate rejected at the open but the planner used to admit.
    assert fits_within_capacity(held, set(), entering, "NEW", 35) is False


def test_no_cap_when_max_non_positive():
    assert fits_within_capacity({"A"}, set(), set(), "NEW", 0) is True
    assert fits_within_capacity({"A"}, set(), set(), "NEW", -1) is True


# ── select_entries_within_capacity ───────────────────────────────────────────

def test_select_admits_best_rank_first_until_full():
    held = {f"T{i}" for i in range(33)}  # 2 free slots
    admitted, deferred = select_entries_within_capacity(
        held, set(), ["A", "B", "C", "D"], max_positions=35,
    )
    assert admitted == {"A", "B"}          # first two fit
    assert deferred == {"C", "D"}          # rest deferred → watch


def test_select_inflight_entry_reduces_free_slots():
    # 33 held + 1 in-flight entry → only 1 truly free slot left.
    held = {f"T{i}" for i in range(33)}
    admitted, deferred = select_entries_within_capacity(
        held, set(), ["A", "B"], max_positions=35,
        inflight_entries={"QUEUED"},
    )
    assert admitted == {"A"}               # only one slot left after the queued entry
    assert deferred == {"B"}


def test_select_confirmed_exit_frees_a_slot():
    held = {f"T{i}" for i in range(35)}     # full
    admitted, deferred = select_entries_within_capacity(
        held, {"T0", "T1"}, ["A", "B", "C"], max_positions=35,
    )
    assert admitted == {"A", "B"}          # two exits → two slots
    assert deferred == {"C"}


def test_select_duplicate_of_inflight_entry_is_deferred():
    held = {f"T{i}" for i in range(10)}
    admitted, deferred = select_entries_within_capacity(
        held, set(), ["QUEUED", "A"], max_positions=35,
        inflight_entries={"QUEUED"},
    )
    assert "QUEUED" in deferred            # don't re-admit an already-queued entry
    assert "A" in admitted


def test_select_no_cap_admits_all():
    admitted, deferred = select_entries_within_capacity(
        {"A"}, set(), ["B", "C", "D"], max_positions=0,
    )
    assert admitted == {"B", "C", "D"} and deferred == set()


# ── parity: planner selection ⇔ gate projected count ─────────────────────────

def test_planner_admits_iff_gate_would_approve():
    """For the same inputs, every entry the planner ADMITS keeps the projected
    book ≤ cap (gate approves), and every DEFERRED one would exceed it (gate
    rejects). This is the invariant that stops the 'proposed-then-rejected' class."""
    held = {f"T{i}" for i in range(32)}
    exiting = {"T0"}
    inflight = {"Q1"}
    ranked = ["A", "B", "C", "D", "E"]
    max_positions = 35
    admitted, deferred = select_entries_within_capacity(
        held, exiting, ranked, max_positions, inflight_entries=inflight,
    )
    # Reconstruct the gate's view as entries settle in admit order.
    entering = set(inflight)
    for t in ranked:
        if t in admitted:
            # gate: projected WITH this entry must be within cap
            assert projected_book_count(held, exiting, entering | {t}) <= max_positions
            entering.add(t)
        elif t in deferred and t not in inflight:
            # gate: adding this one would exceed the cap
            assert projected_book_count(held, exiting, entering | {t}) > max_positions
