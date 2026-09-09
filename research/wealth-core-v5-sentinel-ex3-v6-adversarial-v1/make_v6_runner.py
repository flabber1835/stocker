#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

# Exact reviewed V5 adversarial runner inherited by this V6 experiment.
SOURCE_GIT_BLOB_SHA1 = "afe3eb7fa9c7f927937e532331ccd067598a5d57"
V6_SELECTED_SOURCE_SHA256 = "335e2ae06efd5e2ebfa11f0641029609d524f4e75e733a3dbd0a5efcf64ac42d"

REPLACEMENTS = (
    (
        'SCHEMA = "research.wealth-core-v5-sentinel-ex3-v5-adversarial/1"',
        'SCHEMA = "research.wealth-core-v5-sentinel-ex3-v6-adversarial/1"',
    ),
    (
        'SYSTEM = "Wealth Core V5 + Sentinel EX3 V5"',
        'SYSTEM = "Wealth Core V5 + Sentinel EX3 V6"',
    ),
    (
        'SELECTED = {"rec": 8, "r40_floor": -0.05, "fast_damaged": 0.88, "healthy_damaged": 0.63}',
        'SELECTED = {"rec": 8, "r40_floor": -0.04, "fast_damaged": 0.88, "healthy_damaged": 0.63}',
    ),
    (
        '("r40_m04", "recent_r40>-0.05)", "recent_r40>-0.04)"),',
        '("r40_m03", "recent_r40>-0.04)", "recent_r40>-0.03)"),',
    ),
    (
        '("r40_m06", "recent_r40>-0.05)", "recent_r40>-0.06)"),',
        '("r40_m05", "recent_r40>-0.04)", "recent_r40>-0.05)"),',
    ),
    (
        'if "recent_r40>-0.05)" not in selected:',
        'if "recent_r40>-0.04)" not in selected:',
    ),
    (
        'raise RuntimeError("Sentinel EX3 V5 r40=-5% seam missing")',
        'raise RuntimeError("Sentinel EX3 V6 r40=-4% seam missing")',
    ),
    (
        'raise RuntimeError(f"Sentinel EX3 V5 metric parity failed: {key}: {m[key]} vs {expected}")',
        'raise RuntimeError(f"Sentinel EX3 V6 metric parity failed: {key}: {m[key]} vs {expected}")',
    ),
    (
        '"exact_sentinel_ex3_v5_parity":True',
        '"exact_sentinel_ex3_v6_parity":True',
    ),
)


def git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, type=Path)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()

    raw = args.source.read_bytes()
    observed_blob = git_blob_sha1(raw)
    if observed_blob != SOURCE_GIT_BLOB_SHA1:
        raise RuntimeError(
            f"V5 adversarial runner authority changed: {observed_blob} != {SOURCE_GIT_BLOB_SHA1}"
        )

    text = raw.decode("utf-8")
    for old, new in REPLACEMENTS:
        count = text.count(old)
        if count != 1:
            raise RuntimeError(f"expected exactly one V6 transformation seam, saw {count}: {old!r}")
        text = text.replace(old, new, 1)

    # Guard against accidentally retaining the V5 selected recovery floor or identity.
    forbidden = (
        'SELECTED = {"rec": 8, "r40_floor": -0.05',
        'exact_sentinel_ex3_v5_parity',
        'Sentinel EX3 V5 r40=-5% seam missing',
    )
    for marker in forbidden:
        if marker in text:
            raise RuntimeError(f"V5 marker survived V6 generation: {marker}")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text)
    print(f"generated_runner_sha256={hashlib.sha256(text.encode()).hexdigest()}")
    print(f"required_selected_source_sha256={V6_SELECTED_SOURCE_SHA256}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
