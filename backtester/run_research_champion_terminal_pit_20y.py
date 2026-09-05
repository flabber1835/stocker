#!/usr/bin/env python3
"""Research Champion v1 with canonical terminal lifecycle accounting."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backtester import run_research_champion_strict_pit_20y as champion
from backtester.research_terminal_lifecycle import install

_original = champion._champion_strict20_transform


def _terminal_aware_source(mode, output):
    return install(_original(mode, output))


champion._champion_strict20_transform = _terminal_aware_source
champion.strict20.corrected.transformed_source = _terminal_aware_source

if __name__ == "__main__":
    raise SystemExit(champion.main())
