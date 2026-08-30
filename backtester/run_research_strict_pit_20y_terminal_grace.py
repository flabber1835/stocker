#!/usr/bin/env python3
"""Strict-PIT research entrypoint with backtester-only terminal-grace repair."""
from __future__ import annotations

import backtester.run_research_strict_pit_20y as base
from backtester.research_terminal_grace_overlay import install

_original = base.corrected.transformed_source


def _transformed(mode, output):
    return install(_original(mode, output))


base.corrected.transformed_source = _transformed

if __name__ == "__main__":
    raise SystemExit(base.main())
