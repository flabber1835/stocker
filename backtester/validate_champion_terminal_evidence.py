#!/usr/bin/env python3
"""Validate and seal a prioritized Champion terminal-authority batch."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import date
from pathlib import Path


SCHEMA = "backtester.research-champion-terminal-authority/1"
OUTPUT_SCHEMA = "backtester.research-champion-terminal-authority-package/1"
EVENT_TYPES = {"cash_merger", "stock_merger", "mixed_merger", "election_merger"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(evidence_path: Path, priority_path: Path, output: Path) -> dict:
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    if evidence.get("schema") != SCHEMA or evidence.get("status") != "ACCEPTED":
        raise ValueError("terminal evidence header is not accepted schema v1")

    with priority_path.open(encoding="utf-8", newline="") as handle:
        priority = {row["security_id"]: row for row in csv.DictReader(handle)}

    events = evidence.get("events")
    if not isinstance(events, list) or not events:
        raise ValueError("terminal evidence has no events")

    seen: set[str] = set()
    for event in events:
        sid = str(event["security_id"])
        if sid in seen:
            raise ValueError(f"duplicate security_id: {sid}")
        seen.add(sid)
        work = priority.get(sid)
        if work is None:
            raise ValueError(f"security_id is absent from terminal priority: {sid}")
        if work["ticker"] != event["ticker"] or work["priority"] != "1_HELD_POSITION":
            raise ValueError(f"priority identity mismatch: {sid}")
        if int(work["incomplete_terminal_sessions"]) < 1 or int(work["held_sessions"]) < 1:
            raise ValueError(f"case is not an incomplete held terminal: {sid}")
        if event.get("acceptance_status") != "ACCEPTED":
            raise ValueError(f"unaccepted event: {sid}")
        if event.get("event_type") not in EVENT_TYPES:
            raise ValueError(f"invalid event type: {sid}")

        effective = date.fromisoformat(event["effective_date"])
        last_trade = date.fromisoformat(event["last_executable_session"])
        terms_known = date.fromisoformat(event["terms_known_date"])
        completion_filed = date.fromisoformat(event["completion_filed_date"])
        if last_trade > effective or terms_known > effective or completion_filed > effective:
            raise ValueError(f"non-causal event chronology: {sid}")

        for key in ("terms_source", "completion_source"):
            if not str(event.get(key, "")).startswith("https://www.sec.gov/Archives/edgar/data/"):
                raise ValueError(f"non-SEC {key}: {sid}")

        cash = float(event["cash_per_share"])
        ratio = float(event["share_conversion_ratio"])
        successor = event.get("successor_ticker")
        kind = event["event_type"]
        if kind == "cash_merger" and not (cash > 0 and ratio == 0 and successor is None):
            raise ValueError(f"incomplete cash consideration: {sid}")
        if kind == "stock_merger" and not (cash == 0 and ratio > 0 and successor):
            raise ValueError(f"incomplete stock consideration: {sid}")
        if kind in {"mixed_merger", "election_merger"} and not (cash > 0 and ratio > 0 and successor):
            raise ValueError(f"incomplete mixed/elective consideration: {sid}")

    ordered = sorted(events, key=lambda row: (row["effective_date"], row["security_id"]))
    output.mkdir(parents=True, exist_ok=True)
    accepted_path = output / "accepted-terminal-events.json"
    accepted = {
        "schema": OUTPUT_SCHEMA,
        "status": "PASS",
        "source_champion_run_id": evidence["source_champion_run_id"],
        "source_priority_run_id": evidence["source_priority_run_id"],
        "accepted_events": len(ordered),
        "security_ids": [row["security_id"] for row in ordered],
        "events": ordered,
    }
    accepted_path.write_text(json.dumps(accepted, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary = {
        "schema": OUTPUT_SCHEMA,
        "status": "PASS",
        "accepted_events": len(ordered),
        "held_terminal_starting_worklist": len(priority),
        "cash_events": sum(row["event_type"] == "cash_merger" for row in ordered),
        "stock_events": sum(row["event_type"] == "stock_merger" for row in ordered),
        "mixed_or_election_events": sum(row["event_type"] in {"mixed_merger", "election_merger"} for row in ordered),
        "evidence_sha256": _sha256(evidence_path),
        "priority_sha256": _sha256(priority_path),
    }
    summary_path = output / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path = output / "REPORT.md"
    report_path.write_text(
        "# Champion terminal evidence stage 2\n\n"
        f"Status: **PASS**\n\nAccepted held-position terminal events: **{len(ordered)}**\n\n"
        + "\n".join(f"- {row['ticker']}: {row['event_type']} effective {row['effective_date']}" for row in ordered)
        + "\n",
        encoding="utf-8",
    )
    sums_path = output / "SHA256SUMS.txt"
    sums_path.write_text(
        "".join(f"{_sha256(path)}  {path.name}\n" for path in (accepted_path, report_path, summary_path)),
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--priority", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(validate(args.evidence, args.priority, args.output), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
