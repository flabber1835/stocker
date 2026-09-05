#!/usr/bin/env python3
"""Stage B4: retained-V4 authority closure and PIT membership-ledger construction.

This stage consumes the immutable B3b R3000 proxy identity package, the retained
ownership-strict V4 candidate corpus, its authoritative canonical-audit output,
and the pinned canonical PIT price package. Membership dates remain exactly the
contemporaneous IWB/IWM holdings dates. V4 evidence is used only to identify the
permanent security represented by a historical holding.

Promotion rules are deliberately narrow:
* BlackRock: exact normalized reported ticker -> exactly one ownership-strict V4
  security episode whose [first_session,last_session] contains the target session,
  and that security must exist in the canonical target-session observation.
* SEC N-Q: after BlackRock promotion, exact deterministic issuer-name continuity
  to a resolved BlackRock permanent security plus exact target-session historical
  price; one candidate only.
* Any collision remains ambiguous. Every residual row receives a terminal reason
  classification. No fuzzy matching is performed.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path

from backtester.r3000_proxy_identity_closure import (
    CAVEAT,
    STATUSES,
    read_csv,
    sha256_file,
    ticker_key,
    verify_sha256s,
    write_csv_gz,
)
from backtester.r3000_proxy_identity_closure_v3 import _name_variants, _set_open, _set_resolved

SCHEMA = "stocker.r3000-proxy.identity-closure/4"
B3B_SCHEMA = "stocker.r3000-proxy.identity-closure/3b"
V4_CANDIDATE_SCHEMA = "backtester.historical-metadata-reconstruction-v4.ownership-strict-candidate-merge/1"
V4_AUDIT_SCHEMA = "backtester.historical-metadata-reconstruction-v4.issuer-safe-canonical-observation-audit/1"
IDENTITY_QUALITIES = {"SEC_EXPLICIT_TRADING_SYMBOL_LABEL", "SEC_OWNERSHIP_ISSUER_TRADING_SYMBOL_XML"}


def _source_row_id(row: dict[str, str]) -> str:
    return "|".join((row.get("fund", ""), row.get("holdings_effective_date", ""), row.get("source_sha256", ""), row.get("source_row_number", "")))


def _cents(value: str) -> Decimal | None:
    text = (value or "").replace(",", "").replace("$", "").strip()
    if not text or text == "-":
        return None
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None
    if not number.is_finite() or number <= 0:
        return None
    return number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _load_canonical_targets(canonical: Path, target_sessions: set[str]):
    by_year: dict[int, set[str]] = defaultdict(set)
    for session in target_sessions:
        by_year[int(session[:4])].add(session)
    by_sid: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    by_price: dict[str, dict[Decimal, dict[str, dict[str, str]]]] = defaultdict(lambda: defaultdict(dict))
    required = {"session", "security_id", "ticker", "issuer_id", "issuer_source", "security_type", "listing_active", "tradeable", "identity_source", "raw_close"}
    for year, sessions in sorted(by_year.items()):
        path = canonical / f"observations-{year}.csv.gz"
        if not path.is_file():
            raise RuntimeError(f"missing canonical partition {path.name}")
        maximum = max(sessions)
        found: set[str] = set()
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if not required.issubset(set(reader.fieldnames or [])):
                raise RuntimeError(f"canonical columns incomplete in {path.name}")
            for record in reader:
                session = record["session"]
                if session > maximum:
                    break
                if session not in sessions:
                    continue
                found.add(session)
                sid = record.get("security_id", "")
                if not sid:
                    continue
                by_sid[session][sid] = record
                price = _cents(record.get("raw_close", ""))
                if price is not None:
                    by_price[session][price][sid] = record
        if found != sessions:
            raise RuntimeError(f"canonical target sessions missing from {path.name}: {sorted(sessions - found)}")
    return by_sid, by_price


def _load_v4_index(v4_root: Path):
    summary = json.loads((v4_root / "summary.json").read_text(encoding="utf-8"))
    if summary.get("schema") != V4_CANDIDATE_SCHEMA or summary.get("status") != "PASS" or summary.get("candidate_only") is not True:
        raise RuntimeError("V4 ownership-strict candidate package is not authenticated PASS")
    episodes: dict[str, dict[str, dict[str, object]]] = defaultdict(dict)
    evidence_rows = 0
    with gzip.open(v4_root / "candidate_evidence.csv.gz", "rt", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("candidate_kind") != "IDENTITY_EXACT_TICKER" or row.get("candidate_quality") not in IDENTITY_QUALITIES:
                continue
            if row.get("admission_effect") != "NONE_CANDIDATE_ONLY":
                raise RuntimeError("V4 candidate unexpectedly has admission effect")
            key = ticker_key(row.get("ticker", ""))
            sid = row.get("security_id", "")
            if not key or not sid:
                continue
            slot = episodes[key].setdefault(sid, {"first": row.get("first_session", ""), "last": row.get("last_session", ""), "ciks": set(), "proofs": []})
            if slot["first"] != row.get("first_session", "") or slot["last"] != row.get("last_session", ""):
                raise RuntimeError(f"V4 episode bounds drift for {sid}")
            slot["ciks"].add(row.get("candidate_cik", ""))
            slot["proofs"].append({k: row.get(k, "") for k in ("candidate_quality", "form", "filed", "accession", "source_sha256", "source_url")})
            evidence_rows += 1
    return summary, episodes, evidence_rows


def _authenticate_audit(audit_root: Path) -> dict:
    verify_sha256s(audit_root)
    summary = json.loads((audit_root / "summary.json").read_text(encoding="utf-8"))
    if summary.get("schema") != V4_AUDIT_SCHEMA or summary.get("status") != "PASS" or summary.get("canonical_price_dataset_rewritten") is not False:
        raise RuntimeError("V4 canonical audit is not authenticated PASS")
    if summary.get("causal_rule") != "usable_after < decision_session":
        raise RuntimeError("V4 canonical audit causal rule drift")
    return summary


def _classify_residual(row: dict[str, str]) -> str:
    source = row.get("source_type", "")
    reason = row.get("identity_reason", "")
    if row.get("identity_status") == "AMBIGUOUS":
        return "AMBIGUOUS_MULTIPLE_DEFENSIBLE_IDENTITIES"
    if source == "blackrock_product_data_v2":
        if reason == "NO_HISTORICAL_UNIT_PRICE":
            return "BLACKROCK_MISSING_HISTORICAL_PRICE_AUTHORITY"
        if reason == "TIED_IDENTIFIER_PRICE_PATH":
            return "BLACKROCK_IDENTIFIER_PRICE_PATH_TIE"
        if "COLLISION" in reason:
            return "BLACKROCK_SNAPSHOT_SECURITY_COLLISION"
        return "BLACKROCK_NO_DEFENSIBLE_PERMANENT_IDENTITY_AUTHORITY"
    if source == "sec_n-q":
        if reason == "NO_CANONICAL_HISTORICAL_PRICE_CANDIDATE":
            return "SEC_NO_HISTORICAL_PRICE_AUTHORITY"
        if reason == "MULTIPLE_EXACT_NAME_AND_PRICE_MATCHES":
            return "SEC_MULTIPLE_EXACT_NAME_PRICE_IDENTITIES"
        return "SEC_NO_EXACT_NAME_PRICE_IDENTITY_AUTHORITY"
    return "UNCLASSIFIED_SOURCE_AUTHORITY_GAP"


def close_identity_v4(b3b_root: Path, v4_root: Path, audit_root: Path, canonical: Path, output: Path) -> dict:
    verify_sha256s(b3b_root)
    b3 = json.loads((b3b_root / "identity_summary_v3b.json").read_text(encoding="utf-8"))
    if b3.get("schema") != B3B_SCHEMA or b3.get("status") != "PASS" or int(b3.get("source_rows", -1)) != 63113:
        raise RuntimeError("B3b package identity mismatch")
    fields, rows = read_csv(b3b_root / "identity_ledger_v3b.csv.gz")
    if len(rows) != 63113 or len({_source_row_id(row) for row in rows}) != 63113:
        raise RuntimeError("B3b ledger accounting mismatch")
    candidate_summary, v4_index, v4_identity_evidence_rows = _load_v4_index(v4_root)
    audit_summary = _authenticate_audit(audit_root)

    manifest = json.loads((canonical / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("dataset_hash") != b3.get("canonical_dataset_hash"):
        raise RuntimeError("canonical dataset hash differs from B3b")
    targets = {row.get("identity_target_session", "") for row in rows}
    if "" in targets:
        raise RuntimeError("missing identity target session")
    by_sid, by_price = _load_canonical_targets(canonical, targets)

    blackrock_promoted = 0
    blackrock_multi = 0
    for row in rows:
        if row.get("source_type") != "blackrock_product_data_v2" or row.get("identity_status") == "RESOLVED":
            continue
        key = ticker_key(row.get("reported_ticker", ""))
        target = row["identity_target_session"]
        active: list[tuple[str, dict[str, object]]] = []
        for sid, evidence in v4_index.get(key, {}).items():
            if str(evidence["first"]) <= target <= str(evidence["last"]) and sid in by_sid.get(target, {}):
                active.append((sid, evidence))
        if len(active) == 1:
            sid, evidence = active[0]
            detail = {
                "method": "RETAINED_V4_EXACT_TICKER_EPISODE",
                "reported_ticker": row.get("reported_ticker", ""),
                "target_session": target,
                "permanent_security_id": sid,
                "candidate_ciks": sorted(evidence["ciks"]),
                "episode_first_session": evidence["first"],
                "episode_last_session": evidence["last"],
                "proofs": sorted(evidence["proofs"], key=lambda x: (x["filed"], x["accession"], x["source_sha256"])),
                "v4_candidate_artifact_sha256": sha256_file(v4_root / "candidate_evidence.csv.gz"),
            }
            _set_resolved(row, by_sid[target][sid], method="RETAINED_V4_EXACT_TICKER_EPISODE", reason="", detail=detail)
            blackrock_promoted += 1
        elif len(active) > 1:
            _set_open(row, status="AMBIGUOUS", method="RETAINED_V4_EXACT_TICKER_EPISODE", reason="MULTIPLE_V4_SECURITY_EPISODES_ACTIVE_FOR_EXACT_TICKER", candidate_count=len(active), detail={"candidate_security_ids": sorted(sid for sid, _ in active), "target_session": target})
            blackrock_multi += 1

    # New BlackRock promotions can provide deterministic legal-name continuity for
    # old SEC N-Q rows. Historical price agreement remains mandatory.
    names: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if row.get("source_type") != "blackrock_product_data_v2" or row.get("identity_status") != "RESOLVED":
            continue
        sid = row.get("normalized_security_id", "")
        if not sid:
            continue
        for variant in _name_variants(row.get("reported_issuer_name", "")):
            names[variant].add(sid)

    sec_promoted = 0
    sec_ambiguous = 0
    for row in rows:
        if row.get("source_type") != "sec_n-q" or row.get("identity_status") == "RESOLVED":
            continue
        target = row["identity_target_session"]
        price = _cents(row.get("reported_unit_price", ""))
        if price is None:
            continue
        price_candidates = by_price.get(target, {}).get(price, {})
        matched: set[str] = set()
        for variant in _name_variants(row.get("reported_issuer_name", "")):
            matched.update(names.get(variant, set()))
        matched &= set(price_candidates)
        if len(matched) == 1:
            sid = next(iter(matched))
            _set_resolved(row, price_candidates[sid], method="RETAINED_V4_BLACKROCK_NAME_PLUS_HISTORICAL_PRICE", reason="", detail={
                "method": "RETAINED_V4_BLACKROCK_NAME_PLUS_HISTORICAL_PRICE",
                "source_name": row.get("reported_issuer_name", ""),
                "source_name_variants": sorted(_name_variants(row.get("reported_issuer_name", ""))),
                "historical_price_cents": format(price, "f"),
                "target_session": target,
                "permanent_security_id": sid,
            })
            sec_promoted += 1
        elif len(matched) > 1:
            _set_open(row, status="AMBIGUOUS", method="RETAINED_V4_BLACKROCK_NAME_PLUS_HISTORICAL_PRICE", reason="MULTIPLE_EXACT_NAME_AND_PRICE_MATCHES", candidate_count=len(matched), detail={"candidate_security_ids": sorted(matched), "target_session": target})
            sec_ambiguous += 1

    # Fail closed on same-fund/snapshot permanent-security collisions after all promotions.
    assignments: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        if row.get("identity_status") == "RESOLVED" and row.get("normalized_security_id"):
            assignments[(row.get("fund", ""), row.get("holdings_effective_date", ""), row["normalized_security_id"])].append(i)
    collision_rows = 0
    for (fund, effective, sid), indexes in sorted(assignments.items()):
        if len(indexes) <= 1:
            continue
        source_ids = [_source_row_id(rows[i]) for i in indexes]
        for i in indexes:
            _set_open(rows[i], status="AMBIGUOUS", method="V4_DUPLICATE_SECURITY_ID_FAIL_CLOSED", reason="SAME_FUND_SNAPSHOT_SECURITY_ID_COLLISION_REQUIRES_INDEPENDENT_ISSUER_AUTHORITY", candidate_count=len(indexes), detail={"fund": fund, "holdings_effective_date": effective, "security_id": sid, "same_snapshot_source_rows": source_ids})
            collision_rows += 1

    for row in rows:
        row["permanent_security_id"] = row.get("normalized_security_id", "") if row.get("identity_status") == "RESOLVED" else ""
        row["residual_classification"] = "" if row.get("identity_status") == "RESOLVED" else _classify_residual(row)

    counts = Counter(row.get("identity_status", "") for row in rows)
    if set(counts) - set(STATUSES):
        raise RuntimeError(f"unknown statuses: {sorted(set(counts)-set(STATUSES))}")
    if sum(counts.values()) != 63113:
        raise RuntimeError("terminal accounting mismatch")
    duplicates = Counter((r.get("fund", ""), r.get("holdings_effective_date", ""), r.get("permanent_security_id", "")) for r in rows if r.get("identity_status") == "RESOLVED")
    duplicate_groups = sum(1 for n in duplicates.values() if n > 1)
    if duplicate_groups:
        raise RuntimeError(f"duplicate resolved assignments remain: {duplicate_groups}")

    out_fields = list(fields)
    for extra in ("permanent_security_id", "residual_classification"):
        if extra not in out_fields:
            out_fields.append(extra)
    output.mkdir(parents=True, exist_ok=True)
    write_csv_gz(output / "identity_ledger_v4.csv.gz", out_fields, rows)
    residual = [row for row in rows if row.get("identity_status") != "RESOLVED"]
    write_csv_gz(output / "identity_residual_classification_v4.csv.gz", out_fields, residual)

    member_fields = ["holdings_effective_date", "identity_target_session", "fund", "permanent_security_id", "identity_status", "reported_ticker", "normalized_ticker_on_snapshot_date", "reported_issuer_name", "source_type", "source_id", "source_sha256", "source_row_number", "residual_classification"]
    fund_counts = {}
    for fund in ("IWB", "IWM"):
        subset = [row for row in rows if row.get("fund") == fund]
        write_csv_gz(output / f"{fund.lower()}_pit_membership_v4.csv.gz", member_fields, subset)
        fund_counts[fund] = len(subset)

    # Conservative union: resolved rows dedupe on permanent security ID per date.
    # Unresolved rows remain distinct source claims so uncertainty is never erased.
    union: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        effective = row.get("holdings_effective_date", "")
        sid = row.get("permanent_security_id", "")
        source_key = _source_row_id(row)
        key = (effective, f"P:{sid}" if sid else f"U:{source_key}")
        if key not in union:
            union[key] = {
                "holdings_effective_date": effective,
                "identity_target_session": row.get("identity_target_session", ""),
                "membership_key": key[1],
                "permanent_security_id": sid,
                "identity_status": row.get("identity_status", ""),
                "normalized_ticker_on_snapshot_date": row.get("normalized_ticker_on_snapshot_date", ""),
                "reported_issuer_name": row.get("reported_issuer_name", ""),
                "in_iwb": "false",
                "in_iwm": "false",
                "source_claim_count": "0",
                "residual_classification": row.get("residual_classification", ""),
            }
        item = union[key]
        item["in_iwb" if row.get("fund") == "IWB" else "in_iwm"] = "true"
        item["source_claim_count"] = str(int(item["source_claim_count"]) + 1)
    union_rows = [union[key] for key in sorted(union)]
    union_fields = ["holdings_effective_date", "identity_target_session", "membership_key", "permanent_security_id", "identity_status", "normalized_ticker_on_snapshot_date", "reported_issuer_name", "in_iwb", "in_iwm", "source_claim_count", "residual_classification"]
    write_csv_gz(output / "r3000_proxy_union_pit_membership_v4.csv.gz", union_fields, union_rows)

    residual_classes = Counter(row["residual_classification"] for row in residual)
    snapshot_counts: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for row in rows:
        snapshot_counts[(row["fund"], row["holdings_effective_date"])][row["identity_status"]] += 1
    snapshot_rows = []
    for (fund, effective), c in sorted(snapshot_counts.items()):
        snapshot_rows.append({"fund": fund, "holdings_effective_date": effective, "rows": str(sum(c.values())), **{status.lower(): str(c.get(status, 0)) for status in STATUSES}})
    write_csv_gz(output / "snapshot_reconciliation_v4.csv.gz", ["fund", "holdings_effective_date", "rows", "resolved", "ambiguous", "unmatched", "conflict"], snapshot_rows)

    summary = {
        "schema": SCHEMA,
        "stage": "RETAINED_V4_AUTHORITY_CLOSURE_AND_MEMBERSHIP_LEDGERS",
        "status": "PASS" if len(snapshot_counts) == 42 and duplicate_groups == 0 and sum(counts.values()) == 63113 else "FAIL",
        "corpus_id": "r3000-proxy-pit-2006-2026-v1",
        "mode": "HISTORICAL_STATE_PROXY",
        "source_rows": 63113,
        "fund_snapshots": len(snapshot_counts),
        "resolution_counts": {status: counts.get(status, 0) for status in STATUSES},
        "resolved_fraction": counts.get("RESOLVED", 0) / 63113,
        "b3b_resolution_counts": b3.get("resolution_counts"),
        "methods_added": {"blackrock_retained_v4_exact_ticker_episode": blackrock_promoted, "blackrock_v4_multiple_active": blackrock_multi, "sec_v4_blackrock_name_plus_historical_price": sec_promoted, "sec_v4_name_price_ambiguous": sec_ambiguous, "collision_rows_demoted": collision_rows},
        "residual_classification_counts": dict(sorted(residual_classes.items())),
        "duplicate_security_assignments_after": duplicate_groups,
        "fund_ledger_rows": fund_counts,
        "union_ledger_rows": len(union_rows),
        "union_resolved_rows": sum(1 for row in union_rows if row["permanent_security_id"]),
        "union_unresolved_claim_rows": sum(1 for row in union_rows if not row["permanent_security_id"]),
        "v4_candidate_rows": candidate_summary.get("candidate_rows"),
        "v4_identity_evidence_rows_indexed": v4_identity_evidence_rows,
        "v4_canonical_audit_resolved_increment_episodes": audit_summary.get("resolved_by_v4_increment", {}).get("episodes"),
        "canonical_dataset_hash": manifest.get("dataset_hash"),
        "b3b_identity_ledger_sha256": sha256_file(b3b_root / "identity_ledger_v3b.csv.gz"),
        "v4_candidate_evidence_sha256": sha256_file(v4_root / "candidate_evidence.csv.gz"),
        "v4_audit_summary_sha256": sha256_file(audit_root / "summary.json"),
        "membership_semantics": "Fund membership comes only from contemporaneous IWB/IWM holdings snapshots. Ex-post authority may identify a permanent security but cannot create, remove, or move a membership claim in time.",
        "union_semantics": "Resolved same-date holdings dedupe by permanent security ID across IWB/IWM. Unresolved holdings remain distinct source claims and are never silently deduplicated.",
        "information_available_semantics": "MEMBERSHIP_DATE_PIT; IDENTITY_RECONSTRUCTION_AUTHORITY_MAY_BE_EX_POST",
        "caveat": CAVEAT,
    }
    (output / "summary_v4.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    members = [path for path in output.iterdir() if path.is_file() and path.name != "SHA256SUMS.txt"]
    (output / "SHA256SUMS.txt").write_text("".join(f"{sha256_file(path)}  {path.name}\n" for path in sorted(members)), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--b3b", type=Path, required=True)
    parser.add_argument("--v4", type=Path, required=True)
    parser.add_argument("--v4-audit", type=Path, required=True)
    parser.add_argument("--canonical", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(close_identity_v4(args.b3b, args.v4, args.v4_audit, args.canonical, args.output), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
