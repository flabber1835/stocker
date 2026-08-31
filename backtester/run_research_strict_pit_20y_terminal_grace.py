#!/usr/bin/env python3
"""Strict-PIT research entrypoint with backtester-only equivalence repairs."""
from __future__ import annotations

import backtester.run_research_strict_pit_20y as base
from backtester.research_fixed_forward_signal_overlay import install as install_signal
from backtester.research_terminal_grace_overlay import install as install_terminal

_original = base.corrected.transformed_source


def _transformed(mode, output):
    text = install_terminal(_original(mode, output))
    return install_signal(text)


base.corrected.transformed_source = _transformed

if __name__ == "__main__":
    raise SystemExit(base.main())
