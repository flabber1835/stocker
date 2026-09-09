#!/usr/bin/env python3
"""Isolated Wealth Core V5 execution transform.

V5 inherits the frozen Median-5 + 10 bp + next-open whole-share execution
contract and changes exactly one economic predicate: one-share feasibility at
close is tested against total cash. The 10 bp admission cushion remains a
separate positive-cash gate and is released at the next open.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

CONTRACT_VERSION = "wealth-core.v5-total-cash-affordability/1"
CLOSE_ADMISSION_RULE = "REQUIRE_POSITIVE_CASH_ABOVE_10BP_RESERVE_AND_ONE_WHOLE_SHARE_AFFORDABLE_FROM_TOTAL_CASH"
Q0_REASON = "TOTAL_CASH_ONE_SHARE_UNAFFORDABLE_AT_CLOSE"


def _load_v4_harness():
    path = Path(__file__).resolve().parents[1] / "median5-open-sizing-10bp-ex3-v1" / "canonical_execution_harness.py"
    spec = importlib.util.spec_from_file_location("wealth_core_v4_canonical_execution_harness", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen V4 harness at {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_V4 = _load_v4_harness()
V4_CONTRACT_VERSION = _V4.CONTRACT_VERSION


def _replace_once(src: str, old: str, new: str, label: str) -> str:
    count = src.count(old)
    if count != 1:
        raise RuntimeError(f"V5 {label} seam mismatch: expected 1, observed {count}")
    return src.replace(old, new, 1)


def apply_v5_open_time_whole_share_10bp(src: str) -> str:
    """Apply frozen V4 mechanics, then the isolated V5 affordability correction."""
    out = _V4.apply_open_time_whole_share_10bp(src)

    # The only economic predicate change in V5.
    out = _replace_once(
        out,
        "if _buffer_available_close+1e-12<_one_share_close_cost:",
        "if float(book.cash)+1e-12<_one_share_close_cost:",
        "total-cash affordability predicate",
    )

    # Evidence labels are updated so V4 and V5 artifacts cannot be confused.
    out = _replace_once(
        out,
        "'q0_reason':'WHOLE_SHARE_UNAFFORDABLE_AT_CLOSE'",
        f"'q0_reason':'{Q0_REASON}'",
        "q0 reason",
    )
    out = _replace_once(
        out,
        "'schema':'research.canonical-open-time-whole-shares-10bp/2'",
        "'schema':'research.wealth-core-v5-open-time-whole-shares-10bp/1'",
        "telemetry schema",
    )
    out = _replace_once(
        out,
        "'close_admission_rule':'REQUIRE_ONE_WHOLE_SHARE_AFFORDABLE_AT_CLOSE_ABOVE_10BP_RESERVE'",
        f"'close_admission_rule':'{CLOSE_ADMISSION_RULE}','close_admission_rule_cash_basis':'TOTAL_CASH'",
        "telemetry rule",
    )
    out = _replace_once(
        out,
        "'close_q0_whole_share_unaffordable':int(open_close_whole_share_unaffordable_skips)",
        "'close_q0_total_cash_one_share_unaffordable':int(open_close_whole_share_unaffordable_skips)",
        "telemetry affordability counter",
    )

    forbidden = (
        "if _buffer_available_close+1e-12<_one_share_close_cost:",
        "'q0_reason':'WHOLE_SHARE_UNAFFORDABLE_AT_CLOSE'",
        "REQUIRE_ONE_WHOLE_SHARE_AFFORDABLE_AT_CLOSE_ABOVE_10BP_RESERVE",
    )
    for marker in forbidden:
        if marker in out:
            raise RuntimeError(f"V4 affordability marker survived V5 transform: {marker}")

    required = (
        "if float(book.cash)+1e-12<_one_share_close_cost:",
        f"'q0_reason':'{Q0_REASON}'",
        f"'close_admission_rule':'{CLOSE_ADMISSION_RULE}'",
        "'close_admission_rule_cash_basis':'TOTAL_CASH'",
        "q=float(math.floor(_execution_budget/(float(px)*(1+COST))))",
        "_buffer_available_close=max(0.0,float(book.cash)-_buffer_required_close)",
    )
    for marker in required:
        if out.count(marker) != 1:
            raise RuntimeError(f"V5 required marker missing/duplicated: {marker}")

    compile(out, "<wealth-core-v5-total-cash-affordability>", "exec")
    return out


def assert_exact_v5_delta(v4: str, v5: str) -> None:
    """Prove V5 equals V4 plus the one economic predicate and evidence relabels."""
    expected = v4
    expected = _replace_once(
        expected,
        "if _buffer_available_close+1e-12<_one_share_close_cost:",
        "if float(book.cash)+1e-12<_one_share_close_cost:",
        "delta predicate",
    )
    expected = _replace_once(
        expected,
        "'q0_reason':'WHOLE_SHARE_UNAFFORDABLE_AT_CLOSE'",
        f"'q0_reason':'{Q0_REASON}'",
        "delta q0 reason",
    )
    expected = _replace_once(
        expected,
        "'schema':'research.canonical-open-time-whole-shares-10bp/2'",
        "'schema':'research.wealth-core-v5-open-time-whole-shares-10bp/1'",
        "delta telemetry schema",
    )
    expected = _replace_once(
        expected,
        "'close_admission_rule':'REQUIRE_ONE_WHOLE_SHARE_AFFORDABLE_AT_CLOSE_ABOVE_10BP_RESERVE'",
        f"'close_admission_rule':'{CLOSE_ADMISSION_RULE}','close_admission_rule_cash_basis':'TOTAL_CASH'",
        "delta telemetry rule",
    )
    expected = _replace_once(
        expected,
        "'close_q0_whole_share_unaffordable':int(open_close_whole_share_unaffordable_skips)",
        "'close_q0_total_cash_one_share_unaffordable':int(open_close_whole_share_unaffordable_skips)",
        "delta telemetry counter",
    )
    if v5 != expected:
        raise RuntimeError("V5 source contains changes outside the frozen affordability delta manifest")
