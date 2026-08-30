#!/usr/bin/env python3
"""Parallel certification using the backtester-only research terminal-grace repair."""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backtester.run_certification_parallel_20y as base

base.RESEARCH_WRAPPER = Path("backtester/run_research_strict_pit_20y_terminal_grace.py")

if __name__ == "__main__":
    raise SystemExit(base.main())
