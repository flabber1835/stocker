#!/usr/bin/env python3
"""Certified Research Champion V1 with observer-only Wealth Core audit outputs."""
from __future__ import annotations

import importlib.util
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
_CANONICAL_DIVIDEND_MARKER = "            # Canonical dividends already use the as-traded share basis."
_OBSERVER_DIVIDEND_MARKER = "            # Dividends use prior-close raw share quantity and current raw/signal price factor."


def transformed_source(mode, output):
    text = _PRIOR(mode, output)
    if text.count(_CANONICAL_DIVIDEND_MARKER) != 1:
        raise RuntimeError(
            "observed V1: expected exactly one canonical dividend observer seam, "
            f"found {text.count(_CANONICAL_DIVIDEND_MARKER)}"
        )
    # Comment-only alias for the observer's insertion anchor. The canonical
    # dividend implementation immediately below this line is left byte-for-byte
    # unchanged.
    text = text.replace(_CANONICAL_DIVIDEND_MARKER, _OBSERVER_DIVIDEND_MARKER, 1)
    return observer.install(text, variant="V1")


def _self_test_observer() -> int:
    generated = transformed_source("fullpit", Path("/tmp/wc-v1-observer-selftest"))
    compile(generated, "<wealth-core-v1-observed-fullpit>", "exec")
    for needle in (
        "wealth_core_order_blotter.csv",
        "wealth_core_position_lifecycle.csv",
        "wealth_core_daily_observer.csv",
    ):
        if needle not in generated:
            raise RuntimeError(f"observed V1 final source missing {needle}")
    print("[OBSERVER_FINAL_SOURCE] PASS V1", flush=True)
    return 0


if __name__ == "__main__":
    if "--self-test-observer" in sys.argv[1:]:
        raise SystemExit(_self_test_observer())
    raise SystemExit(certified.main())
