#!/usr/bin/env python3
"""Certified Research Champion V1 with observer-only Wealth Core audit outputs."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys

from backtester import run_research_champion_strict_pit_20y_v2 as certified

_OBSERVER_PATH = Path("research/wealth-core-v2-pit-ab-v1/pit_audit_observer_v2.py")
_spec = importlib.util.spec_from_file_location("wealth_core_pit_audit_observer_v2", _OBSERVER_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"cannot load observer {_OBSERVER_PATH}")
observer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(observer)

BASE = certified.champion
_PRIOR = BASE.strict20.corrected.transformed_source


def transformed_source(mode, output):
    return observer.install(_PRIOR(mode, output), variant="V1")


BASE.strict20.corrected.transformed_source = transformed_source


def _assert_generated(generated: str, label: str) -> None:
    compile(generated, f"<wealth-core-v1-observed-{label}>", "exec")
    required = (
        "wealth_core_order_blotter.csv",
        "wealth_core_position_lifecycle.csv",
        "wealth_core_daily_observer.csv",
    )
    missing = [needle for needle in required if needle not in generated]
    if missing:
        raise RuntimeError(f"observed V1 {label} source missing: {missing}")


def _self_test_observer() -> int:
    prior = os.environ.pop("CANONICAL_PIT_DATASET", None)
    try:
        unbound = transformed_source("fullpit", Path("/tmp/wc-v1-observer-selftest-unbound"))
        _assert_generated(unbound, "unbound")

        # Source generation only needs a truthy binding to exercise the exact
        # canonical transform. The generated program is compiled, not executed,
        # so this sentinel path is never opened.
        os.environ["CANONICAL_PIT_DATASET"] = "/tmp/source-generation-only-canonical-pit"
        canonical = transformed_source("fullpit", Path("/tmp/wc-v1-observer-selftest-canonical"))
        _assert_generated(canonical, "canonical")
        if "Canonical dividends already use the as-traded share basis." not in canonical:
            raise RuntimeError("observed V1 canonical source did not exercise canonical dividend transform")
    finally:
        if prior is None:
            os.environ.pop("CANONICAL_PIT_DATASET", None)
        else:
            os.environ["CANONICAL_PIT_DATASET"] = prior
    print("[OBSERVER_FINAL_SOURCE] PASS V1 unbound+canonical", flush=True)
    return 0


if __name__ == "__main__":
    if "--self-test-observer" in sys.argv[1:]:
        raise SystemExit(_self_test_observer())
    raise SystemExit(certified.main())
