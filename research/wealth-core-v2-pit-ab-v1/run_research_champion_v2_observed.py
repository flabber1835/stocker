#!/usr/bin/env python3
"""Wealth Core V2 Research Champion replay with observer-only audit outputs."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path("research/wealth-core-v2-pit-ab-v1")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


v2 = _load("wealth_core_v2_replay", ROOT / "run_research_champion_slot_funding_v2.py")
observer = _load("wealth_core_pit_audit_observer", ROOT / "pit_audit_observer.py")

_PRIOR = v2.BASE.strict20.corrected.transformed_source


def transformed_source(mode, output):
    return observer.install(_PRIOR(mode, output), variant="V2")


v2.BASE.strict20.corrected.transformed_source = transformed_source


if __name__ == "__main__":
    raise SystemExit(v2.main())
