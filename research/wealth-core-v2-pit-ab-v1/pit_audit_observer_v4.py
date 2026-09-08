#!/usr/bin/env python3
"""Thin compatibility alias to the promotion-safe observer.

The base observer now selects its initializer explicitly from the requested
variant, so the former V2-prefix normalization is no longer needed. Keeping this
alias avoids churn in the observed replay wrappers while ensuring the final
source uses the direct variant-specific implementation.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_V3_PATH = Path("research/wealth-core-v2-pit-ab-v1/pit_audit_observer_v3.py")
_spec = importlib.util.spec_from_file_location("wealth_core_pit_audit_observer_v3_base", _V3_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"cannot load observer base {_V3_PATH}")
_v3 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_v3)


def install(text: str, *, variant: str) -> str:
    return _v3.install(text, variant=variant)
