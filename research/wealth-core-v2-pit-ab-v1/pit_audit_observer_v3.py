#!/usr/bin/env python3
"""Compatibility shell around the observer for Research Champion promotion.

The underlying observer was first written against the retained control assignment
(`control=ctl_d`). Research Champion deliberately promotes Candidate A
(`control=a_d`). This module normalizes only that textual anchor long enough to
install the observer, then restores the exact promoted assignment before the
generated program is compiled or executed. No economic expression changes in
the final source.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_BASE_PATH = Path("research/wealth-core-v2-pit-ab-v1/pit_audit_observer_v2.py")
_spec = importlib.util.spec_from_file_location("wealth_core_pit_audit_observer_v2_base", _BASE_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"cannot load observer base {_BASE_PATH}")
_base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_base)

_RETAINED = "            pending_native=native_target; pend['control']=ctl_d; pend['A']=a_d; pend['B']=b_d"
_PROMOTED = "            pending_native=native_target; pend['control']=a_d; pend['A']=a_d; pend['B']=b_d"
_CLOCK = "\n            audit_last_session=ds"


def install(text: str, *, variant: str) -> str:
    retained = text.count(_RETAINED)
    promoted = text.count(_PROMOTED)
    if (retained, promoted) not in {(1, 0), (0, 1)}:
        raise RuntimeError(
            "observer Champion assignment seam: expected exactly one retained or "
            f"promoted form, got retained={retained} promoted={promoted}"
        )

    was_promoted = promoted == 1
    if was_promoted:
        text = text.replace(_PROMOTED, _RETAINED, 1)

    out = _base.install(text, variant=variant)

    retained_with_clock = _RETAINED + _CLOCK
    if out.count(retained_with_clock) != 1:
        raise RuntimeError(
            "observer Champion assignment seam disappeared after instrumentation: "
            f"count={out.count(retained_with_clock)}"
        )

    if was_promoted:
        out = out.replace(retained_with_clock, _PROMOTED + _CLOCK, 1)
        if _RETAINED in out:
            raise RuntimeError("observer leaked retained control assignment into promoted Champion source")
        if out.count(_PROMOTED + _CLOCK) != 1:
            raise RuntimeError("observer failed to restore exact promoted Champion control assignment")
    return out
