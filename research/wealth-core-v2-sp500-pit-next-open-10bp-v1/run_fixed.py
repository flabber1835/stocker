#!/usr/bin/env python3
"""Harness-only repair for the Wealth Core V2 S&P 500 next-open experiment.

The economic transform remains in run.py. This wrapper fixes instrumentation after
that transform: run.py correctly replaces the V2 reservation-bound open sizing
seam, so its later telemetry patch can no longer find the pre-replacement text.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET = HERE / "run.py"
_spec = importlib.util.spec_from_file_location("wc_v2_sp500_nextopen_base", TARGET)
if _spec is None or _spec.loader is None:
    raise RuntimeError("could not load experiment runner")
base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(base)

_strict_replace = base.replace_one
_original_build = base.build_source


def _replace_allow_obsolete_telemetry(text: str, old: str, new: str, label: str) -> str:
    if label == "execution telemetry" and text.count(old) == 0:
        return text
    return _strict_replace(text, old, new, label)


# run.py's economics are unchanged. Only permit its obsolete post-transform
# telemetry seam to be absent; the corrected telemetry is inserted below.
base.replace_one = _replace_allow_obsolete_telemetry


def build_source(output: Path):
    v1, v2, src = _original_build(output)

    # This anchor is part of the already-applied next-open economics. Insert
    # telemetry after the actual open-time q has been calculated and after the
    # frozen capacity guard has accepted q. No economic state is changed here.
    anchor = (
        "                    nextopen_cash_limited+=int(float(book.cash)+1e-8<float(s.reserved_cash)); "
        "nextopen_zero_qty+=int(q<1); nextopen_blocks+=int(q<1); slot_v2_gap_cancelled+=int(q<1)"
    )
    instrumented = anchor + (
        "\n                    if q>=1:\n"
        "                        _gross_nextopen=float(q)*float(px)*(1+COST)\n"
        "                        nextopen_rounding_underfill+=max(0.,float(_execution_budget)-_gross_nextopen)\n"
        "                        nextopen_executed_gross+=_gross_nextopen\n"
        "                        _delay=max(0,int(gday)-int(s.pending_signal_day)-1)\n"
        "                        nextopen_delayed+=int(_delay>0); nextopen_max_delay=max(nextopen_max_delay,_delay)"
    )
    src = _strict_replace(src, anchor, instrumented, "post-open execution telemetry")

    # Explicitly prove the capacity guard consumes the quantity calculated from
    # the actual opening price, never the intentionally unbound close quantity.
    required = (
        "_execution_budget=min(float(s.reserved_cash),float(book.cash)); q=math.floor(_execution_budget/(float(px)*(1+COST)))",
        "_research_capacity_guard(q,_capacity_volumes.get(int(tid),())",
        "nextopen_rounding_underfill+=max(0.,float(_execution_budget)-_gross_nextopen)",
    )
    missing = [x for x in required if x not in src]
    if missing:
        raise RuntimeError(f"fixed next-open source missing required seams: {missing}")
    forbidden = (
        "_research_capacity_guard(s.pending_shares,_capacity_volumes.get(int(tid),())",
        "afford=math.floor(s.reserved_cash/",
    )
    survived = [x for x in forbidden if x in src]
    if survived:
        raise RuntimeError(f"close-bound execution mechanics survived: {survived}")
    compile(src, "<wealth-core-v2-sp500-next-open-10bp-fixed>", "exec")
    return v1, v2, src


base.build_source = build_source

if __name__ == "__main__":
    raise SystemExit(base.main())
