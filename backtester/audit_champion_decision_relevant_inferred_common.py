#!/usr/bin/env python3
"""Build the decision-relevant inferred-common audit worklist from a Champion replay."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def _integer(row: dict[str, str], key: str) -> int:
    return int(row.get(key) or 0)


def _role(row: dict[str, str]) -> str:
    if _integer(row, "held_sessions") or _integer(row, "pending_sessions"):
        return "HELD_OR_PENDING"
    if _integer(row, "recent_leadership_sessions"):
        return "LEADERSHIP_SIGNAL"
    if _integer(row, "durable_ranked_sessions"):
        return "DURABLE_RANKED"
    if _integer(row, "eligible_sessions") or _integer(row, "momentum_pool_sessions"):
        return "RANKING_INPUT"
    if _integer(row, "base_candidate_sessions"):
        return "BASE_CANDIDATE_ONLY"
    return "NO_REPLAY_CONTACT"


def build(replay: Path, ledger: Path, output: Path) -> dict:
    with ledger.open(encoding="utf-8", newline="") as handle:
        base = {row["security_id"]: row for row in csv.DictReader(handle)}
    with (replay / "strategy-path-worklist.csv").open(encoding="utf-8", newline="") as handle:
        path = {row["security_id"]: row for row in csv.DictReader(handle)}

    rows = []
    for sid, evidence in base.items():
        if evidence.get("classification") != "common" or evidence.get("disposition") != "INFERRED_COMMON":
            continue
        observed = path.get(sid)
        if not observed:
            continue
        role = _role(observed)
        if role in {"BASE_CANDIDATE_ONLY", "NO_REPLAY_CONTACT"}:
            continue
        best_rank = observed.get("best_durable_rank", "")
        rows.append({
            "security_id": sid,
            "ticker": evidence.get("ticker", observed.get("ticker", "")),
            "audit_priority": role,
            "classification": evidence.get("classification", ""),
            "disposition": evidence.get("disposition", ""),
            "vendor_category": evidence.get("category", ""),
            "base_candidate_sessions": _integer(observed, "base_candidate_sessions"),
            "eligible_sessions": _integer(observed, "eligible_sessions"),
            "momentum_pool_sessions": _integer(observed, "momentum_pool_sessions"),
            "durable_ranked_sessions": _integer(observed, "durable_ranked_sessions"),
            "recent_leadership_sessions": _integer(observed, "recent_leadership_sessions"),
            "pending_sessions": _integer(observed, "pending_sessions"),
            "held_sessions": _integer(observed, "held_sessions"),
            "best_durable_rank": best_rank,
            "metadata_firstpricedate": evidence.get("metadata_firstpricedate", ""),
            "metadata_lastpricedate": evidence.get("metadata_lastpricedate", ""),
            "figi": evidence.get("figi", ""),
            "cusips": evidence.get("cusips", ""),
            "inference_reason": evidence.get("reason", ""),
            "audit_status": "AUTHORITATIVE_HISTORICAL_EVIDENCE_REQUIRED",
        })

    priority = {"HELD_OR_PENDING": 0, "LEADERSHIP_SIGNAL": 1, "DURABLE_RANKED": 2, "RANKING_INPUT": 3}
    rows.sort(key=lambda row: (priority[row["audit_priority"]], int(row["best_durable_rank"] or 999999), row["ticker"]))
    fields = list(rows[0]) if rows else [
        "security_id", "ticker", "audit_priority", "classification", "disposition", "vendor_category",
        "base_candidate_sessions", "eligible_sessions", "momentum_pool_sessions", "durable_ranked_sessions",
        "recent_leadership_sessions", "pending_sessions", "held_sessions", "best_durable_rank",
        "metadata_firstpricedate", "metadata_lastpricedate", "figi", "cusips", "inference_reason", "audit_status",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)

    counts = {name: sum(row["audit_priority"] == name for row in rows) for name in priority}
    result = {
        "schema": "backtester.champion-decision-relevant-inferred-common-audit/1",
        "source_replay": str(replay),
        "total_decision_relevant_inferred_common": len(rows),
        "counts": counts,
        "status": "WORKLIST_REQUIRES_AUTHORITATIVE_HISTORICAL_REVIEW",
    }
    output.with_suffix(".json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.replay, args.ledger, args.output), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
