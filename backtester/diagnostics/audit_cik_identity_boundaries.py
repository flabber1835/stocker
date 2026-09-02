#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

from backtester.strict_pit_metadata import audit_cik_identity_boundaries


EXPECTED_RAW_CIK_CHANGE_EVENTS = 9547


def main() -> int:
    root = Path(os.environ.get("BACKTESTER_LAB_ROOT", ".")).resolve()
    output = Path(
        os.environ.get(
            "BACKTESTER_CIK_IDENTITY_AUDIT_OUTPUT",
            "backtester-results/cik-identity-boundary-audit.json",
        )
    ).resolve()
    records_path = output.with_name("cik-identity-boundaries.csv.gz")
    output.parent.mkdir(parents=True, exist_ok=True)
    cik_path = (
        root
        / "research/sentinel-fastgate/pit-evidence/generated/sec_cik_change_events.csv.gz"
    )
    records, summary = audit_cik_identity_boundaries(
        sharadar_root=root / "sharadar",
        cik_path=cik_path,
        start_year=1997,
        end_year=2026,
    )
    raw_count = int(summary["raw_cik_change_evidence_events"])
    population_ok = raw_count == EXPECTED_RAW_CIK_CHANGE_EVENTS

    mls = [row for row in records if str(row["ticker"]).upper() == "MLS"]
    expected_next_sessions = {"2007-02-08", "2007-03-30"}
    confirmed = {
        str(row["next_price_session"])
        for row in mls
        if row["disposition"] == "CONTINUOUS_TAPE_CIK_REJECTED"
    }
    missing = sorted(expected_next_sessions - confirmed)

    frame = pd.DataFrame(records)
    frame.to_csv(
        records_path,
        index=False,
        compression={"method": "gzip", "compresslevel": 6, "mtime": 0},
    )
    payload = {
        "schema": "backtester.cik-identity-boundary-audit/1",
        "status": "PASS" if population_ok and not missing else "FAIL",
        "summary": summary,
        "mls_records": mls,
        "records_file": records_path.name,
    }
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True), flush=True)
    if not population_ok:
        raise RuntimeError(
            f"frozen CIK boundary population changed: {raw_count} != "
            f"{EXPECTED_RAW_CIK_CHANGE_EVENTS}"
        )
    if missing:
        raise RuntimeError(
            "MLS continuity witness was not reproduced for session(s): "
            + ", ".join(missing)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
