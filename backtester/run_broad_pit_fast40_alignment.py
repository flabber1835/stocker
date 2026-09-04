#!/usr/bin/env python3
"""Diagnostic-only broad-PIT replay with the frozen main FAST acceleration rule.

This is not calibration. It changes exactly one stale retained-source seam:
FAST damaged-breadth delta5 0.30 -> 0.40, matching the frozen Sentinel 1.1
rule on main. All other transformed replay semantics remain identical.
"""
from __future__ import annotations

import sys
from backtester import run_research_ldrc_corrected_warmup_cash as base

_original = base.transformed_source


def _aligned_source(mode, output):
    text = _original(mode, output)
    old = "'ddam5':.30"
    new = "'ddam5':.40"
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"FAST acceleration alignment expected one seam, found {count}")
    text = text.replace(old, new, 1)
    if old in text:
        raise RuntimeError("stale FAST 0.30 seam survived alignment")
    return text


base.transformed_source = _aligned_source

if __name__ == "__main__":
    raise SystemExit(base.main())
