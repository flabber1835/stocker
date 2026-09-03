#!/usr/bin/env python3
"""Deterministic facade for the authoritative PIT certification engine.

The underlying certificate schema and validation logic remain unchanged.  This
facade removes host-VM identity from the experiment hash, requires the current
canonical dataset schema, and extends the authenticated Production source
closure for the combined SEC-V2/20-year workflow.
"""
from __future__ import annotations

import platform
import sys

from backtester import certify_backtest_result as implementation


CANONICAL_SCHEMA = "backtester.canonical-pit-dataset/2"


def deterministic_runtime_identity_hash():
    payload = {
        "python": sys.version.split()[0],
        "implementation": platform.python_implementation(),
        "cache_tag": str(getattr(sys.implementation, "cache_tag", "")),
    }
    return implementation.json_hash(payload), payload


_original_verify_dataset = implementation.verify_dataset


def verify_dataset_v2(dataset_root, pointer):
    value = _original_verify_dataset(dataset_root, pointer)
    manifest = value.get("manifest") or {}
    if manifest.get("schema") != CANONICAL_SCHEMA:
        raise RuntimeError(
            "global PIT certification requires canonical dataset schema "
            f"{CANONICAL_SCHEMA}; observed {manifest.get('schema')!r}"
        )
    return value


def _extend_source_closure() -> None:
    common = (
        "backtester/certify_backtest_result_v2.py",
        "main-src/sentinel/requirements.lock",
    )
    production = (
        "backtester/canonical_pit_metadata_v2.py",
        "backtester/build_canonical_pit_with_metadata_v2.py",
        "backtester/production_run_summary.py",
    )
    for mode in ("production", "research"):
        current = list(implementation.OFFICIAL_SOURCE_FILES[mode])
        for item in common + (production if mode == "production" else ()):
            if item not in current:
                current.append(item)
        implementation.OFFICIAL_SOURCE_FILES[mode] = tuple(current)


implementation.runtime_identity_hash = deterministic_runtime_identity_hash
implementation.verify_dataset = verify_dataset_v2
_extend_source_closure()


def main() -> int:
    return implementation.main()


if __name__ == "__main__":
    raise SystemExit(main())
