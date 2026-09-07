#!/usr/bin/env python3
"""Frozen Caesar 20 overlays for final pre-hardening robustness validation."""
from __future__ import annotations

import ast

ARMS = (
    "JACKKNIFE_BUCKET_0",
    "JACKKNIFE_BUCKET_1",
    "JACKKNIFE_BUCKET_2",
    "JACKKNIFE_BUCKET_3",
    "JACKKNIFE_BUCKET_4",
    "LIQ_ADV40M",
    "LIQ_ADV80M",
    "LIQ_DAYDV10M",
)


def _replace_exact(text: str, old: str, new: str, count: int, label: str) -> str:
    actual = text.count(old)
    if actual != count:
        raise RuntimeError(f"{label}: expected {count} exact occurrence(s), got {actual}")
    return text.replace(old, new, count)


def _caesar20(text: str) -> str:
    text = _replace_exact(text, "N_SLOTS = 25", "N_SLOTS = 20", 1, "Caesar 20 capacity")
    text = _replace_exact(text, "ENTRY_W = 0.04", "ENTRY_W = 0.05", 1, "Caesar 20 weight")
    return text


def apply_arm(text: str, arm: str) -> str:
    if arm not in ARMS:
        raise ValueError(arm)
    out = _caesar20(text)

    if arm.startswith("JACKKNIFE_BUCKET_"):
        bucket = int(arm.rsplit("_", 1)[1])
        old = "if tid in heldids or tid in resids or book.sec_ready.get(tid,-1)>gday or tid in term_tids: continue"
        new = old.replace(": continue", f" or int(sid[int(tid)])%5=={bucket}: continue")
        out = _replace_exact(out, old, new, 1, f"deterministic security jackknife bucket {bucket}")
    elif arm == "LIQ_ADV40M":
        out = _replace_exact(out, "MIN_ADV20 = 20_000_000.0", "MIN_ADV20 = 40_000_000.0", 1, "ADV40M")
    elif arm == "LIQ_ADV80M":
        out = _replace_exact(out, "MIN_ADV20 = 20_000_000.0", "MIN_ADV20 = 80_000_000.0", 1, "ADV80M")
    elif arm == "LIQ_DAYDV10M":
        out = _replace_exact(out, "MIN_DAY_DV = 5_000_000.0", "MIN_DAY_DV = 10_000_000.0", 1, "DAYDV10M")
    else:
        raise AssertionError(arm)

    ast.parse(out)
    assert_arm_contract(text, out, arm)
    return out


def assert_arm_contract(base: str, variant: str, arm: str) -> None:
    if "N_SLOTS = 20" not in variant or "ENTRY_W = 0.05" not in variant:
        raise RuntimeError("Caesar 20 definition changed")
    if variant.count("book.receivables.append((gday+1,q*rawdiv))") != 1:
        raise RuntimeError("one-session dividend scheduling lost")
    if "book.receivables.append((gday+15" in variant.replace(" ", ""):
        raise RuntimeError("15-session dividend regression present")
    for invariant in (
        "from backtester import champion_final_security_truth as _bestclass",
        "COOLDOWN = 21",
        "REVIEW_AGE = 119",
        "STOP_RET = 0.70",
        "budget=len(ready) if not book.initialized else 1",
        "COST = 0.001",
    ):
        if invariant not in variant:
            raise RuntimeError(f"certified invariant changed: {invariant}")

    if arm.startswith("JACKKNIFE_BUCKET_"):
        bucket = int(arm.rsplit("_", 1)[1])
        token = f"int(sid[int(tid)])%5=={bucket}"
        if variant.count(token) != 1:
            raise RuntimeError(f"jackknife token mismatch for {arm}")
        if "MIN_ADV20 = 20_000_000.0" not in variant or "MIN_DAY_DV = 5_000_000.0" not in variant:
            raise RuntimeError("jackknife changed liquidity thresholds")
    elif arm == "LIQ_ADV40M":
        if "MIN_ADV20 = 40_000_000.0" not in variant:
            raise RuntimeError("ADV40M missing")
    elif arm == "LIQ_ADV80M":
        if "MIN_ADV20 = 80_000_000.0" not in variant:
            raise RuntimeError("ADV80M missing")
    elif arm == "LIQ_DAYDV10M":
        if "MIN_DAY_DV = 10_000_000.0" not in variant:
            raise RuntimeError("DAYDV10M missing")

    if variant.count("s.ready_day=gday+COOLDOWN") != base.count("s.ready_day=gday+COOLDOWN"):
        raise RuntimeError("slot cooldown seam changed")
    if variant.count("_slot.ready_day=gday+COOLDOWN") != base.count("_slot.ready_day=gday+COOLDOWN"):
        raise RuntimeError("carried cooldown seam changed")
    if variant.count("book.sec_ready[") != base.count("book.sec_ready["):
        raise RuntimeError("security cooldown seam changed")


def arm_dimensions(arm: str) -> list[str]:
    if arm.startswith("JACKKNIFE_BUCKET_"):
        bucket = arm.rsplit("_", 1)[1]
        return ["caesar20", f"deterministic_security_id_mod5_exclusion_bucket_{bucket}", "20pct_security_jackknife"]
    return {
        "LIQ_ADV40M": ["caesar20", "adv20_floor_40m"],
        "LIQ_ADV80M": ["caesar20", "adv20_floor_80m"],
        "LIQ_DAYDV10M": ["caesar20", "same_day_dollar_volume_floor_10m"],
    }[arm]
