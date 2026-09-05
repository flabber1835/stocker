#!/usr/bin/env python3
"""Formal Research Champion replay with the causal terminal leadership repair."""
from __future__ import annotations

from backtester import run_research_champion_strict_pit_20y as champion
from backtester.research_champion_terminal_leadership_overlay import install


# strict20._twenty_year_transform resolves this module global at generation time.
# Binding the corrected installer here leaves Champion parameters and promotion
# assertions untouched while closing the known-terminal T -> T+1 witness seam.
champion.strict20.install_terminal_grace = install


def main() -> int:
    return int(champion.main())


if __name__ == "__main__":
    raise SystemExit(main())
