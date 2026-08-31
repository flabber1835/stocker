#!/usr/bin/env python3
"""Annual, restartable research/production strict-PIT causal certification."""
from __future__ import annotations

import os
from pathlib import Path

import backtester.run_certification_parallel_20y as cert

FULL_DATASET_END = os.environ.get("CANONICAL_PIT_EXPECTED_END", "2026-07-31")
_real_dataset = cert.CanonicalPITDataset
_real_strong_equivalence = cert._strong_equivalence


def _full_package_dataset(path, *, expected_start=None, expected_end=None, **kwargs):
    return _real_dataset(
        path,
        expected_start=expected_start,
        expected_end=FULL_DATASET_END,
        **kwargs,
    )


def _required_strong_equivalence(
    output_root: Path,
    tolerance: float = 1e-10,
    *,
    require_match: bool = True,
) -> int:
    return _real_strong_equivalence(
        output_root,
        tolerance,
        require_match=True,
    )


cert.CanonicalPITDataset = _full_package_dataset
cert.PRODUCTION_WRAPPER = Path(
    "backtester/run_production_strict_pit_20y_checkpointed.py"
)
cert.RESEARCH_WRAPPER = Path(
    "backtester/run_research_strict_pit_20y_checkpointed.py"
)
cert._strong_equivalence = _required_strong_equivalence

if __name__ == "__main__":
    raise SystemExit(cert.main())
