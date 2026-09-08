#!/usr/bin/env python3
"""Certified Research Champion V1 with observer-only Wealth Core audit outputs."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from backtester import run_research_champion_strict_pit_20y_v2 as certified

_OBSERVER_PATH = Path("research/wealth-core-v2-pit-ab-v1/pit_audit_observer.py")
_spec = importlib.util.spec_from_file_location("wealth_core_pit_audit_observer", _OBSERVER_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"cannot load observer {_OBSERVER_PATH}")
pit_audit_observer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pit_audit_observer)

BASE = certified.champion
_PRIOR = BASE.strict20.corrected.transformed_source


def transformed_source(mode, output):
    return pit_audit_observer.install(_PRIOR(mode, output), variant="V1")


BASE.strict20.corrected.transformed_source = transformed_source


if __name__ == "__main__":
    raise SystemExit(certified.main())
