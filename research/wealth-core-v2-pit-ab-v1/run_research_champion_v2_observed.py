#!/usr/bin/env python3
"""Wealth Core V2 Research Champion replay with observer-only audit outputs."""
from __future__ import annotations

import importlib.util
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
observer = _load("wealth_core_pit_audit_observer_v2", ROOT / "pit_audit_observer_v2.py")

_PRIOR = v2.BASE.strict20.corrected.transformed_source
_CANONICAL_DIVIDEND_MARKER = "            # Canonical dividends already use the as-traded share basis."
_OBSERVER_DIVIDEND_MARKER = "            # Dividends use prior-close raw share quantity and current raw/signal price factor."


def transformed_source(mode, output):
    text = _PRIOR(mode, output)
    if text.count(_CANONICAL_DIVIDEND_MARKER) != 1:
        raise RuntimeError(
            "observed V2: expected exactly one canonical dividend observer seam, "
            f"found {text.count(_CANONICAL_DIVIDEND_MARKER)}"
        )
    # Comment-only alias for the observer insertion anchor. No economic line is
    # altered: V2 slot funding has already been installed in _PRIOR.
    text = text.replace(_CANONICAL_DIVIDEND_MARKER, _OBSERVER_DIVIDEND_MARKER, 1)
    return observer.install(text, variant="V2")


v2.BASE.strict20.corrected.transformed_source = transformed_source


def _self_test_observer() -> int:
    generated = transformed_source("fullpit", Path("/tmp/wc-v2-observer-selftest"))
    compile(generated, "<wealth-core-v2-observed-fullpit>", "exec")
    required = (
        "wealth_core_order_blotter.csv",
        "wealth_core_position_lifecycle.csv",
        "wealth_core_daily_observer.csv",
        "reserved_cash:float=0.",
        "required_cash>book.uncommitted_cash()",
        "afford=math.floor(s.reserved_cash/",
    )
    missing = [needle for needle in required if needle not in generated]
    if missing:
        raise RuntimeError(f"observed V2 final source missing: {missing}")
    print("[OBSERVER_FINAL_SOURCE] PASS V2", flush=True)
    return 0


if __name__ == "__main__":
    if "--self-test-observer" in sys.argv[1:]:
        raise SystemExit(_self_test_observer())
    raise SystemExit(v2.main())
