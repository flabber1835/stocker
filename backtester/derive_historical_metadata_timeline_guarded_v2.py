#!/usr/bin/env python3
"""Derive the V2 historical metadata timeline with full-canonical episode guards."""
from __future__ import annotations

import argparse
import csv
import gzip
import json
from collections import defaultdict
from pathlib import Path
from typing import Mapping, Sequence

from backtester import historical_metadata_reconstruction_v2 as base

SCHEMA = "backtester.historical-metadata-reconstruction-v2.guarded-timeline/1"


def load_guard(path: Path) -> tuple[list[dict[str, str]], dict[str, list[dict[str, str]]]]:
    rows = base.read_gzip_csv(path)
    by_ticker: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        sid = str(row.get("security_id") or "").strip()
        ticker = base.norm_ticker(row.get("ticker"))
        first = str(row.get("first_session") or "")[:10]
        last = str(row.get("last_session") or "")[:10]
        if not sid or not ticker or not first or not last or last < first:
            raise base.ReconstructionError(f"invalid episode-guard row: {row}")
        item = dict(row)
        item["ticker"] = ticker
        item["first_session"] = first
        item["last_session"] = last
        by_ticker[ticker].append(item)
    for ticker in by_ticker:
        by_ticker[ticker].sort(key=lambda row: (row["first_session"], row["last_session"], row["security_id"]))
    return rows, by_ticker


def _candidate_cik_match(candidate: base.CandidateEpisode, cik: str) -> bool:
    return not candidate.observed_ciks or cik in candidate.observed_ciks


def _prestart_allowed(
    candidate: base.CandidateEpisode,
    filed: str,
    guard_by_ticker: Mapping[str, Sequence[Mapping[str, str]]],
) -> bool:
    if not filed or filed >= candidate.first_session:
        return False
    low = f"{max(1994, int(candidate.first_session[:4]) - 3)}-01-01"
    if filed < low:
        return False
    candidate_guard = [
        row for row in guard_by_ticker.get(candidate.ticker, ())
        if str(row.get("security_id")) == candidate.security_id
    ]
    if len(candidate_guard) != 1:
        raise base.ReconstructionError(
            f"candidate episode missing/non-unique in canonical guard: {(candidate.security_id, candidate.ticker)}"
        )
    for other in guard_by_ticker.get(candidate.ticker, ()):
        if str(other.get("security_id")) == candidate.security_id:
            continue
        other_first = str(other.get("first_session") or "")
        other_last = str(other.get("last_session") or "")
        # Any other canonical episode that covers the filing, or begins after the
        # filing but before this candidate begins, makes backward seeding unsafe.
        if other_first < candidate.first_session and other_last >= filed:
            return False
    return True


def allocate_identity_events_guarded(
    candidates: Sequence[base.CandidateEpisode],
    identity_rows: Sequence[Mapping[str, str]],
    guard_by_ticker: Mapping[str, Sequence[Mapping[str, str]]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    by_symbol: dict[str, list[base.CandidateEpisode]] = defaultdict(list)
    for candidate in candidates:
        if candidate.alias_safe or candidate.alias_symbol:
            raise base.ReconstructionError("guarded admission refuses inferred ticker aliases")
        by_symbol[candidate.ticker].append(candidate)

    allocated: list[dict[str, object]] = []
    ambiguous: list[dict[str, object]] = []
    for row in identity_rows:
        symbol = base.norm_ticker(row.get("sec_symbol"))
        cik = base.validate_cik(row.get("cik"))
        filed = base.normalize_date(row.get("filed"))
        if not symbol or not cik or not filed:
            continue
        possible = [
            candidate for candidate in by_symbol.get(symbol, ())
            if _candidate_cik_match(candidate, cik)
        ]
        inside = [
            candidate for candidate in possible
            if candidate.first_session <= filed <= candidate.last_session
        ]
        if inside:
            possible = inside
        else:
            possible = [
                candidate for candidate in possible
                if _prestart_allowed(candidate, filed, guard_by_ticker)
            ]
        if len(possible) == 1:
            candidate = possible[0]
            allocated.append(dict(row) | {
                "security_id": candidate.security_id,
                "ticker": candidate.ticker,
                "alias_used": "false",
                "usable_after": filed,
            })
        elif possible:
            ambiguous.append({
                "filed": filed,
                "sec_symbol": symbol,
                "cik": cik,
                "accession": row.get("accession", ""),
                "candidate_security_ids": ";".join(sorted(candidate.security_id for candidate in possible)),
                "reason": "identity_event_maps_to_multiple_guarded_security_episodes",
            })
    return allocated, ambiguous


def _load_existing_sic(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = {str(x).lower(): str(x) for x in (reader.fieldnames or [])}
        filed_col = next((fields[x] for x in ("filed", "filing_date", "date") if x in fields), None)
        cik_col = next((fields[x] for x in ("cik", "issuer_cik") if x in fields), None)
        sic_col = next((fields[x] for x in ("sic", "sic_code") if x in fields), None)
        if not filed_col or not cik_col or not sic_col:
            raise base.ReconstructionError(f"cannot identify SIC columns in {path}")
        for row in reader:
            filed = base.normalize_date(row.get(filed_col, ""))
            cik = base.validate_cik(row.get(cik_col, ""))
            sic_digits = "".join(ch for ch in str(row.get(sic_col, "")) if ch.isdigit())
            if filed and cik and 3 <= len(sic_digits) <= 4:
                rows.append({
                    "filed": filed,
                    "cik": cik,
                    "sic": sic_digits.zfill(4),
                    "source_kind": "RETAINED_SEC_SIC_DATASET",
                    "accession": "",
                    "source_url": "",
                    "source_sha256": "",
                })
    return rows


def _web_rows(web_root: Path | None, name: str) -> list[dict[str, str]]:
    if not web_root:
        return []
    path = web_root / name
    return base.read_gzip_csv(path) if path.exists() else []


def _dedup(rows: Sequence[Mapping[str, object]], keys: Sequence[str]) -> list[dict[str, object]]:
    chosen: dict[tuple[str, ...], dict[str, object]] = {}
    for row in rows:
        key = tuple(str(row.get(k, "")) for k in keys)
        chosen.setdefault(key, dict(row))
    return [chosen[key] for key in sorted(chosen)]


def derive(
    candidates_path: Path,
    episode_guard_path: Path,
    bulk_dir: Path,
    existing_sic_path: Path,
    output: Path,
    web_root: Path | None = None,
) -> dict:
    candidates = base.load_candidates(candidates_path)
    _guard_rows, guard_by_ticker = load_guard(episode_guard_path)
    for candidate in candidates:
        if candidate.alias_safe or candidate.alias_symbol:
            raise base.ReconstructionError("guarded derive refuses inferred ticker aliases")
        matches = [
            row for row in guard_by_ticker.get(candidate.ticker, ())
            if str(row.get("security_id")) == candidate.security_id
        ]
        if len(matches) != 1:
            raise base.ReconstructionError(
                f"candidate not uniquely represented in full canonical episode guard: {(candidate.security_id, candidate.ticker)}"
            )

    bulk_types = base.read_gzip_csv(bulk_dir / "bulk_security_type_sources.csv.gz")
    if any(str(row.get("classification")) in {"common", "non_common"} for row in bulk_types):
        raise base.ReconstructionError("Form 3/4/5 type evidence was not demoted before guarded derive")

    identity_raw = base.read_gzip_csv(bulk_dir / "bulk_identity_sources.csv.gz") + _web_rows(
        web_root, "web_identity_sources.csv.gz"
    )
    type_raw = bulk_types + _web_rows(web_root, "web_security_type_sources.csv.gz")
    allocated_identity, ambiguous_identity = allocate_identity_events_guarded(
        candidates, identity_raw, guard_by_ticker
    )

    identity_by_accession_episode = {
        (str(row.get("accession", "")), str(row.get("security_id", "")), str(row.get("cik", "")), str(row.get("source_sha256", "")))
        for row in allocated_identity
    }
    type_allocated: list[dict[str, object]] = []
    candidate_by_sid = {candidate.security_id: candidate for candidate in candidates}
    for row in type_raw:
        classification = str(row.get("classification") or "unknown")
        if classification not in {"common", "non_common"}:
            continue
        accession = str(row.get("accession") or "")
        cik = base.validate_cik(row.get("cik"))
        symbol = base.norm_ticker(row.get("sec_symbol"))
        source_sha = str(row.get("source_sha256") or "")
        matches = []
        for candidate in candidates:
            if candidate.ticker != symbol or not _candidate_cik_match(candidate, cik):
                continue
            key_exact = (accession, candidate.security_id, cik, source_sha)
            key_no_source = (accession, candidate.security_id, cik, "")
            if key_exact in identity_by_accession_episode or key_no_source in identity_by_accession_episode:
                matches.append(candidate)
        if len(matches) != 1:
            continue
        candidate = matches[0]
        filed = base.normalize_date(row.get("filed"))
        if not filed:
            continue
        type_allocated.append(dict(row) | {
            "security_id": candidate.security_id,
            "ticker": candidate.ticker,
            "usable_after": filed,
            "alias_used": "false",
        })

    sic_raw = _load_existing_sic(existing_sic_path) + _web_rows(web_root, "web_sic_sources.csv.gz")
    first_identity: dict[tuple[str, str], str] = {}
    for row in allocated_identity:
        key = (str(row["security_id"]), str(row["cik"]))
        filed = base.normalize_date(row["filed"])
        if filed:
            first_identity[key] = min(first_identity.get(key, filed), filed)
    sic_by_cik: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in sic_raw:
        cik = base.validate_cik(row.get("cik"))
        if cik:
            sic_by_cik[cik].append(row)
    sic_allocated: list[dict[str, object]] = []
    for (sid, cik), identity_filed in sorted(first_identity.items()):
        candidate = candidate_by_sid[sid]
        for row in sic_by_cik.get(cik, ()):
            filed = base.normalize_date(row.get("filed"))
            if not filed:
                continue
            sic_allocated.append(dict(row) | {
                "security_id": sid,
                "ticker": candidate.ticker,
                "usable_after": max(filed, identity_filed),
                "identity_proof_filed": identity_filed,
            })

    allocated_identity = _dedup(allocated_identity, ("security_id", "filed", "cik", "accession", "sec_symbol", "source_sha256"))
    type_allocated = _dedup(type_allocated, ("security_id", "filed", "cik", "accession", "classification", "source_sha256"))
    sic_allocated = _dedup(sic_allocated, ("security_id", "filed", "cik", "sic", "usable_after", "source_sha256"))
    ambiguous_identity = _dedup(ambiguous_identity, ("filed", "sec_symbol", "cik", "accession", "candidate_security_ids"))

    grouped_types: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in type_allocated:
        grouped_types[(str(row["security_id"]), str(row["usable_after"]))].append(row)
    type_conflicts: list[dict[str, object]] = []
    admitted_types: list[dict[str, object]] = []
    for key, rows in sorted(grouped_types.items()):
        classes = {str(row["classification"]) for row in rows}
        if len(classes) > 1:
            type_conflicts.append({
                "security_id": key[0], "usable_after": key[1],
                "classifications": ";".join(sorted(classes)),
                "reason": "conflicting_security_type_evidence_same_usable_date",
            })
        else:
            admitted_types.extend(rows)
    type_allocated = admitted_types

    output.mkdir(parents=True, exist_ok=True)
    base.write_gzip_csv(output / "identity_events.csv.gz", [
        "security_id", "ticker", "filed", "usable_after", "cik", "sec_symbol", "accession",
        "document_type", "source_kind", "alias_used", "archive", "archive_sha256", "source_url", "source_sha256",
    ], allocated_identity)
    base.write_gzip_csv(output / "security_type_events.csv.gz", [
        "security_id", "ticker", "filed", "usable_after", "cik", "sec_symbol", "accession",
        "classification", "security_title_evidence", "authority", "alias_used", "archive", "archive_sha256",
        "source_url", "source_sha256",
    ], type_allocated)
    base.write_gzip_csv(output / "sic_events.csv.gz", [
        "security_id", "ticker", "filed", "usable_after", "identity_proof_filed", "cik", "sic", "source_kind",
        "accession", "source_url", "source_sha256",
    ], sic_allocated)
    base.write_gzip_csv(output / "ambiguous_identity_events.csv.gz", [
        "filed", "sec_symbol", "cik", "accession", "candidate_security_ids", "reason",
    ], ambiguous_identity)
    base.write_gzip_csv(output / "security_type_conflicts.csv.gz", [
        "security_id", "usable_after", "classifications", "reason",
    ], type_conflicts)

    type_sids = {str(row["security_id"]) for row in type_allocated}
    sic_sids = {str(row["security_id"]) for row in sic_allocated}
    identity_sids = {str(row["security_id"]) for row in allocated_identity}
    ambiguous_sids = {
        sid for row in ambiguous_identity
        for sid in str(row.get("candidate_security_ids", "")).split(";") if sid
    }
    conflict_sids = {str(row["security_id"]) for row in type_conflicts}
    unresolved_rows: list[dict[str, object]] = []
    for candidate in candidates:
        reasons: list[str] = []
        if candidate.security_id not in identity_sids:
            reasons.append("no_unambiguous_historical_identity_proof")
        if candidate.unknown_type_observations and candidate.security_id not in type_sids:
            reasons.append("no_admitted_security_type_evidence")
        if candidate.missing_sector_observations and candidate.security_id not in sic_sids:
            reasons.append("no_admitted_sic_evidence")
        if candidate.security_id in ambiguous_sids:
            reasons.append("ambiguous_identity_evidence")
        if candidate.security_id in conflict_sids:
            reasons.append("security_type_conflict")
        if reasons:
            unresolved_rows.append({
                "security_id": candidate.security_id,
                "ticker": candidate.ticker,
                "first_session": candidate.first_session,
                "last_session": candidate.last_session,
                "observations": candidate.observations,
                "unknown_type_observations": candidate.unknown_type_observations,
                "missing_sector_observations": candidate.missing_sector_observations,
                "observed_ciks": ";".join(candidate.observed_ciks),
                "reasons": ";".join(reasons),
            })
    base.write_gzip_csv(output / "unresolved_episodes.csv.gz", [
        "security_id", "ticker", "first_session", "last_session", "observations",
        "unknown_type_observations", "missing_sector_observations", "observed_ciks", "reasons",
    ], unresolved_rows)

    summary = {
        "schema": SCHEMA,
        "status": "PASS" if not type_conflicts and not ambiguous_identity else "PARTIAL",
        "admission_status": "READY" if not unresolved_rows else "REVIEW_REQUIRED",
        "causal_rule": "filed/usable_after < decision_session",
        "ticker_alias_policy": "disabled_without_independent_historical_alias_proof",
        "prestart_identity_rule": "three-year bounded seed with full-canonical ticker-reuse guard",
        "episode_guard_sha256": base.sha256_file(episode_guard_path),
        "identity_events": len(allocated_identity),
        "security_type_events": len(type_allocated),
        "sic_events": len(sic_allocated),
        "ambiguous_identity_events": len(ambiguous_identity),
        "security_type_conflicts": len(type_conflicts),
        "unresolved_episode_records": len(unresolved_rows),
    }
    (output / "timeline_coverage.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    base.write_checksums(output)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--episode-guard", type=Path, required=True)
    parser.add_argument("--bulk", type=Path, required=True)
    parser.add_argument("--existing-sic", type=Path, required=True)
    parser.add_argument("--web", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = derive(args.candidates, args.episode_guard, args.bulk, args.existing_sic, args.output, args.web)
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
