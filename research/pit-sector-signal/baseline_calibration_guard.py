#!/usr/bin/env python3
"""Research guard for issue #241 baseline interpretation.

This does not run in production or CI. It verifies that a claimed sector-only
experiment has a current-Sharadar-sector control matching the authoritative
Simplified Concordance LD-RC baseline before the PIT-sector result is compared
to that baseline.
"""
from __future__ import annotations

import csv
from pathlib import Path

AUTHORITATIVE_20Y_CAGR = 0.22630215620600636
TOLERANCE = 1e-10

HERE = Path(__file__).resolve().parent
SUMMARY = HERE / "results-summary.csv"

with SUMMARY.open(newline="") as fh:
    rows = list(csv.DictReader(fh))


def row(variant: str, threshold: float) -> dict[str, str]:
    for item in rows:
        if item["variant"] == variant and abs(float(item["damaged_delta5_threshold"]) - threshold) < 1e-12:
            return item
    raise SystemExit(f"missing {variant=} {threshold=}")


current = float(row("current_sharadar", 0.30)["20y_cagr"])
ff12 = float(row("sec_ff12", 0.30)["20y_cagr"])
sector_delta_pp = (ff12 - current) * 100.0
control_gap_pp = (current - AUTHORITATIVE_20Y_CAGR) * 100.0

print(f"authoritative_current_system_20y_cagr={AUTHORITATIVE_20Y_CAGR:.12%}")
print(f"issue241_current_sector_control_20y_cagr={current:.12%}")
print(f"issue241_sec_ff12_20y_cagr={ff12:.12%}")
print(f"sector_only_delta_pp={sector_delta_pp:.12f}")
print(f"pre_sector_control_gap_pp={control_gap_pp:.12f}")

if abs(current - AUTHORITATIVE_20Y_CAGR) > TOLERANCE:
    raise SystemExit(
        "CALIBRATION_FAIL: #241 current-sector control does not reproduce the "
        "authoritative 22.6302156206% current-system baseline. Do not attribute "
        "the difference between 22.63% and the FF12 result to sector."
    )

print("CALIBRATION_PASS")
