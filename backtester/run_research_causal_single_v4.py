#!/usr/bin/env python3
"""Run one replay with the final guarded causal runtime."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtester import research_causal_instrumentation as base_instrumentation
from backtester.research_causal_instrumentation_v4 import (
    audit_sources,
    instrument_source,
    static_leakage_audit,
)
from backtester import run_research_causal_single as base_runner

base_instrumentation.instrument_source = instrument_source
base_instrumentation.static_leakage_audit = static_leakage_audit
base_instrumentation.audit_sources = audit_sources

if __name__ == "__main__":
    raise SystemExit(base_runner.main())
