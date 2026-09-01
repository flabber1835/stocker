#!/usr/bin/env python3
"""Enforce V2 candidate identity policy after canonical candidate extraction."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backtester import historical_metadata_reconstruction_v2 as base

SCHEMA = "backtester.historical-metadata-reconstruction-v2.candidate-policy/1"


def sanitize(candidate_dir: Path) -> dict:
    path = candidate_dir / "candidate_episodes.csv.gz"
    if not path.is_file():
        raise base.ReconstructionError(f"missing candidate file: {path}")
    rows = base.read_gzip_csv(path)
    fields = [
        "security_id", "ticker", "first_session", "last_session", "observations",
        "unknown_type_observations", "missing_sector_observations", "observed_ciks",
        "alias_symbol", "alias_safe",
    ]
    output = []
    invalid_ciks = 0
    sid_in_cik = 0
    vendor_suffix_rows = 0
    for row in rows:
        sid = str(row.get("security_id") or "").strip()
        ticker = base.norm_ticker(row.get("ticker"))
        if not sid or not ticker:
            raise base.ReconstructionError("candidate row lacks security_id/ticker")
        raw_ciks = [value for value in str(row.get("observed_ciks") or "").split(";") if value]
        valid = []
        for value in raw_ciks:
            cik = base.validate_cik(value)
            if not cik:
                invalid_ciks += 1
                continue
            if cik == sid or value == sid:
                sid_in_cik += 1
                continue
            valid.append(cik)
        if base.alias_candidate(ticker):
            vendor_suffix_rows += 1
        item = dict(row)
        item["ticker"] = ticker
        item["observed_ciks"] = ";".join(sorted(set(valid)))
        # Numeric vendor suffix removal is not historical identity evidence.
        item["alias_symbol"] = ""
        item["alias_safe"] = "false"
        output.append(item)

    if sid_in_cik:
        raise base.ReconstructionError(f"security ids leaked into CIK fields: {sid_in_cik}")
    base.write_gzip_csv(path, fields, output)
    coverage_path = candidate_dir / "candidate_coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage.update({
        "candidate_policy_schema": SCHEMA,
        "vendor_suffix_alias_policy": "disabled_without_independent_historical_alias_proof",
        "vendor_suffix_candidate_rows": vendor_suffix_rows,
        "candidate_aliases_admitted": 0,
        "invalid_cik_values_removed": invalid_ciks,
        "security_id_in_cik_fields": 0,
        "candidate_sha256": base.sha256_file(path),
    })
    coverage_path.write_text(json.dumps(coverage, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    base.write_checksums(candidate_dir)
    return coverage


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-dir", type=Path, required=True)
    args = parser.parse_args()
    result = sanitize(args.candidate_dir)
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
