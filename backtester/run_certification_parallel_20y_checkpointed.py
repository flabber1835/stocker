#!/usr/bin/env python3
"""Annual, restartable research/production strict-PIT causal certification."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

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


def _verify_prefix_consumption(output_root: Path, expected_hash: str) -> None:
    """Authenticate the exact canonical prefix consumed by both annual engines."""
    end_session = os.environ.get("CERTIFICATION_END_SESSION", "").strip()
    canonical_root = Path(os.environ["CANONICAL_PIT_DATASET"])
    canonical = pd.read_csv(
        canonical_root / "session-hashes.csv", dtype=str, keep_default_na=False
    )
    expected_prefix = canonical[canonical["session"].le(end_session)].copy()
    if expected_prefix.empty or str(expected_prefix.iloc[-1]["session"]) != end_session:
        raise RuntimeError(
            f"canonical session-hash prefix does not end at {end_session}"
        )
    expected_prefix.reset_index(drop=True, inplace=True)

    summaries: dict[str, dict] = {}
    prefixes: dict[str, pd.DataFrame] = {}
    for role in ("research", "production"):
        summaries[role] = json.loads(
            (output_root / role / "summary.json").read_text(encoding="utf-8")
        )
        observed_hash = summaries[role].get("canonical_pit_dataset_hash")
        if observed_hash != expected_hash:
            raise RuntimeError(
                f"{role} canonical dataset hash mismatch: "
                f"{observed_hash} != {expected_hash}"
            )
        path = output_root / role / "canonical_input_session_hashes.csv"
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
        prefix = frame[frame["session"].le(end_session)].copy()
        prefix.reset_index(drop=True, inplace=True)
        if not prefix.equals(expected_prefix):
            raise RuntimeError(
                f"{role} canonical per-session input hashes disagree with "
                f"the immutable package through {end_session}"
            )
        prefix.to_csv(path, index=False, lineterminator="\n")
        prefixes[role] = prefix

    if not prefixes["research"].equals(prefixes["production"]):
        raise RuntimeError("research/production canonical annual prefixes differ")
    audit = {
        "schema": "backtester.canonical-input-consumption/2",
        "dataset_hash": expected_hash,
        "prefix_end": end_session,
        "sessions_compared": int(len(expected_prefix)),
        "roles": {
            role: summaries[role]["canonical_pit_dataset_hash"]
            for role in summaries
        },
        "per_session_hashes_identical": True,
        "package_prefix_authenticated": True,
    }
    (output_root / "canonical_input_consumption_audit.json").write_text(
        json.dumps(audit, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
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
cert._verify_canonical_consumption = _verify_prefix_consumption
cert._strong_equivalence = _required_strong_equivalence

if __name__ == "__main__":
    raise SystemExit(cert.main())
