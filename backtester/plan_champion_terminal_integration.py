#!/usr/bin/env python3
"""Translate accepted terminal evidence against an exact canonical PIT tape."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path


OUTPUT_SCHEMA = "backtester.research-champion-terminal-integration-plan/1"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _observation_rows(dataset: Path, wanted: set[tuple[str, str]]):
    for path in sorted(dataset.glob("observations-*.csv.gz")):
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                key = (row["session"], row["ticker"])
                if key in wanted:
                    yield key, row, path.name


def plan(evidence_path: Path, dataset: Path, output: Path) -> dict:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if evidence.get("schema") != "backtester.research-champion-terminal-authority-package/1":
        raise ValueError("unexpected accepted terminal evidence schema")
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != "backtester.canonical-pit-dataset/2":
        raise ValueError("unexpected canonical PIT schema")

    wanted: set[tuple[str, str]] = set()
    for event in evidence["events"]:
        wanted.add((event["last_executable_session"], event["ticker"]))
        if event.get("successor_ticker"):
            wanted.add((event["effective_date"], event["successor_ticker"]))
    found = {key: (row, name) for key, row, name in _observation_rows(dataset, wanted)}

    records = []
    blockers = []
    for event in evidence["events"]:
        sid = str(event["security_id"])
        target_key = (event["last_executable_session"], event["ticker"])
        target = found.get(target_key)
        if target is None or str(target[0]["security_id"]) != sid:
            blockers.append({"security_id": sid, "ticker": event["ticker"], "reason": "TARGET_IDENTITY_MISMATCH"})
            continue
        if event["event_type"] == "election_merger":
            blockers.append({"security_id": sid, "ticker": event["ticker"], "reason": "NO_ELECTION_ALLOCATION_UNPROVEN"})
            continue

        record = {
            "security_id": sid,
            "ticker": event["ticker"],
            "effective_session": event["effective_date"],
            "known_by": event["terms_known_date"],
            "reference": f"Champion stage-2 accepted terminal authority for {event['ticker']}",
            "sources": [event["terms_source"], event["completion_source"]],
        }
        kind = event["event_type"]
        if kind == "cash_merger":
            record.update(kind="CASH_MERGER", cash_per_share=event["cash_per_share"])
        else:
            successor_key = (event["effective_date"], event["successor_ticker"])
            delivered = found.get(successor_key)
            if delivered is None:
                blockers.append({"security_id": sid, "ticker": event["ticker"], "reason": "DELIVERED_SECURITY_MISSING_ON_EFFECTIVE_SESSION"})
                continue
            row, member_name = delivered
            close = float(row["raw_close"])
            if close <= 0 or not row["issuer_id"]:
                blockers.append({"security_id": sid, "ticker": event["ticker"], "reason": "DELIVERED_PRICE_OR_ISSUER_MISSING"})
                continue
            record.update(
                kind="CONVERSION" if kind == "stock_merger" else "CASH_PLUS_STOCK",
                delivered_security_id=row["security_id"],
                delivered_ticker=event["successor_ticker"],
                exchange_ratio=event["share_conversion_ratio"],
                cash_in_lieu_price_per_delivered_share=close,
                price_witness={
                    "session": event["effective_date"],
                    "security_id": row["security_id"],
                    "ticker": event["successor_ticker"],
                    "closeunadj": close,
                    "source_sep_sha256": manifest["members"][member_name]["sha256"],
                },
            )
            if kind == "mixed_merger":
                record["cash_per_share"] = event["cash_per_share"]
        records.append(record)

    result = {
        "schema": OUTPUT_SCHEMA,
        "status": "PASS",
        "canonical_dataset_hash": manifest["dataset_hash"],
        "source_evidence_sha256": _sha(evidence_path),
        "accepted_input_events": len(evidence["events"]),
        "integration_ready": len(records),
        "blocked": len(blockers),
        "records": sorted(records, key=lambda row: (row["effective_session"], row["security_id"])),
        "blockers": sorted(blockers, key=lambda row: row["security_id"]),
    }
    output.mkdir(parents=True, exist_ok=True)
    plan_path = output / "terminal-integration-plan.json"
    plan_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report = output / "REPORT.md"
    report.write_text(
        "# Champion terminal integration plan\n\n"
        f"Integration ready: **{len(records)}**\n\nBlocked: **{len(blockers)}**\n\n"
        + "\n".join(f"- {row['ticker']}: {row['reason']}" for row in result["blockers"])
        + "\n",
        encoding="utf-8",
    )
    sums = output / "SHA256SUMS.txt"
    sums.write_text(f"{_sha(plan_path)}  {plan_path.name}\n{_sha(report)}  {report.name}\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(plan(args.evidence, args.dataset, args.output), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
