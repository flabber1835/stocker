#!/usr/bin/env python3
"""Compatibility shell for V2's extended audit-counter initializer.

`pit_audit_observer_v2` knows both V1 and V2 initializer text, but the shorter V1
initializer is a literal prefix of the longer V2 initializer. A substring count
therefore reports two matches on V2 even though only one physical initializer
exists. Normalize only this text seam while installing the observer, then restore
the exact V2 initializer in the final generated source.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_V3_PATH = Path("research/wealth-core-v2-pit-ab-v1/pit_audit_observer_v3.py")
_spec = importlib.util.spec_from_file_location("wealth_core_pit_audit_observer_v3_base", _V3_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"cannot load observer base {_V3_PATH}")
_v3 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_v3)

_INIT_V1 = "    rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0"
_INIT_V2 = (
    "    rows=[]; overlap_checks={}; buys=sells=split_events=div_events=0; "
    "slot_v2_reserved=slot_v2_rejected=slot_v2_gap_clipped=slot_v2_gap_cancelled=0"
)


def install(text: str, *, variant: str) -> str:
    v2_count = text.count(_INIT_V2)
    if v2_count not in (0, 1):
        raise RuntimeError(f"observer V2 initializer duplicated: {v2_count}")

    was_v2 = v2_count == 1
    if was_v2:
        # Replace the single physical long initializer with the short form so
        # v2's substring-based selector sees one variant, not both.
        text = text.replace(_INIT_V2, _INIT_V1, 1)

    out = _v3.install(text, variant=variant)

    if was_v2:
        if out.count(_INIT_V1) != 1:
            raise RuntimeError(
                "observer V2 initializer normalization did not survive instrumentation: "
                f"short_count={out.count(_INIT_V1)}"
            )
        out = out.replace(_INIT_V1, _INIT_V2, 1)
        if out.count(_INIT_V2) != 1:
            raise RuntimeError("observer failed to restore exact V2 diagnostic initializer")
    return out
