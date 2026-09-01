#!/usr/bin/env python3
"""Bound v2 SEC web source selection to the earliest unresolved observation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backtester import historical_metadata_reconstruction_v2 as base

SCHEMA = "backtester.historical-metadata-reconstruction-v2.web-plan-bounds/1"


def bound_plan(plan_dir: Path) -> dict:
    plan_path = plan_dir / "web_plan.csv.gz"
    if not plan_path.exists():
        raise base.ReconstructionError(f"missing web plan: {plan_path}")
    rows = base.read_gzip_csv(plan_path)
    bounded = []
    for row in rows:
        if str(row.get("alias_symbol") or ""):
            raise base.ReconstructionError("bounded web plan refuses inferred aliases")
        first_need = str(row.get("first_need_session") or "")[:10]
        if not first_need:
            raise base.ReconstructionError(f"web plan row lacks first_need_session: {row.get('security_id')}")
        original_first = str(row.get("first_session") or "")[:10]
        original_last = str(row.get("last_session") or "")[:10]
        item = dict(row)
        item["episode_first_session"] = original_first
        item["episode_last_session"] = original_last
        # base.select_web_filings applies a three-year lookback from first_session.
        # Pinning both selection endpoints to the earliest unresolved observation
        # prevents downloading later filings that cannot repair that earlier gap.
        item["first_session"] = first_need
        item["last_session"] = first_need
        item["source_selection_rule"] = "three_year_lookback_ending_at_first_unresolved_observation"
        bounded.append(item)

    fields = [
        "security_id", "ticker", "alias_symbol", "cik", "need_identity", "need_type", "need_sic",
        "discovery_only_cik_hint", "first_session", "last_session", "first_need_session",
        "first_unknown_type_session", "first_missing_sector_session", "episode_first_session",
        "episode_last_session", "source_selection_rule",
    ]
    base.write_gzip_csv(plan_path, fields, bounded)
    coverage_path = plan_dir / "web_plan_coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage["bounds_schema"] = SCHEMA
    coverage["source_selection_rule"] = "three-year lookback ending at the first unresolved observation"
    coverage["plan_sha256"] = base.sha256_file(plan_path)
    coverage_path.write_text(json.dumps(coverage, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    base.write_checksums(plan_dir)
    return coverage


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-dir", type=Path, required=True)
    args = parser.parse_args()
    result = bound_plan(args.plan_dir)
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
