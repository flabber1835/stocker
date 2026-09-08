#!/usr/bin/env python3
"""Certified Research Champion V1 with observer-only Wealth Core audit outputs."""
from __future__ import annotations

from backtester import run_research_champion_strict_pit_20y_v2 as certified
from research.wealth_core_v2_pit_ab_v1 import pit_audit_observer

BASE = certified.champion
_PRIOR = BASE.strict20.corrected.transformed_source


def transformed_source(mode, output):
    return pit_audit_observer.install(_PRIOR(mode, output), variant="V1")


BASE.strict20.corrected.transformed_source = transformed_source


if __name__ == "__main__":
    raise SystemExit(certified.main())
