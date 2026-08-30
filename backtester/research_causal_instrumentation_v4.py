#!/usr/bin/env python3
"""Final generated-source instrumentation used by certification."""
from __future__ import annotations

from backtester.research_causal_instrumentation_v3 import (  # noqa: F401
    audit_sources,
    static_leakage_audit,
)
from backtester import research_causal_instrumentation_v3 as base


def instrument_source(text: str) -> str:
    text = base.instrument_source(text)
    old_runtime = "from backtester.research_causal_runtime_v2 import ("
    new_runtime = "from backtester.research_causal_runtime_v4 import ("
    if text.count(old_runtime) != 1:
        raise RuntimeError("final causal runtime-v2 seam changed")
    text = text.replace(old_runtime, new_runtime, 1)
    old_import_end = """    guarded_session_map as causal_guarded_session_map,
    write_runtime_manifest as causal_write_runtime_manifest,
)"""
    new_import_end = """    guarded_session_map as causal_guarded_session_map,
    guarded_split_dates as causal_guarded_split_dates,
    write_runtime_manifest as causal_write_runtime_manifest,
)"""
    if text.count(old_import_end) != 1:
        raise RuntimeError("split-cache guard import seam changed")
    text = text.replace(old_import_end, new_import_end, 1)
    old_return = "return causal_guarded_session_map(bydate,'corporate actions'),split_dates"
    new_return = "return causal_guarded_session_map(bydate,'corporate actions'),causal_guarded_split_dates(split_dates)"
    if text.count(old_return) != 1:
        raise RuntimeError("split-cache return seam changed")
    text = text.replace(old_return, new_return, 1)
    compile(text, "<generated-final-causal-retained-research-v4>", "exec")
    return text
