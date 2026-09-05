#!/usr/bin/env python3
"""Stage B identity closure for the IWB/IWM-derived Russell 3000 proxy.

Historical-only, fail-closed identity rules:
* holdings dates snap to the latest canonical PIT session at or before the date;
* BlackRock rows use only ticker identities observed on that historical session;
* unresolved BlackRock rows may use exact CUSIP/ISIN continuity anchored by an
  independently resolved historical ticker and present on the target session;
* SEC N-Q name-only rows may use deterministic exact/legal-name continuity
  anchored by resolved BlackRock rows and present on the target session;
* one-to-many evidence stays AMBIGUOUS and contradictory evidence is CONFLICT.
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
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

SCHEMA = "stocker.r3000-proxy.identity-closure/1"
CAVEAT = (
    "This is an IWB/IWM-derived Russell 3000 proxy and is not a licensed "
    "FTSE Russell constituent history."
)
STATUSES = ("RESOLVED", "AMBIGUOUS", "UNMATCHED", "CONFLICT")
EXTRA_FIELDS = (
    "identity_target_session",
    "identity_method",
    "identity_candidate_count",
    "identity_reason",
    "identity_canonical_security_type",
    "identity_canonical_issuer_source",
    "identity_canonical_identity_source",
    "identity_canonical_listing_active",
    "identity_canonical_tradeable",
)
LEGAL_TOKEN_ALIASES = {
    "CORPORATION": "CORP",
    "INCORPORATED": "INC",
    "COMPANY": "CO",
    "LIMITED": "LTD",
    "HOLDINGS": "HLDGS",
}
LEGAL_SUFFIXES = {
    "INC", "CORP", "CO", "LTD", "PLC", "LLC", "LP", "TRUST", "NV", "SA", "AG",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _open_csv(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return path.open("r", encoding="utf-8", newline="")


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with _open_csv(path) as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = [
            {str(k): "" if v is None else str(v) for k, v in row.items()}
            for row in reader
        ]
    return fields, rows


def write_csv_gz(path: Path, fieldnames: list[str], rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(
                    text, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore"
                )
                writer.writeheader()
                writer.writerows(rows)


def verify_sha256s(root: Path) -> None:
    sums = root / "SHA256SUMS.txt"
    if not sums.is_file():
        raise RuntimeError(f"missing SHA256SUMS.txt: {root}")
    for raw in sums.read_text(encoding="utf-8").splitlines():
        if not raw.strip():
            continue
        digest, member = raw.split(maxsplit=1)
        path = root / member.lstrip("*")
        if not path.is_file():
            raise RuntimeError(f"missing hashed member: {member}")
        observed = sha256_file(path)
        if observed != digest:
            raise RuntimeError(f"hash mismatch for {member}: {observed} != {digest}")


def ticker_key(value: str) -> str:
    # Normalize punctuation only. A concurrent collision remains ambiguous.
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper().strip())


def strict_name_key(value: str) -> str:
    text = (value or "").upper().replace("&", " AND ")
    return " ".join(re.findall(r"[A-Z0-9]+", text))


def legal_name_key(value: str) -> str:
    tokens = [LEGAL_TOKEN_ALIASES.get(t, t) for t in strict_name_key(value).split()]
    while tokens and tokens[-1] in LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def security_key(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper().strip())


def _source_row_id(row: dict[str, str]) -> str:
    return "|".join(
        (
            row.get("fund", ""),
            row.get("holdings_effective_date", ""),
            row.get("source_sha256", ""),
            row.get("source_row_number", ""),
        )
    )


def _evidence(
    method: str,
    *,
    dataset_hash: str,
    session: str,
    row: dict[str, str],
    key: str,
) -> str:
    payload = {
        "method": method,
        "canonical_dataset_hash": dataset_hash,
        "canonical_session": session,
        "source_type": row.get("source_type", ""),
        "source_id": row.get("source_id", ""),
        "source_sha256": row.get("source_sha256", ""),
        "source_row_number": row.get("source_row_number", ""),
        "continuity_key": key,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _candidate_records(
    candidates: set[str],
    session_sid: dict[str, dict[str, dict[str, str]]],
    session: str,
) -> list[dict[str, str]]:
    return [
        session_sid[session][sid]
        for sid in sorted(candidates)
        if sid in session_sid.get(session, {})
    ]


def _set_resolution(
    row: dict[str, str],
    *,
    status: str,
    session: str,
    method: str,
    records: list[dict[str, str]],
    reason: str,
    dataset_hash: str,
    evidence_key: str,
) -> None:
    unique = {r.get("security_id", ""): r for r in records if r.get("security_id", "")}
    row["identity_target_session"] = session
    row["identity_method"] = method
    row["identity_candidate_count"] = str(len(unique))
    row["identity_reason"] = reason
    row["identity_status"] = status
    row["normalized_security_id"] = ""
    row["normalized_ticker_on_snapshot_date"] = ""
    row["normalized_issuer_id"] = ""
    row["identity_authority"] = ""
    row["identity_canonical_security_type"] = ""
    row["identity_canonical_issuer_source"] = ""
    row["identity_canonical_identity_source"] = ""
    row["identity_canonical_listing_active"] = ""
    row["identity_canonical_tradeable"] = ""
    row["identity_evidence_refs"] = _evidence(
        method,
        dataset_hash=dataset_hash,
        session=session,
        row=row,
        key=evidence_key,
    )
    if status != "RESOLVED":
        return
    if len(unique) != 1:
        raise RuntimeError("RESOLVED requires exactly one security identity")
    record = next(iter(unique.values()))
    row["normalized_security_id"] = record.get("security_id", "")
    row["normalized_ticker_on_snapshot_date"] = record.get("ticker", "")
    row["normalized_issuer_id"] = record.get("issuer_id", "")
    row["identity_authority"] = method
    row["identity_canonical_security_type"] = record.get("security_type", "")
    row["identity_canonical_issuer_source"] = record.get("issuer_source", "")
    row["identity_canonical_identity_source"] = record.get("identity_source", "")
    row["identity_canonical_listing_active"] = record.get("listing_active", "")
    row["identity_canonical_tradeable"] = record.get("tradeable", "")


def _load_sessions(canonical_root: Path) -> list[str]:
    path = canonical_root / "session-hashes.csv"
    if not path.is_file():
        raise RuntimeError("canonical session-hashes.csv missing")
    with path.open("r", encoding="utf-8", newline="") as handle:
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
        session = sessions[index]
        if session > effective:
            raise RuntimeError("future session selected")
        result[effective] = session
    return result


def _load_target_observations(
    canonical_root: Path, target_by_date: dict[str, str]
) -> tuple[
    dict[str, dict[str, list[dict[str, str]]]],
    dict[str, dict[str, dict[str, str]]],
]:
    targets_by_year: dict[int, set[str]] = defaultdict(set)
    for session in target_by_date.values():
        targets_by_year[int(session[:4])].add(session)

    ticker_index: dict[str, dict[str, list[dict[str, str]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    session_sid: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)

    for year, targets in sorted(targets_by_year.items()):
        path = canonical_root / f"observations-{year}.csv.gz"
        if not path.is_file():
            raise RuntimeError(f"missing canonical observation partition: {path.name}")
        maximum = max(targets)
        found_sessions: set[str] = set()
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {
                "session", "security_id", "ticker", "issuer_id", "issuer_source",
                "security_type", "listing_active", "tradeable", "identity_source",
            }
            if not required.issubset(set(reader.fieldnames or [])):
                raise RuntimeError(f"canonical observation columns incomplete: {path.name}")
            for record in reader:
                session = record["session"]
                if session > maximum:
                    break
                if session not in targets:
                    continue
                found_sessions.add(session)
                sid = record.get("security_id", "")
                if not sid:
                    continue
                session_sid[session][sid] = record
                key = ticker_key(record.get("ticker", ""))
                if key:
                    ticker_index[session][key].append(record)
        if found_sessions != targets:
            raise RuntimeError(
                f"canonical target sessions missing from {path.name}: "
                f"{sorted(targets - found_sessions)}"
            )
    return ticker_index, session_sid


def _records_for_ticker(
    ticker_index: dict[str, dict[str, list[dict[str, str]]]],
    session: str,
    ticker: str,
) -> list[dict[str, str]]:
    unique: dict[str, dict[str, str]] = {}
    for record in ticker_index.get(session, {}).get(ticker_key(ticker), []):
        sid = record.get("security_id", "")
        if sid:
            unique[sid] = record
    return list(unique.values())


def _build_continuity_indexes(
    rows: list[dict[str, str]],
) -> tuple[
    dict[str, set[str]],
    dict[str, set[str]],
    dict[str, set[str]],
    dict[str, set[str]],
]:
    cusip: dict[str, set[str]] = defaultdict(set)
    isin: dict[str, set[str]] = defaultdict(set)
    strict_names: dict[str, set[str]] = defaultdict(set)
    legal_names: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        if row.get("source_type") != "blackrock_product_data_v2":
            continue
        if row.get("identity_status") != "RESOLVED":
            continue
        sid = row.get("normalized_security_id", "")
        if not sid:
            continue
        ck = security_key(row.get("reported_cusip", ""))
        ik = security_key(row.get("reported_isin", ""))
        nk = strict_name_key(row.get("reported_issuer_name", ""))
        lk = legal_name_key(row.get("reported_issuer_name", ""))
        if ck:
            cusip[ck].add(sid)
        if ik:
            isin[ik].add(sid)
        if nk:
            strict_names[nk].add(sid)
        if lk:
            legal_names[lk].add(sid)
    return cusip, isin, strict_names, legal_names


def close_identity(stage_a: Path, canonical_root: Path, output: Path) -> dict:
    verify_sha256s(stage_a)
    stage_summary = json.loads((stage_a / "summary.json").read_text(encoding="utf-8"))
    if stage_summary.get("status") != "PASS":
        raise RuntimeError("Stage A source package is not PASS")

    fields, rows = read_csv(stage_a / "parsed_holdings.csv.gz")
    if len(rows) != int(stage_summary.get("parsed_equity_rows", -1)):
        raise RuntimeError("Stage A parsed row count changed")
    if len({_source_row_id(row) for row in rows}) != len(rows):
        raise RuntimeError("duplicate Stage A source row identity")

    manifest_path = canonical_root / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("canonical manifest.json missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    dataset_hash = str(manifest.get("dataset_hash") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", dataset_hash):
        raise RuntimeError("canonical dataset hash missing or invalid")

    effective_dates = {row.get("holdings_effective_date", "") for row in rows}
    if "" in effective_dates:
        raise RuntimeError("source holding missing effective date")
    sessions = _load_sessions(canonical_root)
    target_by_date = _target_sessions(sessions, effective_dates)
    ticker_index, session_sid = _load_target_observations(canonical_root, target_by_date)

    direct_resolved = 0
    for row in rows:
        session = target_by_date[row["holdings_effective_date"]]
        if row.get("source_type") != "blackrock_product_data_v2":
            _set_resolution(
                row,
                status="UNMATCHED",
                session=session,
                method="SEC_NAME_PENDING",
                records=[],
                reason="NO_REPORTED_TICKER",
                dataset_hash=dataset_hash,
                evidence_key=strict_name_key(row.get("reported_issuer_name", "")),
            )
            continue
        records = _records_for_ticker(
            ticker_index, session, row.get("reported_ticker", "")
        )
        if len(records) == 1:
            _set_resolution(
                row,
                status="RESOLVED",
                session=session,
                method="CANONICAL_PIT_HISTORICAL_TICKER_SESSION",
                records=records,
                reason="",
                dataset_hash=dataset_hash,
                evidence_key=ticker_key(row.get("reported_ticker", "")),
            )
            direct_resolved += 1
        elif len(records) > 1:
            _set_resolution(
                row,
                status="AMBIGUOUS",
                session=session,
                method="CANONICAL_PIT_HISTORICAL_TICKER_SESSION",
                records=records,
                reason="MULTIPLE_SECURITY_IDS_FOR_HISTORICAL_TICKER",
                dataset_hash=dataset_hash,
                evidence_key=ticker_key(row.get("reported_ticker", "")),
            )
        else:
            _set_resolution(
                row,
                status="UNMATCHED",
                session=session,
                method="CANONICAL_PIT_HISTORICAL_TICKER_SESSION",
                records=[],
                reason="HISTORICAL_TICKER_ABSENT_ON_TARGET_SESSION",
                dataset_hash=dataset_hash,
                evidence_key=ticker_key(row.get("reported_ticker", "")),
            )

    cusip_index, isin_index, _, _ = _build_continuity_indexes(rows)
    cusip_resolved = 0
    isin_resolved = 0
    for row in rows:
        if row.get("source_type") != "blackrock_product_data_v2":
            continue
        session = row["identity_target_session"]
        active = session_sid.get(session, {})
        direct_sid = row.get("normalized_security_id", "")
        ck = security_key(row.get("reported_cusip", ""))
        ik = security_key(row.get("reported_isin", ""))

        if direct_sid:
            conflicts: set[str] = set()
            for key, index in ((ck, cusip_index), (ik, isin_index)):
                if not key:
                    continue
                active_candidates = {sid for sid in index.get(key, set()) if sid in active}
                conflicts.update(active_candidates - {direct_sid})
            if conflicts:
                _set_resolution(
                    row,
                    status="CONFLICT",
                    session=session,
                    method="IDENTIFIER_CONTINUITY_CONFLICT",
                    records=_candidate_records(conflicts | {direct_sid}, session_sid, session),
                    reason=(
                        "HISTORICAL_TICKER_DISAGREES_WITH_ACTIVE_IDENTIFIER_CONTINUITY"
                    ),
                    dataset_hash=dataset_hash,
                    evidence_key=ck or ik,
                )
            continue

        terminal = False
        for label, key, index in (
            ("BLACKROCK_CUSIP_CONTINUITY", ck, cusip_index),
            ("BLACKROCK_ISIN_CONTINUITY", ik, isin_index),
        ):
            if not key:
                continue
            candidates = {sid for sid in index.get(key, set()) if sid in active}
            records = _candidate_records(candidates, session_sid, session)
            if len(candidates) == 1:
                _set_resolution(
                    row,
                    status="RESOLVED",
                    session=session,
                    method=label,
                    records=records,
                    reason="",
                    dataset_hash=dataset_hash,
                    evidence_key=key,
                )
                if label == "BLACKROCK_CUSIP_CONTINUITY":
                    cusip_resolved += 1
                else:
                    isin_resolved += 1
                terminal = True
                break
            if len(candidates) > 1:
                _set_resolution(
                    row,
                    status="AMBIGUOUS",
                    session=session,
                    method=label,
                    records=records,
                    reason="MULTIPLE_ACTIVE_SECURITY_IDS_FOR_IDENTIFIER",
                    dataset_hash=dataset_hash,
                    evidence_key=key,
                )
                terminal = True
                break
        if not terminal and row.get("identity_status") != "AMBIGUOUS":
            row["identity_reason"] = (
                "NO_HISTORICAL_TICKER_OR_IDENTIFIER_CONTINUITY_AUTHORITY"
            )

    _, _, strict_names, legal_names = _build_continuity_indexes(rows)
    sec_strict_resolved = 0
    sec_legal_resolved = 0
    for row in rows:
        if row.get("source_type") != "sec_n-q":
            continue
        session = row["identity_target_session"]
        active = session_sid.get(session, {})
        resolved_or_ambiguous = False
        attempts = (
            (
                "BLACKROCK_EXACT_NAME_CONTINUITY",
                strict_name_key(row.get("reported_issuer_name", "")),
                strict_names,
            ),
            (
                "BLACKROCK_LEGAL_NAME_CONTINUITY",
                legal_name_key(row.get("reported_issuer_name", "")),
                legal_names,
            ),
        )
        for label, key, index in attempts:
            if not key:
                continue
            candidates = {sid for sid in index.get(key, set()) if sid in active}
            records = _candidate_records(candidates, session_sid, session)
            if len(candidates) == 1:
                _set_resolution(
                    row,
                    status="RESOLVED",
                    session=session,
                    method=label,
                    records=records,
                    reason="",
                    dataset_hash=dataset_hash,
                    evidence_key=key,
                )
                if label == "BLACKROCK_EXACT_NAME_CONTINUITY":
                    sec_strict_resolved += 1
                else:
                    sec_legal_resolved += 1
                resolved_or_ambiguous = True
                break
            if len(candidates) > 1:
                _set_resolution(
                    row,
                    status="AMBIGUOUS",
                    session=session,
                    method=label,
                    records=records,
                    reason="MULTIPLE_ACTIVE_SECURITY_IDS_FOR_NAME",
                    dataset_hash=dataset_hash,
                    evidence_key=key,
                )
                resolved_or_ambiguous = True
                break
        if not resolved_or_ambiguous:
            _set_resolution(
                row,
                status="UNMATCHED",
                session=session,
                method="BLACKROCK_NAME_CONTINUITY",
                records=[],
                reason="NO_EXACT_HISTORICAL_NAME_CONTINUITY_AUTHORITY",
                dataset_hash=dataset_hash,
                evidence_key=strict_name_key(row.get("reported_issuer_name", "")),
            )

    status_counts = Counter(row.get("identity_status", "") for row in rows)
    unknown = sorted(set(status_counts) - set(STATUSES))
    if unknown:
        raise RuntimeError(f"unexpected identity statuses: {unknown}")

    snapshot_counts: dict[tuple[str, str], Counter] = defaultdict(Counter)
    assignments: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for row in rows:
        key = (row.get("fund", ""), row.get("holdings_effective_date", ""))
        snapshot_counts[key][row["identity_status"]] += 1
        sid = row.get("normalized_security_id", "")
        if row["identity_status"] == "RESOLVED" and sid:
            assignments[(key[0], key[1], sid)].append(_source_row_id(row))

    duplicate_assignments = [
        {
            "fund": key[0],
            "holdings_effective_date": key[1],
            "security_id": key[2],
            "source_rows": values,
        }
        for key, values in sorted(assignments.items())
        if len(values) > 1
    ]

    output.mkdir(parents=True, exist_ok=True)
    output_fields = list(fields)
    for field in EXTRA_FIELDS:
        if field not in output_fields:
            output_fields.append(field)
    ledger_path = output / "identity_ledger.csv.gz"
    unresolved_path = output / "identity_unresolved_worklist.csv.gz"
    write_csv_gz(ledger_path, output_fields, rows)
    write_csv_gz(
        unresolved_path,
        output_fields,
        [row for row in rows if row.get("identity_status") != "RESOLVED"],
    )

    snapshot_rows = []
    for (fund, effective), counts in sorted(snapshot_counts.items()):
        snapshot_rows.append(
            {
                "fund": fund,
                "holdings_effective_date": effective,
                "identity_target_session": target_by_date[effective],
                "rows": str(sum(counts.values())),
                **{status.lower(): str(counts.get(status, 0)) for status in STATUSES},
            }
        )
    snapshot_fields = [
        "fund", "holdings_effective_date", "identity_target_session", "rows",
        "resolved", "ambiguous", "unmatched", "conflict",
    ]
    write_csv_gz(
        output / "identity_snapshot_summary.csv.gz", snapshot_fields, snapshot_rows
    )

    total = len(rows)
    resolved = status_counts.get("RESOLVED", 0)
    summary = {
        "schema": SCHEMA,
        "stage": "IDENTITY_CLOSURE_PASS_1",
        "status": "PASS" if sum(status_counts.values()) == total else "FAIL",
        "corpus_id": "r3000-proxy-pit-2006-2026-v1",
        "mode": "HISTORICAL_STATE_PROXY",
        "source_rows": total,
        "fund_snapshots": len(snapshot_counts),
        "resolution_counts": {status: status_counts.get(status, 0) for status in STATUSES},
        "resolved_fraction": resolved / total if total else 0.0,
        "methods": {
            "canonical_historical_ticker": direct_resolved,
            "blackrock_cusip_continuity": cusip_resolved,
            "blackrock_isin_continuity": isin_resolved,
            "sec_exact_name_continuity": sec_strict_resolved,
            "sec_legal_name_continuity": sec_legal_resolved,
        },
        "duplicate_security_assignments_within_fund_snapshot": len(duplicate_assignments),
        "duplicate_assignment_examples": duplicate_assignments[:50],
        "future_session_violations": sum(
            1
            for row in rows
            if row["identity_target_session"] > row["holdings_effective_date"]
        ),
        "stage_a_parsed_holdings_sha256": sha256_file(
            stage_a / "parsed_holdings.csv.gz"
        ),
        "stage_a_summary_sha256": sha256_file(stage_a / "summary.json"),
        "canonical_dataset_hash": dataset_hash,
        "canonical_manifest_sha256": sha256_file(manifest_path),
        "identity_ledger_sha256": sha256_file(ledger_path),
        "unresolved_worklist_sha256": sha256_file(unresolved_path),
        "acceptance_state": (
            "IDENTITY_CLOSED"
            if resolved == total and not duplicate_assignments
            else "OPEN_IDENTITY_WORKLIST"
        ),
        "caveat": CAVEAT,
    }
    (output / "identity_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    members = [
        path for path in output.iterdir()
        if path.is_file() and path.name != "SHA256SUMS.txt"
    ]
    (output / "SHA256SUMS.txt").write_text(
        "".join(
            f"{sha256_file(path)}  {path.name}\n" for path in sorted(members)
        ),
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage-a", type=Path, required=True)
    parser.add_argument("--canonical", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = close_identity(args.stage_a, args.canonical, args.output)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
