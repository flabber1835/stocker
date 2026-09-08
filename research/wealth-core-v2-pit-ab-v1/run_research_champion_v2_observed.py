#!/usr/bin/env python3
"""Wealth Core V2 Research Champion replay with observer-only audit outputs."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys

ROOT = Path("research/wealth-core-v2-pit-ab-v1")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


v2 = _load("wealth_core_v2_replay", ROOT / "run_research_champion_slot_funding_v2.py")
observer = _load("wealth_core_pit_audit_observer_v4", ROOT / "pit_audit_observer_v4.py")

_PRIOR = v2.BASE.strict20.corrected.transformed_source


def transformed_source(mode, output):
    return observer.install(_PRIOR(mode, output), variant="V2")


v2.BASE.strict20.corrected.transformed_source = transformed_source


def _assert_generated(generated: str, label: str) -> None:
    compile(generated, f"<wealth-core-v2-observed-{label}>", "exec")
    required = (
        "wealth_core_order_blotter.csv",
        "wealth_core_position_lifecycle.csv",
        "wealth_core_daily_observer.csv",
        "reserved_cash:float=0.",
        "required_cash>book.uncommitted_cash()",
        "afford=math.floor(s.reserved_cash/",
        "slot_v2_reserved=slot_v2_rejected=slot_v2_gap_clipped=slot_v2_gap_cancelled=0",
        "pending_native=native_target; pend['control']=a_d; pend['A']=a_d; pend['B']=b_d",
    )
    missing = [needle for needle in required if needle not in generated]
    if missing:
        raise RuntimeError(f"observed V2 {label} source missing: {missing}")
    if "pending_native=native_target; pend['control']=ctl_d; pend['A']=a_d; pend['B']=b_d" in generated:
        raise RuntimeError("observed V2 final source reverted Champion control promotion")


def _self_test_observer() -> int:
    prior = os.environ.pop("CANONICAL_PIT_DATASET", None)
    try:
        unbound = transformed_source("fullpit", Path("/tmp/wc-v2-observer-selftest-unbound"))
        _assert_generated(unbound, "unbound")

        os.environ["CANONICAL_PIT_DATASET"] = "/tmp/source-generation-only-canonical-pit"
        canonical = transformed_source("fullpit", Path("/tmp/wc-v2-observer-selftest-canonical"))
        _assert_generated(canonical, "canonical")
        if "Canonical dividends already use the as-traded share basis." not in canonical:
            raise RuntimeError("observed V2 canonical source did not exercise canonical dividend transform")
    finally:
        if prior is None:
            os.environ.pop("CANONICAL_PIT_DATASET", None)
        else:
            os.environ["CANONICAL_PIT_DATASET"] = prior
    print("[OBSERVER_FINAL_SOURCE] PASS V2 unbound+canonical+promotion+init", flush=True)
    return 0


if __name__ == "__main__":
    if "--self-test-observer" in sys.argv[1:]:
        raise SystemExit(_self_test_observer())
    raise SystemExit(v2.main())
