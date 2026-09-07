#!/usr/bin/env python3
"""Frozen source overlays for targeted Champion path-divergence plateau tests."""
from __future__ import annotations

import ast

ARMS = ("SIZE_19", "SIZE_21", "SIZE_23")

PARAMS = {
    "SIZE_19": (19, "0.05263157894736842"),
    "SIZE_21": (21, "0.047619047619047616"),
    "SIZE_23": (23, "0.043478260869565216"),
}


def _replace_exact(text: str, old: str, new: str, count: int, label: str) -> str:
    actual = text.count(old)
    if actual != count:
        raise RuntimeError(f"{label}: expected {count} exact occurrence(s), got {actual}")
    return text.replace(old, new, count)


def apply_arm(text: str, arm: str) -> str:
    if arm not in ARMS:
        raise ValueError(f"unsupported arm: {arm}")
    slots, weight = PARAMS[arm]
    out = _replace_exact(text, "N_SLOTS = 25", f"N_SLOTS = {slots}", 1, f"{arm} slot capacity")
    out = _replace_exact(out, "ENTRY_W = 0.04", f"ENTRY_W = {weight}", 1, f"{arm} equal entry weight")
    ast.parse(out)
    assert_arm_contract(text, out, arm)
    return out


def assert_arm_contract(base: str, variant: str, arm: str) -> None:
    if arm not in ARMS:
        raise ValueError(arm)
    slots, weight = PARAMS[arm]
    if variant.count("book.receivables.append((gday+1,q*rawdiv))") != 1:
        raise RuntimeError("variant lost exact one-session dividend scheduling")
    if "book.receivables.append((gday+15" in variant.replace(" ", ""):
        raise RuntimeError("15-session dividend regression present")
    if "from backtester import champion_final_security_truth as _bestclass" not in variant:
        raise RuntimeError("factual classifier changed")
    if f"N_SLOTS = {slots}" not in variant:
        raise RuntimeError("slot capacity mismatch")
    if f"ENTRY_W = {weight}" not in variant:
        raise RuntimeError("entry weight mismatch")
    for invariant in (
        "COOLDOWN = 21",
        "REVIEW_AGE = 119",
        "STOP_RET = 0.70",
        "budget=len(ready) if not book.initialized else 1",
    ):
        if invariant not in variant:
            raise RuntimeError(f"certified invariant changed: {invariant}")
    if variant.count("s.ready_day=gday+COOLDOWN") != base.count("s.ready_day=gday+COOLDOWN"):
        raise RuntimeError("slot cooldown seam changed")
    if variant.count("_slot.ready_day=gday+COOLDOWN") != base.count("_slot.ready_day=gday+COOLDOWN"):
        raise RuntimeError("carried slot cooldown seam changed")
    if variant.count("book.sec_ready[") != base.count("book.sec_ready["):
        raise RuntimeError("security cooldown seam changed")


def arm_dimensions(arm: str) -> list[str]:
    slots, weight = PARAMS[arm]
    return [f"slots_25_to_{slots}_entry_weight_4pct_to_{weight}_nominal_capacity_preserved"]
