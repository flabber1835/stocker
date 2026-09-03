#!/usr/bin/env python3
"""Fail-closed 2007 Russell 3000 security-identity closure and certification.

This module deliberately separates two authorities:

* the filed 2007 membership source, which establishes which 2,976 source rows
  must be accounted for; and
* historical security-identity evidence, which establishes the ticker/security
  episode for each source row under a strict-prior causal rule.

No name similarity or discovery result is promoted to authority by this layer.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Iterable

SCHEMA = "backtester.historical-metadata-2007-closure/1"
TARGET_YEAR = 2007
EXPECTED_ROWS = 2976

LEDGER_FIELDS = [
    "target_year",
    "source_row_id",
    "source_name",
    "source_ticker",
    "membership_authority",
    "membership_source_url",
    "membership_source_member",
    "membership_source_sha256",
    "decision_session",
    "resolution_status",
    "resolved_ticker",
    "security_id",
    "issuer_cik",
    "security_type",
    "identity_authority",
    "identity_form",
    "identity_accession",
    "identity_filed",
    "identity_usable_after",
    "identity_source_url",
    "identity_source_member",
    "identity_source_sha256",
    "reason_code",
]

CONSTITUENT_FIELDS = [
    "source_row_id",
    "source_name",
    "source_ticker",
    "ticker",
    "security_id",
    "issuer_cik",
    "security_type",
    "decision_session",
]

TERMINAL_STATUSES = {"RESOLVED", "AMBIGUOUS", "UNCLASSIFIED", "CONFLICT", "NO_AUTHORITY"}
UNKNOWN_TYPE = {"", "unknown", "unclassified", "none", "null", "na", "n/a"}


def _open_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", newline="")
    return path.open("r", encoding="utf-8", newline="")


def read_csv(path: Path) -> list[dict[str, str]]:
    with _open_text(path) as fh:
        return [{str(k): ("" if v is None else str(v)) for k, v in row.items()} for row in csv.DictReader(fh)]


def write_gzip_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _first(row: dict[str, str], *names: str) -> str:
    for name in names:
        value = (row.get(name) or "").strip()
        if value:
            return value
    return ""


def _norm_ticker(value: str) -> str:
    return (value or "").strip().upper()


def _norm_cik(value: str) -> str:
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    if not digits:
        return ""
    return digits.zfill(10)


def _norm_type(value: str) -> str:
    return (value or "").strip().lower()


def _parse_iso(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _source_row_id(row: dict[str, str], ordinal: int) -> str:
    value = _first(row, "source_row_id", "row_id", "source_id", "holding_id")
    if value:
        return value
    return f"2007-{ordinal:04d}"


def _candidate_identity(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        _norm_ticker(_first(row, "resolved_ticker", "ticker")),
        _first(row, "security_id"),
        _norm_cik(_first(row, "issuer_cik", "candidate_cik", "cik", "source_cik")),
    )


def _candidate_type(row: dict[str, str]) -> str:
    return _norm_type(_first(row, "security_type", "classification"))


def _candidate_explicit_status(row: dict[str, str]) -> str:
    value = _first(row, "resolution_status", "status").upper()
    return value if value in TERMINAL_STATUSES else ""


def _select_candidate(rows: list[dict[str, str]]) -> tuple[str, dict[str, str] | None, str]:
    """Resolve candidate rows only when they all support one security identity."""
    if not rows:
        return "NO_AUTHORITY", None, "NO_ADJUDICATION"

    explicit = {_candidate_explicit_status(r) for r in rows} - {""}
    if "CONFLICT" in explicit:
        return "CONFLICT", None, "EXPLICIT_CONFLICT"
    if explicit and explicit <= {"NO_AUTHORITY"}:
        return "NO_AUTHORITY", None, "NO_AUTHORITY"

    identities = {_candidate_identity(r) for r in rows if all(_candidate_identity(r)[:2])}
    if len(identities) > 1:
        return "AMBIGUOUS", None, "MULTIPLE_SECURITY_IDENTITIES"
    if not identities:
        if "AMBIGUOUS" in explicit:
            return "AMBIGUOUS", None, "EXPLICIT_AMBIGUITY"
        return "NO_AUTHORITY", None, "MISSING_SECURITY_IDENTITY"

    identity = next(iter(identities))
    matching = [r for r in rows if _candidate_identity(r) == identity]
    types = {_candidate_type(r) for r in matching if _candidate_type(r) not in UNKNOWN_TYPE}
    if len(types) > 1:
        return "CONFLICT", None, "MULTIPLE_SECURITY_TYPES"

    chosen = sorted(
        matching,
        key=lambda r: (
            _first(r, "identity_usable_after", "usable_after", "filed"),
            _first(r, "identity_accession", "accession"),
            _first(r, "identity_source_sha256", "source_sha256"),
        ),
    )[-1]
    if not types:
        return "UNCLASSIFIED", chosen, "SECURITY_TYPE_UNRESOLVED"
    if "AMBIGUOUS" in explicit:
        return "AMBIGUOUS", None, "EXPLICIT_AMBIGUITY"
    if "UNCLASSIFIED" in explicit:
        return "UNCLASSIFIED", chosen, "EXPLICIT_UNCLASSIFIED"
    if "NO_AUTHORITY" in explicit:
        return "NO_AUTHORITY", None, "EXPLICIT_NO_AUTHORITY"
    return "RESOLVED", chosen, ""


def build_ledger(
    source_holdings: Path,
    adjudications: Path,
    output_dir: Path,
    *,
    target_year: int = TARGET_YEAR,
) -> dict:
    source_rows = read_csv(source_holdings)
    candidate_rows = read_csv(adjudications)

    normalized_sources: list[tuple[str, dict[str, str]]] = []
    seen_source_ids: set[str] = set()
    duplicate_source_ids: set[str] = set()
    for ordinal, row in enumerate(source_rows, 1):
        sid = _source_row_id(row, ordinal)
        if sid in seen_source_ids:
            duplicate_source_ids.add(sid)
        seen_source_ids.add(sid)
        normalized_sources.append((sid, row))

    candidates_by_id: dict[str, list[dict[str, str]]] = defaultdict(list)
    unknown_candidate_ids: set[str] = set()
    source_id_set = {sid for sid, _ in normalized_sources}
    for row in candidate_rows:
        sid = _first(row, "source_row_id", "row_id", "source_id", "holding_id")
        if not sid:
            continue
        if sid not in source_id_set:
            unknown_candidate_ids.add(sid)
            continue
        candidates_by_id[sid].append(row)

    ledger: list[dict[str, str]] = []
    for sid, source in normalized_sources:
        status, chosen, reason = _select_candidate(candidates_by_id.get(sid, []))
        chosen = chosen or {}
        decision_session = _first(source, "decision_session", "effective_date", "membership_date")
        ledger.append({
            "target_year": str(target_year),
            "source_row_id": sid,
            "source_name": _first(source, "source_name", "company_name", "issuer_name", "name", "company"),
            "source_ticker": _norm_ticker(_first(source, "source_ticker", "ticker", "symbol")),
            "membership_authority": _first(source, "membership_authority", "authority"),
            "membership_source_url": _first(source, "membership_source_url", "source_url"),
            "membership_source_member": _first(source, "membership_source_member", "source_member"),
            "membership_source_sha256": _first(source, "membership_source_sha256", "source_sha256").lower(),
            "decision_session": decision_session,
            "resolution_status": status,
            "resolved_ticker": _norm_ticker(_first(chosen, "resolved_ticker", "ticker")),
            "security_id": _first(chosen, "security_id"),
            "issuer_cik": _norm_cik(_first(chosen, "issuer_cik", "candidate_cik", "cik", "source_cik")),
            "security_type": _candidate_type(chosen),
            "identity_authority": _first(chosen, "identity_authority", "form_authority", "authority"),
            "identity_form": _first(chosen, "identity_form", "form"),
            "identity_accession": _first(chosen, "identity_accession", "accession"),
            "identity_filed": _first(chosen, "identity_filed", "filed"),
            "identity_usable_after": _first(chosen, "identity_usable_after", "usable_after", "filed"),
            "identity_source_url": _first(chosen, "identity_source_url", "source_url"),
            "identity_source_member": _first(chosen, "identity_source_member", "source_member"),
            "identity_source_sha256": _first(chosen, "identity_source_sha256", "source_sha256").lower(),
            "reason_code": reason or _first(chosen, "reason_code", "reason"),
        })

    ledger.sort(key=lambda r: r["source_row_id"])
    output_dir.mkdir(parents=True, exist_ok=True)
    ledger_path = output_dir / "2007_resolution_ledger.csv.gz"
    write_gzip_csv(ledger_path, LEDGER_FIELDS, ledger)

    counts = Counter(row["resolution_status"] for row in ledger)
    summary = {
        "schema": SCHEMA,
        "stage": "BUILD",
        "status": "PASS" if not duplicate_source_ids and not unknown_candidate_ids else "REVIEW_REQUIRED",
        "target_year": target_year,
        "source_holdings_sha256": sha256_file(source_holdings),
        "adjudications_sha256": sha256_file(adjudications),
        "source_rows": len(source_rows),
        "ledger_rows": len(ledger),
        "candidate_rows": len(candidate_rows),
        "duplicate_source_ids": sorted(duplicate_source_ids),
        "unknown_adjudication_source_ids": sorted(unknown_candidate_ids),
        "resolution_counts": {k: counts.get(k, 0) for k in sorted(TERMINAL_STATUSES)},
        "ledger_sha256": sha256_file(ledger_path),
    }
    (output_dir / "2007_build_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_sha256s(output_dir)
    return summary


def _evidence_failure(
    evidence_root: Path,
    member: str,
    expected_sha256: str,
    *,
    label: str,
) -> str:
    member = (member or "").strip()
    expected_sha256 = (expected_sha256 or "").strip().lower()
    if not member or not expected_sha256:
        return f"{label}:MISSING_EVIDENCE_REFERENCE"
    candidate = (evidence_root / member).resolve()
    root = evidence_root.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return f"{label}:EVIDENCE_PATH_ESCAPE"
    if not candidate.is_file():
        return f"{label}:EVIDENCE_FILE_MISSING"
    if sha256_file(candidate) != expected_sha256:
        return f"{label}:EVIDENCE_HASH_MISMATCH"
    return ""


def certify_ledger(
    ledger_path: Path,
    evidence_root: Path,
    output_dir: Path,
    *,
    expected_rows: int = EXPECTED_ROWS,
    target_year: int = TARGET_YEAR,
) -> dict:
    rows = read_csv(ledger_path)
    diagnostics: list[dict[str, str]] = []
    source_ids = [r.get("source_row_id", "").strip() for r in rows]
    duplicate_source_ids = sorted(k for k, n in Counter(source_ids).items() if k and n > 1)

    status_counts = Counter((r.get("resolution_status") or "").strip().upper() for r in rows)
    invalid_status_rows = sum(1 for r in rows if (r.get("resolution_status") or "").strip().upper() not in TERMINAL_STATUSES)
    target_year_failures = 0
    temporal_failures = 0
    membership_evidence_failures = 0
    identity_evidence_failures = 0
    resolved_field_failures = 0
    bad_decision_sessions = 0
    security_assignments: dict[tuple[str, str], list[str]] = defaultdict(list)

    for row in rows:
        sid = (row.get("source_row_id") or "").strip()
        failures: list[str] = []
        if (row.get("target_year") or "").strip() != str(target_year):
            target_year_failures += 1
            failures.append("TARGET_YEAR_MISMATCH")

        decision = _parse_iso(row.get("decision_session", ""))
        if decision is None or decision.year != target_year:
            bad_decision_sessions += 1
            failures.append("INVALID_2007_DECISION_SESSION")

        mf = _evidence_failure(
            evidence_root,
            row.get("membership_source_member", ""),
            row.get("membership_source_sha256", ""),
            label="MEMBERSHIP",
        )
        if mf:
            membership_evidence_failures += 1
            failures.append(mf)

        status = (row.get("resolution_status") or "").strip().upper()
        if status == "RESOLVED":
            required = [
                row.get("resolved_ticker", ""),
                row.get("security_id", ""),
                row.get("security_type", ""),
                row.get("identity_authority", ""),
                row.get("identity_source_member", ""),
                row.get("identity_source_sha256", ""),
            ]
            if not all((v or "").strip() for v in required) or _norm_type(row.get("security_type", "")) in UNKNOWN_TYPE:
                resolved_field_failures += 1
                failures.append("INCOMPLETE_RESOLVED_IDENTITY")

            filed = _parse_iso(row.get("identity_filed", ""))
            usable = _parse_iso(row.get("identity_usable_after", ""))
            if decision is None or usable is None or not (usable < decision):
                temporal_failures += 1
                failures.append("IDENTITY_NOT_STRICT_PRIOR")
            elif filed is not None and filed > usable:
                temporal_failures += 1
                failures.append("FILED_AFTER_USABLE_AFTER")

            ef = _evidence_failure(
                evidence_root,
                row.get("identity_source_member", ""),
                row.get("identity_source_sha256", ""),
                label="IDENTITY",
            )
            if ef:
                identity_evidence_failures += 1
                failures.append(ef)

            security_id = (row.get("security_id") or "").strip()
            if security_id and decision is not None:
                security_assignments[(security_id, decision.isoformat())].append(sid)

        if failures:
            diagnostics.append({"source_row_id": sid, "failures": ";".join(failures)})

    duplicate_security_assignments = [
        {"security_id": key[0], "decision_session": key[1], "source_row_ids": sorted(ids)}
        for key, ids in sorted(security_assignments.items())
        if len(set(ids)) > 1
    ]

    blockers = {
        "row_count_mismatch": len(rows) != expected_rows,
        "duplicate_source_ids": bool(duplicate_source_ids),
        "invalid_status_rows": invalid_status_rows,
        "ambiguous_rows": status_counts.get("AMBIGUOUS", 0),
        "unclassified_rows": status_counts.get("UNCLASSIFIED", 0),
        "no_authority_rows": status_counts.get("NO_AUTHORITY", 0),
        "conflict_rows": status_counts.get("CONFLICT", 0),
        "unresolved_count": len(rows) - status_counts.get("RESOLVED", 0),
        "target_year_failures": target_year_failures,
        "bad_decision_sessions": bad_decision_sessions,
        "resolved_field_failures": resolved_field_failures,
        "temporal_failures": temporal_failures,
        "membership_evidence_failures": membership_evidence_failures,
        "identity_evidence_failures": identity_evidence_failures,
        "duplicate_security_assignments": len(duplicate_security_assignments),
    }
    accepted = (
        len(rows) == expected_rows
        and status_counts.get("RESOLVED", 0) == expected_rows
        and not any(bool(v) for v in blockers.values())
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    diagnostics_path = output_dir / "2007_closure_diagnostics.csv.gz"
    write_gzip_csv(diagnostics_path, ["source_row_id", "failures"], diagnostics)

    summary = {
        "schema": SCHEMA,
        "stage": "CERTIFY",
        "status": "ACCEPTED" if accepted else "REVIEW_REQUIRED",
        "target_year": target_year,
        "expected_rows": expected_rows,
        "ledger_rows": len(rows),
        "resolved_rows": status_counts.get("RESOLVED", 0),
        "ambiguous_rows": status_counts.get("AMBIGUOUS", 0),
        "unclassified_rows": status_counts.get("UNCLASSIFIED", 0),
        "no_authority_rows": status_counts.get("NO_AUTHORITY", 0),
        "conflict_rows": status_counts.get("CONFLICT", 0),
        "duplicate_source_ids": duplicate_source_ids,
        "duplicate_security_assignments": duplicate_security_assignments,
        "blockers": blockers,
        "causal_rule": "identity_usable_after < decision_session",
        "membership_identity_authorities_separate": True,
        "unknown_never_means_ineligible": True,
        "ledger_sha256": sha256_file(ledger_path),
        "diagnostics_sha256": sha256_file(diagnostics_path),
    }

    if accepted:
        accepted_ledger = output_dir / "2007_resolution_ledger.csv.gz"
        write_gzip_csv(accepted_ledger, LEDGER_FIELDS, rows)
        constituents = [
            {
                "source_row_id": r["source_row_id"],
                "source_name": r["source_name"],
                "source_ticker": r["source_ticker"],
                "ticker": r["resolved_ticker"],
                "security_id": r["security_id"],
                "issuer_cik": r["issuer_cik"],
                "security_type": r["security_type"],
                "decision_session": r["decision_session"],
            }
            for r in sorted(rows, key=lambda x: x["source_row_id"])
        ]
        write_gzip_csv(output_dir / "2007_constituents.csv.gz", CONSTITUENT_FIELDS, constituents)

    (output_dir / "2007_acceptance_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    _write_sha256s(output_dir)
    return summary


def _write_sha256s(root: Path) -> None:
    paths = sorted(p for p in root.rglob("*") if p.is_file() and p.name != "SHA256SUMS.txt")
    lines = [f"{sha256_file(p)}  {p.relative_to(root).as_posix()}" for p in paths]
    (root / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _main_build(args: argparse.Namespace) -> int:
    summary = build_ledger(args.source_holdings, args.adjudications, args.output, target_year=args.target_year)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "PASS" else 2


def _main_certify(args: argparse.Namespace) -> int:
    summary = certify_ledger(
        args.ledger,
        args.evidence_root,
        args.output,
        expected_rows=args.expected_rows,
        target_year=args.target_year,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "ACCEPTED" else 2


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build")
    b.add_argument("--source-holdings", type=Path, required=True)
    b.add_argument("--adjudications", type=Path, required=True)
    b.add_argument("--output", type=Path, required=True)
    b.add_argument("--target-year", type=int, default=TARGET_YEAR)
    b.set_defaults(func=_main_build)

    c = sub.add_parser("certify")
    c.add_argument("--ledger", type=Path, required=True)
    c.add_argument("--evidence-root", type=Path, required=True)
    c.add_argument("--output", type=Path, required=True)
    c.add_argument("--expected-rows", type=int, default=EXPECTED_ROWS)
    c.add_argument("--target-year", type=int, default=TARGET_YEAR)
    c.set_defaults(func=_main_certify)

    args = p.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
