#!/usr/bin/env python3
"""Frozen source overlays for the second five corrected Champion experiments."""
from __future__ import annotations

import ast

ARMS = (
    "CONCENTRATED_20",
    "DIVERSIFIED_30",
    "LATE_REVIEW_159",
    "LONGER_SLOT_COOLDOWN_42",
    "TIGHTER_STOP_25",
)


def _replace_exact(text: str, old: str, new: str, count: int, label: str) -> str:
    actual = text.count(old)
    if actual != count:
        raise RuntimeError(f"{label}: expected {count} exact occurrence(s), got {actual}")
    return text.replace(old, new, count)


def _concentrated_20(text: str) -> str:
    text = _replace_exact(text, "N_SLOTS = 25", "N_SLOTS = 20", 1, "20-slot capacity")
    text = _replace_exact(text, "ENTRY_W = 0.04", "ENTRY_W = 0.05", 1, "20-slot equal entry weight")
    return text


def _diversified_30(text: str) -> str:
    text = _replace_exact(text, "N_SLOTS = 25", "N_SLOTS = 30", 1, "30-slot capacity")
    text = _replace_exact(
        text, "ENTRY_W = 0.04", "ENTRY_W = 0.03333333333333333", 1,
        "30-slot equal entry weight",
    )
    return text


def _late_review_159(text: str) -> str:
    return _replace_exact(text, "REVIEW_AGE = 119", "REVIEW_AGE = 159", 1, "late review age")


def _longer_slot_cooldown_42(text: str) -> str:
    # Change only slot availability. Security-specific sec_ready remains on COOLDOWN=21.
    text = _replace_exact(
        text, "s.ready_day=gday+COOLDOWN", "s.ready_day=gday+42", 3,
        "ordinary/terminal slot reuse delay",
    )
    text = _replace_exact(
        text, "_slot.ready_day=gday+COOLDOWN", "_slot.ready_day=gday+42", 1,
        "carried-terminal slot reuse delay",
    )
    return text


def _tighter_stop_25(text: str) -> str:
    return _replace_exact(text, "STOP_RET = 0.70", "STOP_RET = 0.75", 1, "25-percent trailing stop")


def apply_arm(text: str, arm: str) -> str:
    if arm not in ARMS:
        raise ValueError(f"unsupported arm: {arm}")
    if arm == "CONCENTRATED_20":
        out = _concentrated_20(text)
    elif arm == "DIVERSIFIED_30":
        out = _diversified_30(text)
    elif arm == "LATE_REVIEW_159":
        out = _late_review_159(text)
    elif arm == "LONGER_SLOT_COOLDOWN_42":
        out = _longer_slot_cooldown_42(text)
    elif arm == "TIGHTER_STOP_25":
        out = _tighter_stop_25(text)
    else:
        raise AssertionError(arm)
    ast.parse(out)
    assert_arm_contract(text, out, arm)
    return out


def assert_arm_contract(base: str, variant: str, arm: str) -> None:
    if arm not in ARMS:
        raise ValueError(arm)
    if variant.count("book.receivables.append((gday+1,q*rawdiv))") != 1:
        raise RuntimeError("variant lost exact one-session dividend scheduling")
    if "book.receivables.append((gday+15" in variant.replace(" ", ""):
        raise RuntimeError("15-session dividend regression present")
    if "from backtester import champion_final_security_truth as _bestclass" not in variant:
        raise RuntimeError("factual classifier changed")
    if "budget=len(ready) if not book.initialized else 1" not in variant:
        raise RuntimeError("one-at-a-time initialized admission throttle changed")

    # Explicitly protect baseline semantics that are not the active arm.
    expected_slots = 25
    expected_weight = "0.04"
    expected_review = 119
    expected_stop = "0.70"

    if arm == "CONCENTRATED_20":
        expected_slots = 20
        expected_weight = "0.05"
    elif arm == "DIVERSIFIED_30":
        expected_slots = 30
        expected_weight = "0.03333333333333333"
    elif arm == "LATE_REVIEW_159":
        expected_review = 159
    elif arm == "TIGHTER_STOP_25":
        expected_stop = "0.75"

    if f"N_SLOTS = {expected_slots}" not in variant:
        raise RuntimeError("slot-capacity arm mismatch")
    if f"ENTRY_W = {expected_weight}" not in variant:
        raise RuntimeError("entry-weight arm mismatch")
    if f"REVIEW_AGE = {expected_review}" not in variant:
        raise RuntimeError("review-age arm mismatch")
    if f"STOP_RET = {expected_stop}" not in variant:
        raise RuntimeError("stop arm mismatch")
    if "COOLDOWN = 21" not in variant:
        raise RuntimeError("security-specific cooldown constant changed")

    if arm == "LONGER_SLOT_COOLDOWN_42":
        if variant.count("s.ready_day=gday+42") != 3 or variant.count("_slot.ready_day=gday+42") != 1:
            raise RuntimeError("42-session slot delay not applied exactly")
        if "s.ready_day=gday+COOLDOWN" in variant or "_slot.ready_day=gday+COOLDOWN" in variant:
            raise RuntimeError("baseline slot delay remains in 42-session arm")
        if variant.count("book.sec_ready[") != base.count("book.sec_ready["):
            raise RuntimeError("security-specific cooldown seam changed")
    else:
        if variant.count("s.ready_day=gday+COOLDOWN") != base.count("s.ready_day=gday+COOLDOWN"):
            raise RuntimeError("slot cooldown changed in unauthorized arm")
        if variant.count("_slot.ready_day=gday+COOLDOWN") != base.count("_slot.ready_day=gday+COOLDOWN"):
            raise RuntimeError("carried slot cooldown changed in unauthorized arm")


def arm_dimensions(arm: str) -> list[str]:
    return {
        "CONCENTRATED_20": ["slots_25_to_20_entry_weight_4pct_to_5pct_nominal_capacity_preserved"],
        "DIVERSIFIED_30": ["slots_25_to_30_entry_weight_4pct_to_3p333pct_nominal_capacity_preserved"],
        "LATE_REVIEW_159": ["review_age_119_to_159"],
        "LONGER_SLOT_COOLDOWN_42": ["slot_reuse_delay_21_to_42_security_cooldown_unchanged_21"],
        "TIGHTER_STOP_25": ["trailing_stop_drawdown_30pct_to_25pct"],
    }[arm]
