#!/usr/bin/env python3
"""Stage B3a offline identity closure for the IWB/IWM-derived R3000 proxy.

This pass has no network dependency. It consumes only the immutable B2 ledger and
pinned canonical PIT package. It repairs deterministic SEC N-Q schedule footnote
suffixes, promotes a row only when exact normalized issuer-name continuity and the
historical source price identify exactly one canonical security on the target
session, and fails closed on every duplicate resolved security assignment within a
fund snapshot.

The result is a HISTORICAL_STATE_PROXY reconstruction only.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path

from backtester.r3000_proxy_identity_closure import CAVEAT, STATUSES, read_csv, sha256_file, verify_sha256s, write_csv_gz
from backtester.r3000_proxy_identity_closure_v3 import (
    _load_sessions,
    _load_target_prices,
    _name_variants,
    _price_candidates,
    _set_open,
    _set_resolved,
    _source_row_id,
    _target_sessions,
)

SCHEMA = "stocker.r3000-proxy.identity-closure/3a"
B2_SCHEMA = "stocker.r3000-proxy.identity-closure/2"


def close_identity_v3a(b2_root: Path, canonical_root: Path, output: Path) -> dict:
    verify_sha256s(b2_root)
    b2_summary_path = b2_root / "identity_summary_v2.json"
    b2_ledger_path = b2_root / "identity_ledger_v2.csv.gz"
    b2_summary = json.loads(b2_summary_path.read_text(encoding="utf-8"))
    if b2_summary.get("schema") != B2_SCHEMA or b2_summary.get("status") != "PASS":
        raise RuntimeError("B2 artifact is not a passing schema-2 identity package")

    fields, rows = read_csv(b2_ledger_path)
    if len(rows) != int(b2_summary.get("source_rows", -1)):
        raise RuntimeError("B2 ledger row count changed")
    if len({_source_row_id(row) for row in rows}) != len(rows):
        raise RuntimeError("duplicate B2 source-row identity")

    manifest_path = canonical_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dataset_hash = str(manifest.get("dataset_hash") or "")
    if dataset_hash != b2_summary.get("canonical_dataset_hash"):
        raise RuntimeError("canonical dataset hash differs from B2 authority")

    dates = {row["holdings_effective_date"] for row in rows}
    target_by_date = _target_sessions(_load_sessions(canonical_root), dates)
    for row in rows:
        expected = target_by_date[row["holdings_effective_date"]]
        if row.get("identity_target_session") != expected:
            raise RuntimeError("B2 target-session drift")
    by_price, _ = _load_target_prices(canonical_root, target_by_date)

    # Price-certified BlackRock identities provide the exact issuer-name continuity
    # index. The SEC source itself must independently match the same historical price.
    name_index: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if row.get("source_type") != "blackrock_product_data_v2":
            continue
        if row.get("identity_status") != "RESOLVED":
            continue
        sid = row.get("normalized_security_id", "")
        if not sid:
            continue
        for variant in _name_variants(row.get("reported_issuer_name", "")):
            name_index[variant].add(sid)

    sec_footnote_resolved = 0
    sec_footnote_ambiguous = 0
    sec_no_price = 0
    sec_no_exact_name_price = 0
    for row in rows:
        if row.get("source_type") != "sec_n-q" or row.get("identity_status") == "RESOLVED":
            continue
        price, candidates = _price_candidates(row, by_price)
        if price is None or not candidates:
            sec_no_price += 1
            row["identity_method"] = "OFFLINE_SEC_NORMALIZED_NAME_PLUS_HISTORICAL_PRICE"
            row["identity_reason"] = "NO_CANONICAL_HISTORICAL_PRICE_CANDIDATE"
            continue

        source_variants = _name_variants(row.get("reported_issuer_name", ""))
        matched_sids: set[str] = set()
        for variant in source_variants:
            matched_sids.update(name_index.get(variant, set()))
        matched_sids &= set(candidates)

        detail = {
            "method": "OFFLINE_SEC_NORMALIZED_NAME_PLUS_HISTORICAL_PRICE",
            "source_name": row.get("reported_issuer_name", ""),
            "source_name_variants": sorted(source_variants),
            "historical_price_cents": format(price, "f"),
            "canonical_dataset_hash": dataset_hash,
        }
        if len(matched_sids) == 1:
            sid = next(iter(matched_sids))
            _set_resolved(
                row,
                candidates[sid],
                method="OFFLINE_SEC_NORMALIZED_NAME_PLUS_HISTORICAL_PRICE",
                reason="",
                detail=detail,
            )
            sec_footnote_resolved += 1
        elif len(matched_sids) > 1:
            detail["candidate_security_ids"] = sorted(matched_sids)
            _set_open(
                row,
                status="AMBIGUOUS",
                method="OFFLINE_SEC_NORMALIZED_NAME_PLUS_HISTORICAL_PRICE",
                reason="MULTIPLE_EXACT_NAME_AND_PRICE_MATCHES",
                candidate_count=len(matched_sids),
                detail=detail,
            )
            sec_footnote_ambiguous += 1
        else:
            row["identity_method"] = "OFFLINE_SEC_NORMALIZED_NAME_PLUS_HISTORICAL_PRICE"
            row["identity_reason"] = "NO_EXACT_NORMALIZED_NAME_AND_PRICE_MATCH"
            sec_no_exact_name_price += 1

    # No duplicated security identity is allowed to remain resolved within one fund
    # snapshot. Without independent issuer authority, every member of the duplicate
    # group is reopened as ambiguous.
    assignments: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        sid = row.get("normalized_security_id", "")
        if row.get("identity_status") == "RESOLVED" and sid:
            assignments[(row.get("fund", ""), row.get("holdings_effective_date", ""), sid)].append(index)
    duplicate_groups_before = {key: indexes for key, indexes in assignments.items() if len(indexes) > 1}
    duplicate_rows_demoted = 0
    for (fund, effective, sid), indexes in sorted(duplicate_groups_before.items()):
        source_rows = [_source_row_id(rows[index]) for index in indexes]
        for index in indexes:
            _set_open(
                rows[index],
                status="AMBIGUOUS",
                method="DUPLICATE_SECURITY_ID_FAIL_CLOSED",
                reason="SAME_FUND_SNAPSHOT_SECURITY_ID_COLLISION_REQUIRES_INDEPENDENT_ISSUER_AUTHORITY",
                candidate_count=len(indexes),
                detail={
                    "method": "DUPLICATE_SECURITY_ID_FAIL_CLOSED",
                    "fund": fund,
                    "holdings_effective_date": effective,
                    "security_id": sid,
                    "same_snapshot_source_rows": source_rows,
                },
            )
            duplicate_rows_demoted += 1

    counts = Counter(row.get("identity_status", "") for row in rows)
    unknown = sorted(set(counts) - set(STATUSES))
    if unknown:
        raise RuntimeError(f"unknown identity statuses: {unknown}")

    final_assignments: Counter[tuple[str, str, str]] = Counter()
    snapshot_counts: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for row in rows:
        snap = (row.get("fund", ""), row.get("holdings_effective_date", ""))
        snapshot_counts[snap][row["identity_status"]] += 1
        sid = row.get("normalized_security_id", "")
        if row["identity_status"] == "RESOLVED" and sid:
            final_assignments[(snap[0], snap[1], sid)] += 1
    duplicate_groups_after = sum(1 for value in final_assignments.values() if value > 1)
    future_violations = sum(
        1 for row in rows if row["identity_target_session"] > row["holdings_effective_date"]
    )

    output.mkdir(parents=True, exist_ok=True)
    ledger_path = output / "identity_ledger_v3a.csv.gz"
    worklist_path = output / "identity_unresolved_worklist_v3a.csv.gz"
    write_csv_gz(ledger_path, fields, rows)
    write_csv_gz(
        worklist_path,
        fields,
        [row for row in rows if row.get("identity_status") != "RESOLVED"],
    )

    snapshot_rows = []
    for (fund, effective), snap_counts in sorted(snapshot_counts.items()):
        snapshot_rows.append(
            {
                "fund": fund,
                "holdings_effective_date": effective,
                "identity_target_session": target_by_date[effective],
                "rows": str(sum(snap_counts.values())),
                **{status.lower(): str(snap_counts.get(status, 0)) for status in STATUSES},
            }
        )
    write_csv_gz(
        output / "identity_snapshot_summary_v3a.csv.gz",
        [
            "fund",
            "holdings_effective_date",
            "identity_target_session",
            "rows",
            "resolved",
            "ambiguous",
            "unmatched",
            "conflict",
        ],
        snapshot_rows,
    )

    summary = {
        "schema": SCHEMA,
        "stage": "IDENTITY_CLOSURE_OFFLINE_SEC_NAME_PASS_3A",
        "status": (
            "PASS"
            if sum(counts.values()) == len(rows)
            and future_violations == 0
            and duplicate_groups_after == 0
            else "FAIL"
        ),
        "corpus_id": "r3000-proxy-pit-2006-2026-v1",
        "mode": "HISTORICAL_STATE_PROXY",
        "source_rows": len(rows),
        "fund_snapshots": len(snapshot_counts),
        "resolution_counts": {status: counts.get(status, 0) for status in STATUSES},
        "resolved_fraction": counts.get("RESOLVED", 0) / len(rows),
        "b2_resolution_counts": b2_summary.get("resolution_counts"),
        "methods_added": {
            "sec_normalized_name_plus_historical_price": sec_footnote_resolved,
            "sec_name_price_ambiguous": sec_footnote_ambiguous,
            "duplicate_rows_demoted": duplicate_rows_demoted,
        },
        "authority_gaps": {
            "sec_rows_without_historical_price_candidate": sec_no_price,
            "sec_rows_without_exact_normalized_name_and_price_match": sec_no_exact_name_price,
            "external_sec_cik_current_former_name_authority": "NOT_USED_IN_OFFLINE_PASS",
        },
        "duplicate_security_assignments_before": len(duplicate_groups_before),
        "duplicate_security_assignments_after": duplicate_groups_after,
        "future_session_violations": future_violations,
        "b2_ledger_sha256": sha256_file(b2_ledger_path),
        "b2_summary_sha256": sha256_file(b2_summary_path),
        "canonical_dataset_hash": dataset_hash,
        "canonical_manifest_sha256": sha256_file(manifest_path),
        "identity_ledger_sha256": sha256_file(ledger_path),
        "unresolved_worklist_sha256": sha256_file(worklist_path),
        "historical_state_semantics": (
            "Every new B3a identity requires exact deterministic source-name normalization, "
            "continuity to a B2 price-certified BlackRock identity, and an independent exact "
            "historical source-price match on the canonical target session."
        ),
        "information_available_semantics": "NOT_CERTIFIED_BY_THIS_STAGE",
        "acceptance_state": (
            "IDENTITY_CLOSED"
            if counts.get("RESOLVED", 0) == len(rows)
            else "OPEN_IDENTITY_WORKLIST"
        ),
        "caveat": CAVEAT,
    }
    summary_path = output / "identity_summary_v3a.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    members = [path for path in output.iterdir() if path.is_file() and path.name != "SHA256SUMS.txt"]
    (output / "SHA256SUMS.txt").write_text(
        "".join(f"{sha256_file(path)}  {path.name}\n" for path in sorted(members)),
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--b2", type=Path, required=True)
    parser.add_argument("--canonical", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(close_identity_v3a(args.b2, args.canonical, args.output), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
