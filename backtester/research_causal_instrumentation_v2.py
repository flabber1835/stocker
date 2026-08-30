#!/usr/bin/env python3
"""Final certification instrumentation wrapper."""
from __future__ import annotations

from backtester.research_causal_instrumentation import (  # noqa: F401
    audit_sources,
    static_leakage_audit,
)
from backtester import research_causal_instrumentation as base


def instrument_source(text: str) -> str:
    text = base.instrument_source(text)
    old_import = "from backtester.research_causal_runtime import ("
    new_import = "from backtester.research_causal_runtime_v2 import ("
    if text.count(old_import) != 1:
        raise RuntimeError("final causal runtime import seam changed")
    text = text.replace(old_import, new_import, 1)
    old_empty = """    out=pd.DataFrame(rows)
    out.to_csv(OUT/'daily.csv',index=False)"""
    new_empty = """    out=pd.DataFrame(rows)
    if out.empty:
        out=pd.DataFrame(columns=['date','control_nav','A_nav','B_nav','spy_nav'])
    out.to_csv(OUT/'daily.csv',index=False)"""
    if text.count(old_empty) != 1:
        raise RuntimeError("empty prefix reporting seam changed")
    text = text.replace(old_empty, new_empty, 1)
    compile(text, "<generated-final-causal-retained-research>", "exec")
    return text
