#!/usr/bin/env python3
"""Fail-closed authority review and causal allocation for V3 historical metadata candidates.

The V3 miner is evidence-only. This module is the first admission gate: it admits
only evidence that satisfies the already-approved V2 authority contract and maps
uniquely to the canonical ticker episode guard. It never treats missing evidence
as proof of ineligibility and never rewrites the source V2 package.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Sequence

SCHEMA = "backtester.historical-metadata-reconstruction-v3.authority-allocation/1"
IDENTITY_QUALITIES = {
    "SEC_OWNERSHIP_ISSUER_TRADING_SYMBOL_XML",
    "SEC_EXPLICIT_TRADING_SYMBOL_LABEL",
}
TYPE_QUALITY = "CURRENT_FORM_EXACT_TICKER_CLASS_CANDIDATE"
SIC_QUALITIES = {
    "HEADER_SIC_CAUSAL_CIK",
    "HEADER_SIC_SAME_FILING_EXACT_TICKER_BOOTSTRAP",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def norm_ticker(value: object) -> str:
    return str(value or "").strip().upper()


def validate_cik(value: object) -> str:
    text = str(value or "").strip()
    if not text or not text.isdigit() or len(text) > 10 or int(text) <= 0:
        return ""
    return str(int(text)).zfill(10)


def normalize_date(value: object) -> str:
    text = str(value or "").strip()[:10]
    if len(text) == 10 and text[4] == "-" and text[7] == "-" and text.replace("-", "").isdigit():
        return text
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}" if len(digits) >= 8 else ""


def source_url_cik(url: object) -> str:
    text = str(url or "")
    match = re.search(r"/submissions/CIK(\d{10})\.json(?:$|\?)", text, re.I)
    if match:
        return match.group(1)
    match = re.search(r"/Archives/edgar/data/(\d+)(?:/|$)", text, re.I)
    return validate_cik(match.group(1)) if match else ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_gzip_csv(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_gzip_csv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", compresslevel=9, mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=list(fields), lineterminator="\n", extrasaction="ignore")
                writer.writeheader()
                for row in rows:
                    writer.writerow({field: row.get(field, "") for field in fields})


def write_checksums(root: Path) -> None:
    rows = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.name != "SHA256SUMS.txt"):
        rows.append(f"{sha256_file(path)}  {path.relative_to(root).as_posix()}")
    (root / "SHA256SUMS.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")


def observed_ciks(row: Mapping[str, object]) -> set[str]:
    return {
        validate_cik(value)
        for value in str(row.get("observed_ciks") or "").split(";")
        if validate_cik(value)
    }


def load_guard(path: Path) -> dict[str, list[dict[str, str]]]:
    by_ticker: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in read_gzip_csv(path):
        sid = str(row.get("security_id") or "").strip()
        ticker = norm_ticker(row.get("ticker"))
        first = normalize_date(row.get("first_session"))
        last = normalize_date(row.get("last_session"))
        if not sid or not ticker or not first or not last or last < first:
            raise RuntimeError(f"invalid canonical episode guard row: {row}")
        item = dict(row) | {"ticker": ticker, "first_session": first, "last_session": last}
        by_ticker[ticker].append(item)
    for ticker in by_ticker:
        by_ticker[ticker].sort(key=lambda row: (row["first_session"], row["last_session"], row["security_id"]))
    return by_ticker


def prestart_allowed(
    candidate: Mapping[str, object],
    filed: str,
    guard_by_ticker: Mapping[str, Sequence[Mapping[str, str]]],
) -> bool:
    first = str(candidate["first_session"])
    if not filed or filed >= first:
        return False
    low = f"{max(1994, int(first[:4]) - 3)}-01-01"
    if filed < low:
        return False
    ticker = str(candidate["ticker"])
    sid = str(candidate["security_id"])
    own = [row for row in guard_by_ticker.get(ticker, ()) if str(row.get("security_id")) == sid]
    if len(own) != 1:
        raise RuntimeError(f"candidate episode missing/non-unique in canonical guard: {(sid, ticker)}")
    for other in guard_by_ticker.get(ticker, ()):
        if str(other.get("security_id")) == sid:
            continue
        if str(other.get("first_session")) < first and str(other.get("last_session")) >= filed:
            return False
    return True


def allocate_identity_target(
    row: Mapping[str, str],
    candidates_by_ticker: Mapping[str, Sequence[Mapping[str, object]]],
    guard_by_ticker: Mapping[str, Sequence[Mapping[str, str]]],
) -> tuple[str, str, list[str]]:
    ticker = norm_ticker(row.get("ticker"))
    cik = validate_cik(row.get("candidate_cik"))
    filed = normalize_date(row.get("filed"))
    if not ticker or not cik or not filed:
        return "", "invalid_identity_candidate", []
    possible = [
        candidate
        for candidate in candidates_by_ticker.get(ticker, ())
        if not observed_ciks(candidate) or cik in observed_ciks(candidate)
    ]
    inside = [
        candidate
        for candidate in possible
        if str(candidate["first_session"]) <= filed <= str(candidate["last_session"])
    ]
    if inside:
        possible = inside
    else:
        possible = [
            candidate for candidate in possible
            if prestart_allowed(candidate, filed, guard_by_ticker)
        ]
    sids = sorted({str(candidate["security_id"]) for candidate in possible})
    if len(sids) == 1:
        return sids[0], "unique_guard_allocation", sids
    if sids:
        return "", "ambiguous_guard_allocation", sids
    return "", "no_guard_allocation", []


def validate_candidate_row(row: Mapping[str, str], target: Mapping[str, object]) -> None:
    if str(row.get("admission_effect")) != "NONE_CANDIDATE_ONLY":
        raise RuntimeError("V3 authority gate refuses candidate rows with prior admission effect")
    if norm_ticker(row.get("ticker")) != str(target["ticker"]):
        raise RuntimeError(f"candidate ticker drift for {row.get('security_id')}")
    if normalize_date(row.get("first_session")) != str(target["first_session"]):
        raise RuntimeError(f"candidate first-session drift for {row.get('security_id')}")
    if normalize_date(row.get("last_session")) != str(target["last_session"]):
        raise RuntimeError(f"candidate last-session drift for {row.get('security_id')}")
    cik = validate_cik(row.get("candidate_cik"))
    if not cik:
        raise RuntimeError(f"candidate has invalid CIK: {row}")
    source_sha = str(row.get("source_sha256") or "").lower()
    if not SHA256_RE.fullmatch(source_sha):
        raise RuntimeError(f"candidate has invalid source sha256: {row.get('security_id')}")
    url_cik = source_url_cik(row.get("source_url"))
    if url_cik != cik:
        raise RuntimeError(f"candidate source URL CIK mismatch: {url_cik} != {cik}")


def _dedup(rows: Iterable[Mapping[str, object]], keys: Sequence[str]) -> list[dict[str, object]]:
    chosen: dict[tuple[str, ...], dict[str, object]] = {}
    for row in rows:
        key = tuple(str(row.get(field, "")) for field in keys)
        item = dict(row)
        prior = chosen.get(key)
        if prior is not None and prior != item:
            raise RuntimeError(f"conflicting duplicate V3 admission row: {key}")
        chosen[key] = item
    return [chosen[key] for key in sorted(chosen)]


def admit(package_root: Path, candidate_root: Path, output: Path) -> dict:
    timeline_summary = json.loads(
        (package_root / "timeline" / "timeline_coverage.json").read_text(encoding="utf-8")
    )
    candidate_summary = json.loads((candidate_root / "summary.json").read_text(encoding="utf-8"))
    if timeline_summary.get("status") != "PASS":
        raise RuntimeError("V3 admission requires a PASS V2 guarded timeline")
    if (
        candidate_summary.get("status") != "PASS"
        or not candidate_summary.get("candidate_only")
        or candidate_summary.get("admission_effect") != "NONE"
    ):
        raise RuntimeError("V3 candidate artifact is not evidence-only/PASS")
    if int(candidate_summary.get("merged_shards") or 0) != 32:
        raise RuntimeError("V3 admission requires all 32 candidate shards")

    candidate_episode_rows = read_gzip_csv(package_root / "candidates" / "candidate_episodes.csv.gz")
    by_sid: dict[str, dict[str, object]] = {}
    by_ticker: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in candidate_episode_rows:
        sid = str(row.get("security_id") or "")
        ticker = norm_ticker(row.get("ticker"))
        first = normalize_date(row.get("first_session"))
        last = normalize_date(row.get("last_session"))
        item: dict[str, object] = dict(row) | {
            "security_id": sid,
            "ticker": ticker,
            "first_session": first,
            "last_session": last,
        }
        if not sid or sid in by_sid:
            raise RuntimeError(f"invalid/non-unique candidate security_id: {sid}")
        by_sid[sid] = item
        by_ticker[ticker].append(item)

    guard_path = package_root / "guard" / "canonical_ticker_episode_guard.csv.gz"
    guard_by_ticker = load_guard(guard_path)
    for sid, item in by_sid.items():
        matches = [
            row
            for row in guard_by_ticker.get(str(item["ticker"]), ())
            if str(row.get("security_id")) == sid
        ]
        if len(matches) != 1:
            raise RuntimeError(f"candidate not uniquely represented in full canonical guard: {sid}")

    unresolved = read_gzip_csv(package_root / "timeline" / "unresolved_episodes.csv.gz")
    unresolved_by_sid = {str(row["security_id"]): row for row in unresolved}
    if len(unresolved_by_sid) != len(unresolved):
        raise RuntimeError("duplicate unresolved security_id")

    evidence = read_gzip_csv(candidate_root / "candidate_evidence.csv.gz")
    if len(evidence) != int(candidate_summary.get("candidate_rows") or -1):
        raise RuntimeError("V3 candidate row count does not match summary")
    for row in evidence:
        sid = str(row.get("security_id") or "")
        target = by_sid.get(sid)
        if not target or sid not in unresolved_by_sid:
            raise RuntimeError(f"candidate targets unknown/non-unresolved security episode: {sid}")
        validate_candidate_row(row, target)

    # identity_events.csv.gz contains millions of rows. Its first five columns are
    # fixed by the V2 schema and contain no free-text commas, so scan those columns
    # directly instead of materializing the full CSV in memory.
    existing_identity_pairs: set[tuple[str, str]] = set()
    first_identity: dict[tuple[str, str], str] = {}
    identity_path = package_root / "timeline" / "identity_events.csv.gz"
    with gzip.open(identity_path, "rt", encoding="utf-8", newline="") as fh:
        header = next(fh, "").rstrip("\n\r").split(",")
        if header[:5] != ["security_id", "ticker", "filed", "usable_after", "cik"]:
            raise RuntimeError(f"unexpected V2 identity event prefix: {header[:5]}")
        for line in fh:
            parts = line.split(",", 5)
            if len(parts) < 5:
                raise RuntimeError("malformed V2 identity event row")
            sid, _ticker, filed_raw, _usable_after, cik_raw = parts[:5]
            cik = validate_cik(cik_raw)
            filed = normalize_date(filed_raw)
            if sid and cik:
                existing_identity_pairs.add((sid, cik))
                if filed:
                    first_identity[(sid, cik)] = min(first_identity.get((sid, cik), filed), filed)

    authorized_identity: list[dict[str, object]] = []
    guard_review: list[dict[str, object]] = []
    same_filing_identity_keys: set[tuple[str, str, str, str, str]] = set()
    for row in evidence:
        if (
            row.get("candidate_kind") != "IDENTITY_EXACT_TICKER"
            or row.get("candidate_quality") not in IDENTITY_QUALITIES
        ):
            continue
        target_sid = str(row["security_id"])
        mapped_sid, allocation, possible = allocate_identity_target(row, by_ticker, guard_by_ticker)
        if mapped_sid != target_sid:
            guard_review.append({
                "target_security_id": target_sid,
                "ticker": norm_ticker(row.get("ticker")),
                "filed": normalize_date(row.get("filed")),
                "candidate_cik": validate_cik(row.get("candidate_cik")),
                "candidate_quality": row.get("candidate_quality", ""),
                "mapped_security_id": mapped_sid,
                "possible_security_ids": ";".join(possible),
                "reason": (
                    "candidate_maps_to_different_canonical_episode"
                    if mapped_sid else allocation
                ),
                "accession": row.get("accession", ""),
                "source_url": row.get("source_url", ""),
                "source_sha256": row.get("source_sha256", ""),
                "artifact_member": row.get("artifact_member", ""),
            })
            continue
        filed = normalize_date(row.get("filed"))
        cik = validate_cik(row.get("candidate_cik"))
        unresolved_reasons = set(
            str(unresolved_by_sid[target_sid].get("reasons") or "").split(";")
        )
        event = {
            "security_id": target_sid,
            "ticker": norm_ticker(row.get("ticker")),
            "filed": filed,
            "usable_after": filed,
            "cik": cik,
            "sec_symbol": norm_ticker(row.get("ticker")),
            "accession": row.get("accession", ""),
            "document_type": row.get("form", ""),
            "source_kind": "SEC_V3_EXACT_HISTORICAL_TICKER_AUTHORITY",
            "authority": row.get("candidate_quality", ""),
            "cik_prior_authority": row.get("cik_authority", ""),
            "source_url": row.get("source_url", ""),
            "source_sha256": row.get("source_sha256", ""),
            "artifact_member": row.get("artifact_member", ""),
        }
        if "no_unambiguous_historical_identity_proof" in unresolved_reasons:
            authorized_identity.append(event)
        same_filing_identity_keys.add((
            target_sid,
            cik,
            filed,
            str(row.get("accession") or ""),
            str(row.get("source_sha256") or ""),
        ))

    authorized_identity = _dedup(
        authorized_identity,
        ("security_id", "cik", "filed", "accession", "source_sha256"),
    )
    new_identity_pairs = {(str(row["security_id"]), str(row["cik"])) for row in authorized_identity}
    for row in authorized_identity:
        key = (str(row["security_id"]), str(row["cik"]))
        filed = str(row["filed"])
        first_identity[key] = min(first_identity.get(key, filed), filed)

    type_candidates: list[dict[str, object]] = []
    for row in evidence:
        if row.get("candidate_kind") != "SECURITY_TYPE_EXACT_TICKER_CLASS":
            continue
        if row.get("candidate_quality") != TYPE_QUALITY:
            continue
        classification = str(row.get("classification") or "")
        if classification not in {"common", "non_common"}:
            continue
        sid = str(row["security_id"])
        if "no_admitted_security_type_evidence" not in set(
            str(unresolved_by_sid[sid].get("reasons") or "").split(";")
        ):
            continue
        filed = normalize_date(row.get("filed"))
        cik = validate_cik(row.get("candidate_cik"))
        source_sha = str(row.get("source_sha256") or "")
        key = (sid, cik, filed, str(row.get("accession") or ""), source_sha)
        if key not in same_filing_identity_keys:
            continue
        type_candidates.append({
            "security_id": sid,
            "ticker": norm_ticker(row.get("ticker")),
            "filed": filed,
            "usable_after": filed,
            "cik": cik,
            "sec_symbol": norm_ticker(row.get("ticker")),
            "accession": row.get("accession", ""),
            "classification": classification,
            "security_title_evidence": row.get("evidence_excerpt", ""),
            "authority": "SEC_V3_CURRENT_APPROVED_FORM_SAME_FILING_EXACT_TICKER_AND_CLASS",
            "document_type": row.get("form", ""),
            "source_url": row.get("source_url", ""),
            "source_sha256": source_sha,
            "artifact_member": row.get("artifact_member", ""),
        })

    type_candidates = _dedup(
        type_candidates,
        ("security_id", "filed", "cik", "accession", "classification", "source_sha256"),
    )
    grouped_types: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in type_candidates:
        grouped_types[(str(row["security_id"]), str(row["usable_after"]))].append(row)
    type_conflicts: list[dict[str, object]] = []
    authorized_types: list[dict[str, object]] = []
    for (sid, usable_after), rows in sorted(grouped_types.items()):
        classes = {str(row["classification"]) for row in rows}
        if len(classes) > 1:
            type_conflicts.append({
                "security_id": sid,
                "usable_after": usable_after,
                "classifications": ";".join(sorted(classes)),
                "reason": "conflicting_v3_security_type_evidence_same_usable_date",
            })
        else:
            authorized_types.extend(rows)

    identity_pairs = existing_identity_pairs | new_identity_pairs
    authorized_sic: list[dict[str, object]] = []
    for row in evidence:
        if row.get("candidate_kind") != "SIC_HEADER" or row.get("candidate_quality") not in SIC_QUALITIES:
            continue
        sid = str(row["security_id"])
        if "no_admitted_sic_evidence" not in set(
            str(unresolved_by_sid[sid].get("reasons") or "").split(";")
        ):
            continue
        cik = validate_cik(row.get("candidate_cik"))
        filed = normalize_date(row.get("filed"))
        sic_digits = "".join(ch for ch in str(row.get("sic") or "") if ch.isdigit())
        if not filed or not (3 <= len(sic_digits) <= 4) or (sid, cik) not in identity_pairs:
            continue
        if row.get("cik_authority") == "DISCOVERY_ONLY_HINT":
            proof_key = (
                sid,
                cik,
                filed,
                str(row.get("accession") or ""),
                str(row.get("source_sha256") or ""),
            )
            if proof_key not in same_filing_identity_keys:
                continue
        identity_filed = first_identity.get((sid, cik))
        if not identity_filed:
            continue
        authorized_sic.append({
            "security_id": sid,
            "ticker": norm_ticker(row.get("ticker")),
            "filed": filed,
            "usable_after": max(filed, identity_filed),
            "identity_proof_filed": identity_filed,
            "cik": cik,
            "sic": sic_digits.zfill(4),
            "source_kind": "SEC_V3_COMPLETE_SUBMISSION_HEADER_SIC",
            "authority": row.get("candidate_quality", ""),
            "accession": row.get("accession", ""),
            "source_url": row.get("source_url", ""),
            "source_sha256": row.get("source_sha256", ""),
            "artifact_member": row.get("artifact_member", ""),
        })
    authorized_sic = _dedup(
        authorized_sic,
        ("security_id", "filed", "cik", "sic", "usable_after", "source_sha256"),
    )

    identity_sids = {str(row["security_id"]) for row in authorized_identity}
    type_sids = {str(row["security_id"]) for row in authorized_types}
    sic_sids = {str(row["security_id"]) for row in authorized_sic}
    conflict_sids = {str(row["security_id"]) for row in type_conflicts}
    unresolved_after: list[dict[str, object]] = []
    resolved_sids: set[str] = set()
    for row in unresolved:
        sid = str(row["security_id"])
        reasons = [value for value in str(row.get("reasons") or "").split(";") if value]
        if sid in identity_sids:
            reasons = [value for value in reasons if value != "no_unambiguous_historical_identity_proof"]
        if sid in type_sids and sid not in conflict_sids:
            reasons = [value for value in reasons if value != "no_admitted_security_type_evidence"]
        if sid in sic_sids:
            reasons = [value for value in reasons if value != "no_admitted_sic_evidence"]
        if sid in conflict_sids and "security_type_conflict" not in reasons:
            reasons.append("security_type_conflict")
        if reasons:
            unresolved_after.append(dict(row) | {"reasons": ";".join(reasons)})
        else:
            resolved_sids.add(sid)

    output.mkdir(parents=True, exist_ok=True)
    write_gzip_csv(output / "identity_events_v3.csv.gz", [
        "security_id", "ticker", "filed", "usable_after", "cik", "sec_symbol", "accession",
        "document_type", "source_kind", "authority", "cik_prior_authority", "source_url",
        "source_sha256", "artifact_member",
    ], authorized_identity)
    write_gzip_csv(output / "security_type_events_v3.csv.gz", [
        "security_id", "ticker", "filed", "usable_after", "cik", "sec_symbol", "accession",
        "classification", "security_title_evidence", "authority", "document_type", "source_url",
        "source_sha256", "artifact_member",
    ], authorized_types)
    write_gzip_csv(output / "sic_events_v3.csv.gz", [
        "security_id", "ticker", "filed", "usable_after", "identity_proof_filed", "cik", "sic",
        "source_kind", "authority", "accession", "source_url", "source_sha256", "artifact_member",
    ], authorized_sic)
    write_gzip_csv(output / "identity_guard_review.csv.gz", [
        "target_security_id", "ticker", "filed", "candidate_cik", "candidate_quality",
        "mapped_security_id", "possible_security_ids", "reason", "accession", "source_url",
        "source_sha256", "artifact_member",
    ], _dedup(
        guard_review,
        ("target_security_id", "candidate_cik", "filed", "accession", "source_sha256", "reason", "mapped_security_id"),
    ))
    write_gzip_csv(output / "security_type_conflicts_v3.csv.gz", [
        "security_id", "usable_after", "classifications", "reason",
    ], type_conflicts)
    unresolved_fields = list(unresolved[0]) if unresolved else [
        "security_id", "ticker", "first_session", "last_session", "observations",
        "unknown_type_observations", "missing_sector_observations", "observed_ciks", "reasons",
    ]
    write_gzip_csv(output / "unresolved_episodes_after_v3.csv.gz", unresolved_fields, unresolved_after)

    guard_review_rows = read_gzip_csv(output / "identity_guard_review.csv.gz")
    guard_reason_counts: dict[str, int] = defaultdict(int)
    guard_reason_episodes: dict[str, set[str]] = defaultdict(set)
    for row in guard_review_rows:
        reason = str(row.get("reason") or "")
        guard_reason_counts[reason] += 1
        guard_reason_episodes[reason].add(str(row.get("target_security_id") or ""))
    unresolved_observations_before = sum(int(row.get("observations") or 0) for row in unresolved)
    unresolved_observations_after = sum(int(row.get("observations") or 0) for row in unresolved_after)
    summary = {
        "schema": SCHEMA,
        "status": "PASS" if not type_conflicts else "PARTIAL",
        "admission_status": "READY" if not unresolved_after and not type_conflicts else "REVIEW_REQUIRED",
        "candidate_only_input": True,
        "admission_effect": "AUTHORITATIVE_OVERLAY_ONLY",
        "causal_rule": "filed/usable_after < decision_session",
        "baseline_unresolved_episode_records": len(unresolved),
        "unresolved_episode_records_after_v3": len(unresolved_after),
        "fully_resolved_episode_delta": len(resolved_sids),
        "baseline_unresolved_observations": unresolved_observations_before,
        "unresolved_observations_after_v3": unresolved_observations_after,
        "fully_resolved_observation_delta": unresolved_observations_before - unresolved_observations_after,
        "unknown_type_observations_after_v3": sum(
            int(row.get("unknown_type_observations") or 0) for row in unresolved_after
        ),
        "missing_sector_observations_after_v3": sum(
            int(row.get("missing_sector_observations") or 0) for row in unresolved_after
        ),
        "authorized_identity_events": len(authorized_identity),
        "authorized_identity_episodes": len(identity_sids),
        "authorized_security_type_events": len(authorized_types),
        "authorized_security_type_episodes": len(type_sids),
        "authorized_sic_events": len(authorized_sic),
        "authorized_sic_episodes": len(sic_sids),
        "identity_guard_review_rows": len(guard_review_rows),
        "identity_guard_review_episodes": len({
            str(row.get("target_security_id") or "") for row in guard_review_rows
        }),
        "identity_guard_review_reasons": dict(sorted(guard_reason_counts.items())),
        "identity_guard_review_episode_counts_by_reason": {
            key: len(value) for key, value in sorted(guard_reason_episodes.items())
        },
        "security_type_conflicts": len(type_conflicts),
        "extended_form_type_candidates_admitted": 0,
        "ownership_form_type_candidates_admitted": 0,
        "candidate_evidence_sha256": sha256_file(candidate_root / "candidate_evidence.csv.gz"),
        "canonical_episode_guard_sha256": sha256_file(guard_path),
        "baseline_unresolved_sha256": sha256_file(
            package_root / "timeline" / "unresolved_episodes.csv.gz"
        ),
        "policy": {
            "unknown_never_means_ineligible": True,
            "ticker_aliases_disabled": True,
            "identity_requires_exact_historical_ticker_proof_and_unique_guard_allocation": True,
            "type_requires_current_approved_form_and_same_filing_exact_ticker_identity": True,
            "sic_requires_existing_or_new_causal_cik_identity": True,
            "candidate_target_security_id_is_not_authority": True,
            "guard_mismatch_never_retargets_or_admits_automatically": True,
        },
        "next_gate": (
            "review canonical identity episode topology for guard mismatches/unallocatable identity evidence; "
            "then pursue additional historical authority for remaining unresolved episodes"
            if unresolved_after else "integrate overlay into rebuilt canonical PIT package"
        ),
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    lines = [
        "# V3 historical metadata authority/allocation",
        "",
        f"Baseline unresolved episodes: **{len(unresolved):,}**",
        f"Fully resolved by admitted V3 evidence: **{len(resolved_sids):,}**",
        f"Remaining unresolved episodes: **{len(unresolved_after):,}**",
        "",
        f"Authorized identity episodes: **{len(identity_sids):,}**",
        f"Authorized security-type episodes: **{len(type_sids):,}**",
        f"Authorized SIC episodes: **{len(sic_sids):,}**",
        f"Identity evidence rows requiring guard/topology review: **{len(guard_review_rows):,}**",
        "",
        "Unknown evidence remains unresolved; it is never converted to ineligible.",
    ]
    (output / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_checksums(output)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = admit(args.package_root, args.candidate_root, args.output)
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
