#!/usr/bin/env python3
"""Analyze unresolved historical-metadata episodes without changing admission semantics."""
from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path

SCHEMA = "backtester.historical-metadata-reconstruction-v2.unresolved-analysis/1"


def _iter_gzip_csv(path: Path):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        yield from csv.DictReader(fh)


def _read_gzip_csv(path: Path) -> list[dict[str, str]]:
    return list(_iter_gzip_csv(path))


def _write_gzip_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def analyze(package_root: Path, output: Path) -> dict:
    unresolved = _read_gzip_csv(package_root / "timeline" / "unresolved_episodes.csv.gz")
    unresolved_sids = {row["security_id"] for row in unresolved}
    unresolved_ciks = {
        cik
        for row in unresolved
        for cik in str(row.get("observed_ciks") or "").split(";")
        if cik
    }

    by_plan: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in _iter_gzip_csv(package_root / "web-plan" / "web_plan.csv.gz"):
        if row.get("security_id") in unresolved_sids:
            by_plan[str(row["security_id"])].append(row)

    by_web_identity = Counter()
    for row in _iter_gzip_csv(package_root / "web" / "web_identity_sources.csv.gz"):
        sid = str(row.get("security_id_hint") or "")
        if sid in unresolved_sids:
            by_web_identity[sid] += 1

    by_web_type = Counter()
    for row in _iter_gzip_csv(package_root / "web" / "web_security_type_sources.csv.gz"):
        sid = str(row.get("security_id_hint") or "")
        if sid in unresolved_sids:
            by_web_type[sid] += 1

    by_web_rejected_type: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in _iter_gzip_csv(package_root / "web" / "web_security_type_rejected.csv.gz"):
        sid = str(row.get("security_id_hint") or "")
        if sid in unresolved_sids:
            by_web_rejected_type[sid].append(row)

    by_web_sic = Counter()
    for row in _iter_gzip_csv(package_root / "web" / "web_sic_sources.csv.gz"):
        cik = str(row.get("cik") or "")
        if cik in unresolved_ciks:
            by_web_sic[cik] += 1

    by_timeline_identity = Counter()
    for row in _iter_gzip_csv(package_root / "timeline" / "identity_events.csv.gz"):
        sid = str(row.get("security_id") or "")
        if sid in unresolved_sids:
            by_timeline_identity[sid] += 1

    by_timeline_type = Counter()
    for row in _iter_gzip_csv(package_root / "timeline" / "security_type_events.csv.gz"):
        sid = str(row.get("security_id") or "")
        if sid in unresolved_sids:
            by_timeline_type[sid] += 1

    by_timeline_sic = Counter()
    for row in _iter_gzip_csv(package_root / "timeline" / "sic_events.csv.gz"):
        sid = str(row.get("security_id") or "")
        if sid in unresolved_sids:
            by_timeline_sic[sid] += 1

    detail: list[dict[str, str]] = []
    reason_presence = Counter()
    route_counts = Counter()
    rejection_counts = Counter()
    priority_counts = Counter()
    automation_counts = Counter()

    for row in unresolved:
        sid = row["security_id"]
        reasons = [value for value in str(row.get("reasons") or "").split(";") if value]
        for reason in reasons:
            reason_presence[reason] += 1
        ciks = [value for value in str(row.get("observed_ciks") or "").split(";") if value]
        plan_rows = by_plan[sid]
        rejected_rows = by_web_rejected_type[sid]
        for rejected in rejected_rows:
            rejection_counts[str(rejected.get("reason") or "")] += 1

        identity_missing = "no_unambiguous_historical_identity_proof" in reasons
        type_missing = "no_admitted_security_type_evidence" in reasons
        sic_missing = "no_admitted_sic_evidence" in reasons

        if identity_missing and not ciks:
            resolution_route = "IDENTITY_CIK_DISCOVERY"
        elif identity_missing:
            resolution_route = "IDENTITY_CONFIRMATION"
        elif type_missing and sic_missing:
            resolution_route = "TYPE_AND_SIC_FROM_KNOWN_IDENTITY"
        elif type_missing:
            resolution_route = "TYPE_FROM_KNOWN_IDENTITY"
        elif sic_missing:
            resolution_route = "SIC_FROM_KNOWN_IDENTITY"
        else:
            resolution_route = "REVIEW_OTHER"
        route_counts[resolution_route] += 1

        observations = int(row.get("observations") or 0)
        # Priority is workflow triage only. It never changes eligibility/admission.
        if observations >= 2500 or str(row.get("first_session") or "")[:4] == "2006":
            triage_priority = "P0"
        elif observations >= 500:
            triage_priority = "P1"
        else:
            triage_priority = "P2"
        priority_counts[triage_priority] += 1

        # These labels direct the next investigation; they are never positive admission evidence.
        if identity_missing and not ciks:
            automation_hint = "LOW_NEEDS_NEW_IDENTITY_AUTHORITY"
        elif type_missing and rejected_rows:
            automation_hint = "HIGH_REJECTED_TYPE_EVIDENCE_PRESENT"
        elif sic_missing and ciks and any(by_web_sic[cik] for cik in ciks):
            automation_hint = "HIGH_SIC_EVIDENCE_PRESENT_REVIEW_ALLOCATION"
        elif ciks and (type_missing or sic_missing):
            automation_hint = "MEDIUM_KNOWN_CIK_TARGETED_EVIDENCE"
        else:
            automation_hint = "MEDIUM_REVIEW_EXISTING_EVIDENCE"
        automation_counts[automation_hint] += 1

        detail.append(
            dict(row)
            | {
                "has_observed_cik": str(bool(ciks)).lower(),
                "web_plan_rows": str(len(plan_rows)),
                "web_plan_ciks": ";".join(
                    sorted({str(item.get("cik") or "") for item in plan_rows if item.get("cik")})
                ),
                "web_identity_sources": str(by_web_identity[sid]),
                "web_admitted_type_sources": str(by_web_type[sid]),
                "web_rejected_type_sources": str(len(rejected_rows)),
                "web_rejected_type_reasons": ";".join(
                    sorted({str(item.get("reason") or "") for item in rejected_rows if item.get("reason")})
                ),
                "web_sic_sources_for_observed_ciks": str(sum(by_web_sic[cik] for cik in ciks)),
                "timeline_identity_events": str(by_timeline_identity[sid]),
                "timeline_type_events": str(by_timeline_type[sid]),
                "timeline_sic_events": str(by_timeline_sic[sid]),
                "resolution_route": resolution_route,
                "automation_hint": automation_hint,
                "triage_priority": triage_priority,
                "strategy_entry_relevance": "UNKNOWN_REQUIRES_EXACT_UNIVERSE_REPLAY",
            }
        )

    priority_order = {"P0": 0, "P1": 1, "P2": 2}
    detail.sort(
        key=lambda item: (
            priority_order[item["triage_priority"]],
            -int(item.get("observations") or 0),
            item.get("ticker") or "",
            item["security_id"],
        )
    )

    output.mkdir(parents=True, exist_ok=True)
    _write_gzip_csv(
        output / "unresolved_episode_analysis.csv.gz",
        list(detail[0]) if detail else [],
        detail,
    )

    summary = {
        "schema": SCHEMA,
        "status": "PASS",
        "admission_status": "REVIEW_REQUIRED" if detail else "PASS",
        "unresolved_episode_records": len(detail),
        "unresolved_observations": sum(int(item.get("observations") or 0) for item in detail),
        "unknown_type_observations": sum(
            int(item.get("unknown_type_observations") or 0) for item in detail
        ),
        "missing_sector_observations": sum(
            int(item.get("missing_sector_observations") or 0) for item in detail
        ),
        "episodes_with_observed_cik": sum(item["has_observed_cik"] == "true" for item in detail),
        "episodes_without_observed_cik": sum(item["has_observed_cik"] == "false" for item in detail),
        "reason_presence": dict(reason_presence),
        "resolution_routes": dict(route_counts),
        "automation_hints": dict(automation_counts),
        "triage_priority": dict(priority_counts),
        "rejected_type_evidence_reasons": dict(rejection_counts),
        "policy": {
            "unknown_never_means_ineligible": True,
            "triage_priority_does_not_change_admission": True,
            "strategy_entry_relevance": (
                "must be established by exact historical-universe replay, not by this diagnostic"
            ),
        },
    }
    (output / "unresolved_analysis_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    lines = [
        "# Historical metadata unresolved-episode analysis",
        "",
        f"Unresolved episodes: **{len(detail):,}**",
        f"Episodes with observed CIK: **{summary['episodes_with_observed_cik']:,}**",
        f"Episodes without observed CIK: **{summary['episodes_without_observed_cik']:,}**",
        "",
        "## Resolution routes",
    ]
    for key, value in sorted(route_counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- {key}: {value:,}")
    lines.extend(["", "## Automation hints"])
    for key, value in sorted(automation_counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"- {key}: {value:,}")
    lines.extend(["", "## Top 25 by observation count"])
    for item in sorted(detail, key=lambda row: -int(row.get("observations") or 0))[:25]:
        lines.append(
            f"- {item.get('ticker')} ({item['security_id']}): "
            f"{int(item.get('observations') or 0):,} obs; "
            f"{item['resolution_route']}; {item['automation_hint']}"
        )
    (output / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.package_root, args.output)
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
