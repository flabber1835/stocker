#!/usr/bin/env python3
"""Stage B3 identity closure using SEC CIK current/former-name authority.

Consumes the immutable B2 ledger and the pinned canonical PIT package.  Any new
promotion requires an exact historical price match on the target session plus
issuer-name authority.  SEC current/former names are read from the SEC bulk
submissions archive keyed by CIK.  No fuzzy name promotion is allowed.

This is HISTORICAL_STATE_PROXY reconstruction.  The current SEC submissions
archive may contain information learned after the historical date and therefore
is not admitted for INFORMATION_AVAILABLE_PROXY semantics.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import hashlib
import io
import json
import re
import zipfile
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Iterable

from backtester.r3000_proxy_identity_closure import CAVEAT, STATUSES, read_csv, sha256_file, verify_sha256s, write_csv_gz

SCHEMA = "stocker.r3000-proxy.identity-closure/3"
B2_SCHEMA = "stocker.r3000-proxy.identity-closure/2"
LEGAL_ALIASES = {
    "CORPORATION": "CORP",
    "INCORPORATED": "INC",
    "COMPANY": "CO",
    "LIMITED": "LTD",
    "HOLDINGS": "HLDGS",
    "TECHNOLOGIES": "TECH",
    "TECHNOLOGY": "TECH",
}
LEGAL_SUFFIXES = {"INC", "CORP", "CO", "LTD", "PLC", "LLC", "LP", "TRUST", "NV", "SA", "AG"}


def _number(value: str) -> Decimal | None:
    text = (value or "").replace(",", "").replace("$", "").strip()
    if not text or text == "-":
        return None
    try:
        value_d = Decimal(text)
    except InvalidOperation:
        return None
    if not value_d.is_finite() or value_d <= 0:
        return None
    return value_d


def _cents(value: str) -> Decimal | None:
    number = _number(value)
    if number is None:
        return None
    return number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _clean_source_name(value: str) -> str:
    text = (value or "").strip()
    # N-Q schedules append footnote references such as (1), (2), (1)(2), a, a,b.
    text = re.sub(r"(?:\s*\(\s*\d+[A-Za-z*]?\s*\)\s*)+$", "", text)
    text = re.sub(r"(?:\s+[a-z](?:\s*,\s*[a-z])*)\s*$", "", text)
    text = re.sub(r"\s+\*+\s*$", "", text)
    # A common schedule rendering is "Boeing Co. (The)".
    text = re.sub(r"\s*\(\s*THE\s*\)\s*$", "", text, flags=re.IGNORECASE)
    return text.strip()


def _tokens(value: str) -> list[str]:
    text = _clean_source_name(value).upper().replace("&", " AND ")
    tokens = re.findall(r"[A-Z0-9]+", text)
    if tokens and tokens[0] == "THE":
        tokens = tokens[1:]
    return [LEGAL_ALIASES.get(token, token) for token in tokens]


def _legal_key(value: str, *, broad: bool = False) -> str:
    tokens = _tokens(value)
    if broad:
        out: list[str] = []
        skip = False
        for token in tokens:
            if skip:
                skip = False
                continue
            if token in {"CLASS", "CL"}:
                skip = True
                continue
            if token in {"COMMON", "ORDINARY", "SHARE", "SHARES", "STOCK"}:
                continue
            out.append(token)
        tokens = out
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def _name_variants(value: str) -> set[str]:
    variants = {_legal_key(value, broad=False), _legal_key(value, broad=True)}
    return {variant for variant in variants if variant}


def _source_row_id(row: dict[str, str]) -> str:
    return "|".join((row.get("fund", ""), row.get("holdings_effective_date", ""), row.get("source_sha256", ""), row.get("source_row_number", "")))


def _load_sessions(canonical_root: Path) -> list[str]:
    with (canonical_root / "session-hashes.csv").open("r", encoding="utf-8", newline="") as handle:
        sessions = [row["session"] for row in csv.DictReader(handle)]
    if not sessions or sessions != sorted(sessions) or len(sessions) != len(set(sessions)):
        raise RuntimeError("canonical session axis invalid")
    return sessions


def _target_sessions(sessions: list[str], dates: set[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for effective in sorted(dates):
        index = bisect.bisect_right(sessions, effective) - 1
        if index < 0:
            raise RuntimeError(f"no canonical session at or before {effective}")
        result[effective] = sessions[index]
    return result


def _load_target_prices(canonical_root: Path, target_by_date: dict[str, str]):
    targets_by_year: dict[int, set[str]] = defaultdict(set)
    for session in target_by_date.values():
        targets_by_year[int(session[:4])].add(session)
    by_price: dict[str, dict[Decimal, dict[str, dict[str, str]]]] = defaultdict(lambda: defaultdict(dict))
    by_sid: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    required = {"session", "security_id", "ticker", "issuer_id", "issuer_source", "security_type", "listing_active", "tradeable", "identity_source", "raw_close", "exchange"}
    for year, targets in sorted(targets_by_year.items()):
        path = canonical_root / f"observations-{year}.csv.gz"
        if not path.is_file():
            raise RuntimeError(f"missing {path.name}")
        maximum = max(targets)
        found: set[str] = set()
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if not required.issubset(set(reader.fieldnames or [])):
                raise RuntimeError(f"canonical columns incomplete in {path.name}")
            for record in reader:
                session = record["session"]
                if session > maximum:
                    break
                if session not in targets:
                    continue
                found.add(session)
                sid = record.get("security_id", "")
                if not sid:
                    continue
                by_sid[session][sid] = record
                price = _cents(record.get("raw_close", ""))
                if price is not None:
                    by_price[session][price][sid] = record
        if found != targets:
            raise RuntimeError(f"canonical target sessions missing: {sorted(targets - found)}")
    return by_price, by_sid


def _price_candidates(row: dict[str, str], by_price) -> tuple[Decimal | None, dict[str, dict[str, str]]]:
    price = _cents(row.get("reported_unit_price", ""))
    if price is None:
        return None, {}
    return price, dict(by_price.get(row["identity_target_session"], {}).get(price, {}))


def _parse_cik(issuer_id: str) -> str | None:
    match = re.fullmatch(r"SEC_CIK:(\d+)", (issuer_id or "").strip())
    if not match:
        return None
    return match.group(1).zfill(10)


def _sec_names(payload: dict) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    current = str(payload.get("name") or "").strip()
    if current:
        rows.append({"name": current, "kind": "CURRENT", "from": "", "to": ""})
    former = payload.get("formerNames") or []
    if isinstance(former, list):
        for item in former:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            rows.append({"name": name, "kind": "FORMER", "from": str(item.get("from") or ""), "to": str(item.get("to") or "")})
    return rows


def _load_sec_authority(sec_zip: Path, ciks: set[str]) -> tuple[dict[str, dict], list[dict[str, str]]]:
    archive_sha = sha256_file(sec_zip)
    authorities: dict[str, dict] = {}
    evidence_rows: list[dict[str, str]] = []
    with zipfile.ZipFile(sec_zip) as archive:
        members = set(archive.namelist())
        for cik in sorted(ciks):
            member = f"CIK{cik}.json"
            if member not in members:
                evidence_rows.append({"cik": cik, "status": "MISSING", "bulk_sha256": archive_sha, "member": member, "member_sha256": "", "current_name": "", "former_names_json": "[]", "tickers_json": "[]", "exchanges_json": "[]"})
                continue
            body = archive.read(member)
            member_sha = hashlib.sha256(body).hexdigest()
            payload = json.loads(body)
            names = _sec_names(payload)
            authority = {
                "cik": cik,
                "names": names,
                "variants": {variant for item in names for variant in _name_variants(item["name"])},
                "member": member,
                "member_sha256": member_sha,
                "bulk_sha256": archive_sha,
            }
            authorities[cik] = authority
            evidence_rows.append({
                "cik": cik,
                "status": "PASS",
                "bulk_sha256": archive_sha,
                "member": member,
                "member_sha256": member_sha,
                "current_name": str(payload.get("name") or ""),
                "former_names_json": json.dumps(payload.get("formerNames") or [], sort_keys=True, separators=(",", ":")),
                "tickers_json": json.dumps(payload.get("tickers") or [], sort_keys=True, separators=(",", ":")),
                "exchanges_json": json.dumps(payload.get("exchanges") or [], sort_keys=True, separators=(",", ":")),
            })
    return authorities, evidence_rows


def _authority_match(row: dict[str, str], authority: dict) -> bool:
    return bool(_name_variants(row.get("reported_issuer_name", "")) & set(authority.get("variants") or set()))


def _set_resolved(row: dict[str, str], record: dict[str, str], *, method: str, reason: str, detail: dict) -> None:
    row["identity_status"] = "RESOLVED"
    row["normalized_security_id"] = record.get("security_id", "")
    row["normalized_ticker_on_snapshot_date"] = record.get("ticker", "")
    row["normalized_issuer_id"] = record.get("issuer_id", "")
    row["identity_authority"] = method
    row["identity_method"] = method
    row["identity_candidate_count"] = "1"
    row["identity_reason"] = reason
    row["identity_canonical_security_type"] = record.get("security_type", "")
    row["identity_canonical_issuer_source"] = record.get("issuer_source", "")
    row["identity_canonical_identity_source"] = record.get("identity_source", "")
    row["identity_canonical_listing_active"] = record.get("listing_active", "")
    row["identity_canonical_tradeable"] = record.get("tradeable", "")
    row["identity_evidence_refs"] = json.dumps(detail, sort_keys=True, separators=(",", ":"))


def _set_open(row: dict[str, str], *, status: str, method: str, reason: str, candidate_count: int, detail: dict | None = None) -> None:
    row["identity_status"] = status
    row["identity_method"] = method
    row["identity_reason"] = reason
    row["identity_candidate_count"] = str(candidate_count)
    row["normalized_security_id"] = ""
    row["normalized_ticker_on_snapshot_date"] = ""
    row["normalized_issuer_id"] = ""
    row["identity_authority"] = ""
    if detail is not None:
        row["identity_evidence_refs"] = json.dumps(detail, sort_keys=True, separators=(",", ":"))


def close_identity_v3(b2_root: Path, canonical_root: Path, sec_zip: Path, output: Path) -> dict:
    verify_sha256s(b2_root)
    b2_summary = json.loads((b2_root / "identity_summary_v2.json").read_text(encoding="utf-8"))
    if b2_summary.get("schema") != B2_SCHEMA or b2_summary.get("status") != "PASS":
        raise RuntimeError("B2 artifact is not a passing schema-2 identity package")
    fields, rows = read_csv(b2_root / "identity_ledger_v2.csv.gz")
    if len(rows) != int(b2_summary.get("source_rows", -1)):
        raise RuntimeError("B2 ledger row count changed")
    if len({_source_row_id(row) for row in rows}) != len(rows):
        raise RuntimeError("duplicate source row identity in B2 ledger")

    manifest_path = canonical_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dataset_hash = str(manifest.get("dataset_hash") or "")
    if dataset_hash != b2_summary.get("canonical_dataset_hash"):
        raise RuntimeError("canonical dataset hash differs from B2 authority")

    dates = {row["holdings_effective_date"] for row in rows}
    target_by_date = _target_sessions(_load_sessions(canonical_root), dates)
    for row in rows:
        if row.get("identity_target_session") != target_by_date[row["holdings_effective_date"]]:
            raise RuntimeError("B2 target-session drift")
    by_price, by_sid = _load_target_prices(canonical_root, target_by_date)

    # Improved deterministic SEC schedule-name normalization closes footnote-only gaps
    # using already price-certified BlackRock identities.
    blackrock_name_index: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if row.get("source_type") != "blackrock_product_data_v2" or row.get("identity_status") != "RESOLVED":
            continue
        sid = row.get("normalized_security_id", "")
        if not sid:
            continue
        for variant in _name_variants(row.get("reported_issuer_name", "")):
            blackrock_name_index[variant].add(sid)

    local_name_resolved = 0
    for row in rows:
        if row.get("source_type") != "sec_n-q" or row.get("identity_status") == "RESOLVED":
            continue
        price, candidates = _price_candidates(row, by_price)
        if price is None or not candidates:
            continue
        matched_sids: set[str] = set()
        for variant in _name_variants(row.get("reported_issuer_name", "")):
            matched_sids.update(blackrock_name_index.get(variant, set()))
        matched_sids &= set(candidates)
        if len(matched_sids) == 1:
            sid = next(iter(matched_sids))
            record = candidates[sid]
            _set_resolved(row, record, method="BLACKROCK_PRICE_CERTIFIED_NAME_V2_PLUS_SEC_FOOTNOTE_NORMALIZATION", reason="", detail={
                "method": "BLACKROCK_PRICE_CERTIFIED_NAME_V2_PLUS_SEC_FOOTNOTE_NORMALIZATION",
                "source_name": row.get("reported_issuer_name", ""),
                "name_variants": sorted(_name_variants(row.get("reported_issuer_name", ""))),
                "historical_price_cents": format(price, "f"),
                "canonical_dataset_hash": dataset_hash,
            })
            local_name_resolved += 1

    # Collect SEC CIK authority only for still-open price candidates plus all
    # currently duplicated resolved identities, so false same-snapshot collapses
    # can be adjudicated.
    candidate_cache: dict[int, tuple[Decimal | None, dict[str, dict[str, str]]]] = {}
    ciks: set[str] = set()
    for index, row in enumerate(rows):
        price, candidates = _price_candidates(row, by_price)
        candidate_cache[index] = (price, candidates)
        if row.get("identity_status") != "RESOLVED":
            for record in candidates.values():
                cik = _parse_cik(record.get("issuer_id", ""))
                if cik:
                    ciks.add(cik)

    assignments: dict[tuple[str, str, str], list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        if row.get("identity_status") == "RESOLVED" and row.get("normalized_security_id"):
            assignments[(row.get("fund", ""), row.get("holdings_effective_date", ""), row["normalized_security_id"])].append(index)
    duplicate_groups_before = {key: indexes for key, indexes in assignments.items() if len(indexes) > 1}
    for (_, effective, sid), indexes in duplicate_groups_before.items():
        session = target_by_date[effective]
        record = by_sid.get(session, {}).get(sid)
        if record:
            cik = _parse_cik(record.get("issuer_id", ""))
            if cik:
                ciks.add(cik)

    authorities, sec_evidence = _load_sec_authority(sec_zip, ciks)
    sec_bulk_sha = sha256_file(sec_zip)
    sec_missing_ciks = sum(1 for row in sec_evidence if row["status"] != "PASS")

    sec_resolved = 0
    sec_ambiguous = 0
    sec_no_cik = 0
    sec_no_name_match = 0
    for index, row in enumerate(rows):
        if row.get("identity_status") == "RESOLVED":
            continue
        price, candidates = candidate_cache[index]
        if price is None or not candidates:
            continue
        qualified: dict[str, tuple[dict[str, str], str, dict]] = {}
        candidate_cik_count = 0
        for sid, record in candidates.items():
            cik = _parse_cik(record.get("issuer_id", ""))
            if not cik:
                continue
            candidate_cik_count += 1
            authority = authorities.get(cik)
            if authority and _authority_match(row, authority):
                qualified[sid] = (record, cik, authority)
        if len(qualified) == 1:
            sid, (record, cik, authority) = next(iter(qualified.items()))
            _set_resolved(row, record, method="SEC_CIK_CURRENT_FORMER_NAME_PLUS_HISTORICAL_PRICE", reason="", detail={
                "method": "SEC_CIK_CURRENT_FORMER_NAME_PLUS_HISTORICAL_PRICE",
                "cik": cik,
                "sec_bulk_sha256": sec_bulk_sha,
                "sec_member": authority["member"],
                "sec_member_sha256": authority["member_sha256"],
                "source_name": row.get("reported_issuer_name", ""),
                "source_name_variants": sorted(_name_variants(row.get("reported_issuer_name", ""))),
                "matched_sec_names": [item for item in authority["names"] if _name_variants(item["name"]) & _name_variants(row.get("reported_issuer_name", ""))],
                "historical_price_cents": format(price, "f"),
                "canonical_dataset_hash": dataset_hash,
            })
            sec_resolved += 1
        elif len(qualified) > 1:
            _set_open(row, status="AMBIGUOUS", method="SEC_CIK_CURRENT_FORMER_NAME_PLUS_HISTORICAL_PRICE", reason="MULTIPLE_SEC_CIK_NAME_AND_PRICE_MATCHES", candidate_count=len(qualified), detail={
                "method": "SEC_CIK_CURRENT_FORMER_NAME_PLUS_HISTORICAL_PRICE",
                "candidate_security_ids": sorted(qualified),
                "sec_bulk_sha256": sec_bulk_sha,
                "historical_price_cents": format(price, "f"),
            })
            sec_ambiguous += 1
        elif candidate_cik_count == 0:
            row["identity_reason"] = "NO_SEC_CIK_AUTHORITY_ON_HISTORICAL_PRICE_CANDIDATES"
            sec_no_cik += 1
        else:
            row["identity_reason"] = "NO_EXACT_SEC_CURRENT_FORMER_NAME_MATCH_ON_HISTORICAL_PRICE_CANDIDATES"
            sec_no_name_match += 1

    # Re-adjudicate same-fund/snapshot duplicate security assignments.  A single
    # exact SEC CIK name match may retain the identity; all other rows are opened.
    duplicate_rows_demoted = 0
    assignments = defaultdict(list)
    for index, row in enumerate(rows):
        if row.get("identity_status") == "RESOLVED" and row.get("normalized_security_id"):
            assignments[(row.get("fund", ""), row.get("holdings_effective_date", ""), row["normalized_security_id"])].append(index)
    for (fund, effective, sid), indexes in sorted(assignments.items()):
        if len(indexes) <= 1:
            continue
        session = target_by_date[effective]
        record = by_sid.get(session, {}).get(sid)
        cik = _parse_cik(record.get("issuer_id", "")) if record else None
        authority = authorities.get(cik or "")
        matching = [index for index in indexes if authority and _authority_match(rows[index], authority)]
        if len(matching) == 1:
            keep = matching[0]
            for index in indexes:
                if index == keep:
                    continue
                row = rows[index]
                _set_open(row, status="UNMATCHED", method="DUPLICATE_SECURITY_ID_SEC_CIK_ADJUDICATION", reason="DUPLICATE_SID_REJECTED_BY_SEC_CIK_NAME_AUTHORITY", candidate_count=1, detail={
                    "method": "DUPLICATE_SECURITY_ID_SEC_CIK_ADJUDICATION",
                    "security_id": sid,
                    "cik": cik,
                    "sec_bulk_sha256": sec_bulk_sha,
                    "sec_member_sha256": authority["member_sha256"] if authority else "",
                })
                duplicate_rows_demoted += 1
        else:
            for index in indexes:
                row = rows[index]
                _set_open(row, status="AMBIGUOUS", method="DUPLICATE_SECURITY_ID_FAIL_CLOSED", reason="DUPLICATE_SID_NOT_UNIQUELY_ADJUDICATED", candidate_count=len(indexes), detail={
                    "method": "DUPLICATE_SECURITY_ID_FAIL_CLOSED",
                    "security_id": sid,
                    "cik": cik or "",
                    "same_snapshot_source_rows": [_source_row_id(rows[item]) for item in indexes],
                })
                duplicate_rows_demoted += 1

    counts = Counter(row.get("identity_status", "") for row in rows)
    if set(counts) - set(STATUSES):
        raise RuntimeError(f"unknown identity statuses: {sorted(set(counts)-set(STATUSES))}")
    future_violations = sum(1 for row in rows if row["identity_target_session"] > row["holdings_effective_date"])

    final_assignments: dict[tuple[str, str, str], int] = Counter()
    snapshot_counts: dict[tuple[str, str], Counter] = defaultdict(Counter)
    for row in rows:
        snap = (row.get("fund", ""), row.get("holdings_effective_date", ""))
        snapshot_counts[snap][row["identity_status"]] += 1
        if row["identity_status"] == "RESOLVED" and row.get("normalized_security_id"):
            final_assignments[(snap[0], snap[1], row["normalized_security_id"])] += 1
    duplicate_groups_after = sum(1 for value in final_assignments.values() if value > 1)

    output.mkdir(parents=True, exist_ok=True)
    ledger_path = output / "identity_ledger_v3.csv.gz"
    worklist_path = output / "identity_unresolved_worklist_v3.csv.gz"
    write_csv_gz(ledger_path, fields, rows)
    write_csv_gz(worklist_path, fields, [row for row in rows if row["identity_status"] != "RESOLVED"])
    snapshot_rows = []
    for (fund, effective), snap_counts in sorted(snapshot_counts.items()):
        snapshot_rows.append({
            "fund": fund,
            "holdings_effective_date": effective,
            "identity_target_session": target_by_date[effective],
            "rows": str(sum(snap_counts.values())),
            **{status.lower(): str(snap_counts.get(status, 0)) for status in STATUSES},
        })
    write_csv_gz(output / "identity_snapshot_summary_v3.csv.gz", ["fund", "holdings_effective_date", "identity_target_session", "rows", "resolved", "ambiguous", "unmatched", "conflict"], snapshot_rows)
    sec_fields = ["cik", "status", "bulk_sha256", "member", "member_sha256", "current_name", "former_names_json", "tickers_json", "exchanges_json"]
    write_csv_gz(output / "sec_cik_name_authority.csv.gz", sec_fields, sec_evidence)

    summary = {
        "schema": SCHEMA,
        "stage": "IDENTITY_CLOSURE_SEC_CIK_AUTHORITY_PASS_3",
        "status": "PASS" if sum(counts.values()) == len(rows) and future_violations == 0 and duplicate_groups_after == 0 else "FAIL",
        "corpus_id": "r3000-proxy-pit-2006-2026-v1",
        "mode": "HISTORICAL_STATE_PROXY",
        "source_rows": len(rows),
        "fund_snapshots": len(snapshot_counts),
        "resolution_counts": {status: counts.get(status, 0) for status in STATUSES},
        "resolved_fraction": counts.get("RESOLVED", 0) / len(rows),
        "b2_resolution_counts": b2_summary.get("resolution_counts"),
        "methods_added": {
            "sec_footnote_normalization_plus_price_certified_blackrock_name": local_name_resolved,
            "sec_cik_current_former_name_plus_historical_price": sec_resolved,
            "sec_cik_ambiguous": sec_ambiguous,
            "duplicate_rows_demoted": duplicate_rows_demoted,
        },
        "authority_gaps": {
            "candidate_rows_without_sec_cik": sec_no_cik,
            "candidate_rows_without_exact_sec_name_match": sec_no_name_match,
            "sec_cik_members_missing_from_bulk_archive": sec_missing_ciks,
        },
        "sec_bulk_submissions_sha256": sec_bulk_sha,
        "sec_ciks_requested": len(ciks),
        "sec_ciks_loaded": len(authorities),
        "duplicate_security_assignments_before": len(duplicate_groups_before),
        "duplicate_security_assignments_after": duplicate_groups_after,
        "future_session_violations": future_violations,
        "b2_ledger_sha256": sha256_file(b2_root / "identity_ledger_v2.csv.gz"),
        "b2_summary_sha256": sha256_file(b2_root / "identity_summary_v2.json"),
        "canonical_dataset_hash": dataset_hash,
        "canonical_manifest_sha256": sha256_file(manifest_path),
        "identity_ledger_sha256": sha256_file(ledger_path),
        "unresolved_worklist_sha256": sha256_file(worklist_path),
        "historical_state_semantics": "SEC current/former-name metadata may be used as later archival identity authority only when the source holding independently matches the candidate security's historical raw close on the target session.",
        "information_available_semantics": "NOT_CERTIFIED_BY_THIS_STAGE",
        "acceptance_state": "IDENTITY_CLOSED" if counts.get("RESOLVED", 0) == len(rows) else "OPEN_IDENTITY_WORKLIST",
        "caveat": CAVEAT,
    }
    summary_path = output / "identity_summary_v3.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    members = [path for path in output.iterdir() if path.is_file() and path.name != "SHA256SUMS.txt"]
    (output / "SHA256SUMS.txt").write_text("".join(f"{sha256_file(path)}  {path.name}\n" for path in sorted(members)), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--b2", type=Path, required=True)
    parser.add_argument("--canonical", type=Path, required=True)
    parser.add_argument("--sec-submissions-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(close_identity_v3(args.b2, args.canonical, args.sec_submissions_zip, args.output), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
