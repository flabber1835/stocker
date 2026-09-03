#!/usr/bin/env python3
"""Rebuild historical metadata episode topology using the corrected strict-PIT identity contract.

This bridge deliberately separates *security identity* from SEC issuer identity:
security episodes come from historical SEP tape continuity and independently causal
terminal/relisting evidence. SEC CIK evidence can describe the issuer attached to
an episode, but cannot manufacture an episode boundary.

The module consumes the authenticated V2/V3 evidence artifacts, remaps them onto a
new guard produced by an exact pinned copy of research/backtester's corrected
strict_pit_metadata.py, and reports the resulting metadata-resolution inventory.
It never edits the frozen V2 package and never turns missing evidence into an
ineligibility decision.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib.util
import io
import json
from bisect import bisect_right
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Sequence

SCHEMA = "backtester.historical-metadata-reconstruction-v3.corrected-identity-topology/1"
IDENTITY_QUALITIES = {
    "SEC_OWNERSHIP_ISSUER_TRADING_SYMBOL_XML",
    "SEC_EXPLICIT_TRADING_SYMBOL_LABEL",
}
TYPE_QUALITY = "CURRENT_FORM_EXACT_TICKER_CLASS_CANDIDATE"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def norm_ticker(value: object) -> str:
    return str(value or "").strip().upper()


def normalize_date(value: object) -> str:
    text = str(value or "").strip()[:10]
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text
    return ""


def validate_cik(value: object) -> str:
    text = str(value or "").strip()
    if not text or not text.isdigit() or len(text) > 10 or int(text) <= 0:
        return ""
    return str(int(text)).zfill(10)


def read_gzip_csv(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def iter_gzip_csv(path: Path):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        yield from csv.DictReader(fh)


def write_gzip_csv(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", compresslevel=9, mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=list(fields), extrasaction="ignore", lineterminator="\n")
                writer.writeheader()
                for row in rows:
                    writer.writerow({field: row.get(field, "") for field in fields})


def write_checksums(root: Path) -> None:
    rows = []
    for path in sorted(p for p in root.rglob("*") if p.is_file() and p.name != "SHA256SUMS.txt"):
        rows.append(f"{sha256_file(path)}  {path.relative_to(root).as_posix()}")
    (root / "SHA256SUMS.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")


def load_corrected_identity_module(path: Path):
    spec = importlib.util.spec_from_file_location("corrected_strict_pit_metadata", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import corrected identity source: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    required = (
        "_price_dates", "_cik_changes", "_changes_as_of", "_terminal_identity_evidence",
        "_identity_boundary_classification", "_sid", "IDENTITY_AUTHORITY",
    )
    missing = [name for name in required if not hasattr(module, name)]
    if missing:
        raise RuntimeError(f"corrected identity source missing API: {missing}")
    return module


def corrected_guard(module, source_root: Path) -> tuple[list[dict[str, object]], dict, list[dict], list[dict]]:
    sharadar_root = source_root / "sharadar"
    cik_path = source_root / "research" / "sentinel-fastgate" / "pit-evidence" / "generated" / "sec_cik_change_events.csv.gz"
    if not cik_path.is_file():
        raise RuntimeError(f"missing corrected CIK evidence: {cik_path}")
    price_dates = module._price_dates(sharadar_root, 1997, 2026)
    _events, all_changes = module._cik_changes(cik_path)
    changes = module._changes_as_of(all_changes, "2026-12-31")
    vendor, exact = module._terminal_identity_evidence(sharadar_root)
    starts_by_ticker, boundary_records, blocking, audit = module._identity_boundary_classification(
        price_dates=price_dates,
        changes=changes,
        vendor_terminals=vendor,
        exact_terminals=exact,
    )

    guard: list[dict[str, object]] = []
    for ticker, observed in sorted(price_dates.items()):
        observed = tuple(sorted(set(str(value) for value in observed)))
        if not observed:
            continue
        starts = sorted(set(starts_by_ticker.get(ticker, {observed[0]})))
        if not starts or starts[0] != observed[0]:
            raise RuntimeError(f"corrected episode starts omit first tape observation: {ticker}")
        observed_index = {session: index for index, session in enumerate(observed)}
        if any(start not in observed_index for start in starts):
            raise RuntimeError(f"corrected episode start is not on price tape: {ticker}")
        for episode, start in enumerate(starts):
            start_index = observed_index[start]
            if episode + 1 < len(starts):
                next_index = observed_index[starts[episode + 1]]
                end_index = next_index - 1
            else:
                end_index = len(observed) - 1
            if end_index < start_index:
                raise RuntimeError(f"empty corrected episode: {(ticker, start)}")
            guard.append({
                "security_id": module._sid(ticker, observed[0], episode),
                "ticker": ticker,
                "first_session": start,
                "last_session": observed[end_index],
                "observations": end_index - start_index + 1,
                "episode": episode,
                "identity_authority": module.IDENTITY_AUTHORITY,
            })
    audit = dict(audit) | {
        "corrected_guard_rows": len(guard),
        "corrected_guard_tickers": len({str(row["ticker"]) for row in guard}),
    }
    return guard, audit, boundary_records, blocking


def by_ticker_guard(rows: Sequence[Mapping[str, object]]) -> dict[str, list[dict[str, object]]]:
    result: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        result[norm_ticker(row.get("ticker"))].append(dict(row))
    for ticker in result:
        result[ticker].sort(key=lambda row: (str(row["first_session"]), str(row["last_session"]), str(row["security_id"])))
    return result


def allocate_date(ticker: str, filed: str, guard_by_ticker: Mapping[str, Sequence[Mapping[str, object]]]) -> str:
    """Map dated ticker evidence to one corrected episode, with the V2 3-year prestart guard."""
    ticker = norm_ticker(ticker)
    filed = normalize_date(filed)
    if not ticker or not filed:
        return ""
    episodes = list(guard_by_ticker.get(ticker, ()))
    inside = [
        row for row in episodes
        if str(row["first_session"]) <= filed <= str(row["last_session"])
    ]
    if len(inside) == 1:
        return str(inside[0]["security_id"])
    if len(inside) > 1:
        raise RuntimeError(f"overlapping corrected guard episodes for {(ticker, filed)}")

    possible = []
    for candidate in episodes:
        first = str(candidate["first_session"])
        if filed >= first:
            continue
        low = f"{max(1994, int(first[:4]) - 3)}-01-01"
        if filed < low:
            continue
        blocked = False
        for other in episodes:
            if str(other["security_id"]) == str(candidate["security_id"]):
                continue
            if str(other["first_session"]) < first and str(other["last_session"]) >= filed:
                blocked = True
                break
        if not blocked:
            possible.append(candidate)
    return str(possible[0]["security_id"]) if len(possible) == 1 else ""


def map_interval(
    ticker: str,
    first: str,
    last: str,
    guard_by_ticker: Mapping[str, Sequence[Mapping[str, object]]],
) -> tuple[str, str, list[str]]:
    ticker = norm_ticker(ticker)
    first = normalize_date(first)
    last = normalize_date(last)
    overlaps = [
        row for row in guard_by_ticker.get(ticker, ())
        if not (str(row["last_session"]) < first or last < str(row["first_session"]))
    ]
    ids = [str(row["security_id"]) for row in overlaps]
    containing = [
        row for row in overlaps
        if str(row["first_session"]) <= first and last <= str(row["last_session"])
    ]
    if len(containing) == 1:
        return str(containing[0]["security_id"]), "CONTAINED", ids
    if len(overlaps) > 1:
        return "", "CROSSES_CORRECTED_BOUNDARY", ids
    if len(overlaps) == 1:
        return str(overlaps[0]["security_id"]), "PARTIAL_OVERLAP", ids
    return "", "NO_OVERLAP", []


def main_rebuild(
    *,
    identity_source_root: Path,
    identity_source_sha: str,
    v2_root: Path,
    v3_candidate_root: Path,
    v3_authority_root: Path,
    output: Path,
) -> dict:
    source_file = identity_source_root / "backtester" / "strict_pit_metadata.py"
    module = load_corrected_identity_module(source_file)
    corrected, identity_audit, boundary_records, blocking = corrected_guard(module, identity_source_root)
    corrected_by_ticker = by_ticker_guard(corrected)

    old_guard = read_gzip_csv(v2_root / "guard" / "canonical_ticker_episode_guard.csv.gz")
    old_to_new: dict[str, str] = {}
    topology_rows: list[dict[str, object]] = []
    topology_counts = Counter()
    fragments_per_new = Counter()
    for row in old_guard:
        new_sid, disposition, overlaps = map_interval(
            row.get("ticker", ""), row.get("first_session", ""), row.get("last_session", ""), corrected_by_ticker
        )
        topology_counts[disposition] += 1
        if new_sid:
            old_to_new[str(row["security_id"])] = new_sid
            fragments_per_new[new_sid] += 1
        topology_rows.append({
            "old_security_id": row.get("security_id", ""),
            "ticker": norm_ticker(row.get("ticker")),
            "old_first_session": row.get("first_session", ""),
            "old_last_session": row.get("last_session", ""),
            "old_observations": row.get("observations", ""),
            "old_observed_ciks": row.get("observed_ciks", ""),
            "corrected_security_id": new_sid,
            "disposition": disposition,
            "overlapping_corrected_security_ids": ";".join(overlaps),
        })

    candidate_rows = read_gzip_csv(v2_root / "candidates" / "candidate_episodes.csv.gz")
    aggregate: dict[str, dict[str, object]] = {}
    candidate_mapping_anomalies: list[dict[str, object]] = []
    for row in candidate_rows:
        new_sid, disposition, overlaps = map_interval(
            row.get("ticker", ""), row.get("first_session", ""), row.get("last_session", ""), corrected_by_ticker
        )
        if not new_sid or disposition != "CONTAINED":
            candidate_mapping_anomalies.append({
                "old_security_id": row.get("security_id", ""),
                "ticker": row.get("ticker", ""),
                "first_session": row.get("first_session", ""),
                "last_session": row.get("last_session", ""),
                "disposition": disposition,
                "overlapping_corrected_security_ids": ";".join(overlaps),
            })
            continue
        corrected_row = next(
            item for item in corrected_by_ticker[norm_ticker(row.get("ticker"))]
            if str(item["security_id"]) == new_sid
        )
        item = aggregate.setdefault(new_sid, {
            "security_id": new_sid,
            "ticker": corrected_row["ticker"],
            "first_session": corrected_row["first_session"],
            "last_session": corrected_row["last_session"],
            "observations": 0,
            "unknown_type_observations": 0,
            "missing_sector_observations": 0,
            "old_candidate_fragments": 0,
            "old_security_ids": set(),
            "observed_ciks": set(),
        })
        item["observations"] = int(item["observations"]) + int(row.get("observations") or 0)
        item["unknown_type_observations"] = int(item["unknown_type_observations"]) + int(row.get("unknown_type_observations") or 0)
        item["missing_sector_observations"] = int(item["missing_sector_observations"]) + int(row.get("missing_sector_observations") or 0)
        item["old_candidate_fragments"] = int(item["old_candidate_fragments"]) + 1
        item["old_security_ids"].add(str(row.get("security_id") or ""))
        for cik in str(row.get("observed_ciks") or "").split(";"):
            cik = validate_cik(cik)
            if cik:
                item["observed_ciks"].add(cik)

    if candidate_mapping_anomalies:
        # Counts cannot be conserved if an old candidate interval crosses a new boundary.
        exact_resolution_available = False
    else:
        exact_resolution_available = True

    # Remap already-authoritative V2 identity evidence. This is issuer evidence;
    # it is not used to manufacture corrected security episodes.
    issuer_pairs: set[tuple[str, str]] = set()
    first_issuer: dict[tuple[str, str], str] = {}
    remapped_identity_events = 0
    for row in iter_gzip_csv(v2_root / "timeline" / "identity_events.csv.gz"):
        new_sid = allocate_date(row.get("ticker", ""), row.get("filed", ""), corrected_by_ticker)
        cik = validate_cik(row.get("cik"))
        filed = normalize_date(row.get("filed"))
        if not new_sid or not cik or not filed:
            continue
        issuer_pairs.add((new_sid, cik))
        first_issuer[(new_sid, cik)] = min(first_issuer.get((new_sid, cik), filed), filed)
        remapped_identity_events += 1

    # Remap already-authoritative V2 listed-class evidence.
    type_sids: set[str] = set()
    remapped_v2_type_events = 0
    for row in iter_gzip_csv(v2_root / "timeline" / "security_type_events.csv.gz"):
        new_sid = allocate_date(row.get("ticker", ""), row.get("filed", ""), corrected_by_ticker)
        if new_sid and str(row.get("classification")) in {"common", "non_common"}:
            type_sids.add(new_sid)
            remapped_v2_type_events += 1

    # Remap already-authoritative V2 SIC evidence using the issuer-proof date so
    # the sector row cannot jump across a corrected relisting boundary.
    sic_sids: set[str] = set()
    remapped_v2_sic_events = 0
    for row in iter_gzip_csv(v2_root / "timeline" / "sic_events.csv.gz"):
        evidence_date = row.get("identity_proof_filed") or row.get("usable_after") or row.get("filed")
        new_sid = allocate_date(row.get("ticker", ""), evidence_date, corrected_by_ticker)
        if new_sid and str(row.get("sic") or "").isdigit():
            sic_sids.add(new_sid)
            remapped_v2_sic_events += 1

    # Reallocate all evidence-only V3 candidates against corrected topology.
    v3_rows = read_gzip_csv(v3_candidate_root / "candidate_evidence.csv.gz")
    identity_key_to_sid: dict[tuple[str, str, str, str], str] = {}
    v3_identity_events = 0
    v3_identity_sids: set[str] = set()
    for row in v3_rows:
        if row.get("candidate_kind") != "IDENTITY_EXACT_TICKER" or row.get("candidate_quality") not in IDENTITY_QUALITIES:
            continue
        new_sid = allocate_date(row.get("ticker", ""), row.get("filed", ""), corrected_by_ticker)
        cik = validate_cik(row.get("candidate_cik"))
        filed = normalize_date(row.get("filed"))
        if not new_sid or not cik or not filed:
            continue
        key = (cik, filed, str(row.get("accession") or ""), str(row.get("source_sha256") or ""))
        prior = identity_key_to_sid.get(key)
        if prior is not None and prior != new_sid:
            raise RuntimeError(f"same exact SEC identity source maps to multiple corrected episodes: {key}")
        identity_key_to_sid[key] = new_sid
        issuer_pairs.add((new_sid, cik))
        first_issuer[(new_sid, cik)] = min(first_issuer.get((new_sid, cik), filed), filed)
        v3_identity_sids.add(new_sid)
        v3_identity_events += 1

    v3_type_events = 0
    v3_type_sids: set[str] = set()
    type_conflicts: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in v3_rows:
        if row.get("candidate_kind") != "SECURITY_TYPE_EXACT_TICKER_CLASS" or row.get("candidate_quality") != TYPE_QUALITY:
            continue
        classification = str(row.get("classification") or "")
        if classification not in {"common", "non_common"}:
            continue
        filed = normalize_date(row.get("filed"))
        key = (
            validate_cik(row.get("candidate_cik")), filed,
            str(row.get("accession") or ""), str(row.get("source_sha256") or ""),
        )
        new_sid = identity_key_to_sid.get(key)
        if not new_sid:
            continue
        type_conflicts[(new_sid, filed)].add(classification)
        v3_type_sids.add(new_sid)
        v3_type_events += 1
    conflicting_type_sids = {
        sid for (sid, _filed), values in type_conflicts.items() if len(values) > 1
    }
    type_sids.update(v3_type_sids - conflicting_type_sids)

    v3_sic_events = 0
    v3_sic_sids: set[str] = set()
    for row in v3_rows:
        if row.get("candidate_kind") != "SIC_HEADER":
            continue
        cik = validate_cik(row.get("candidate_cik"))
        filed = normalize_date(row.get("filed"))
        if not cik or not filed:
            continue
        new_sid = allocate_date(row.get("ticker", ""), filed, corrected_by_ticker)
        if not new_sid or (new_sid, cik) not in issuer_pairs:
            continue
        if row.get("cik_authority") == "DISCOVERY_ONLY_HINT":
            key = (cik, filed, str(row.get("accession") or ""), str(row.get("source_sha256") or ""))
            if identity_key_to_sid.get(key) != new_sid:
                continue
        sic_digits = "".join(ch for ch in str(row.get("sic") or "") if ch.isdigit())
        if 3 <= len(sic_digits) <= 4:
            v3_sic_sids.add(new_sid)
            v3_sic_events += 1
    sic_sids.update(v3_sic_sids)

    # Quantify how much of the old guard-review queue disappears under corrected
    # topology without accepting any candidate's old target security_id as truth.
    review_rows = read_gzip_csv(v3_authority_root / "identity_guard_review.csv.gz")
    review_dispositions = Counter()
    review_target_episode_dispositions: dict[str, set[str]] = defaultdict(set)
    for row in review_rows:
        old_sid = str(row.get("target_security_id") or "")
        target_new = old_to_new.get(old_sid, "")
        allocated_new = allocate_date(row.get("ticker", ""), row.get("filed", ""), corrected_by_ticker)
        if target_new and allocated_new == target_new:
            disposition = "NOW_ALLOCATES_TO_TARGET_CORRECTED_EPISODE"
        elif target_new and allocated_new:
            disposition = "ALLOCATES_TO_DIFFERENT_CORRECTED_EPISODE"
        elif not target_new:
            disposition = "TARGET_OLD_EPISODE_NOT_UNIQUELY_MAPPED"
        else:
            disposition = "STILL_NO_CORRECTED_ALLOCATION"
        review_dispositions[disposition] += 1
        review_target_episode_dispositions[old_sid].add(disposition)

    prospective_unresolved: list[dict[str, object]] = []
    resolved_corrected_candidates = 0
    if exact_resolution_available:
        for sid, item in sorted(aggregate.items()):
            reasons = []
            if int(item["unknown_type_observations"]) and sid not in type_sids:
                reasons.append("no_admitted_security_type_evidence")
            if int(item["missing_sector_observations"]) and sid not in sic_sids:
                reasons.append("no_admitted_sic_evidence")
            if sid in conflicting_type_sids:
                reasons.append("security_type_conflict")
            if reasons:
                prospective_unresolved.append({
                    "security_id": sid,
                    "ticker": item["ticker"],
                    "first_session": item["first_session"],
                    "last_session": item["last_session"],
                    "observations": item["observations"],
                    "unknown_type_observations": item["unknown_type_observations"],
                    "missing_sector_observations": item["missing_sector_observations"],
                    "old_candidate_fragments": item["old_candidate_fragments"],
                    "old_security_ids": ";".join(sorted(item["old_security_ids"])),
                    "observed_ciks": ";".join(sorted(item["observed_ciks"])),
                    "causal_issuer_ciks": ";".join(sorted(cik for s, cik in issuer_pairs if s == sid)),
                    "reasons": ";".join(reasons),
                })
            else:
                resolved_corrected_candidates += 1

    output.mkdir(parents=True, exist_ok=True)
    write_gzip_csv(output / "corrected_episode_guard.csv.gz", [
        "security_id", "ticker", "first_session", "last_session", "observations", "episode", "identity_authority",
    ], corrected)
    write_gzip_csv(output / "old_to_corrected_episode_mapping.csv.gz", [
        "old_security_id", "ticker", "old_first_session", "old_last_session", "old_observations",
        "old_observed_ciks", "corrected_security_id", "disposition", "overlapping_corrected_security_ids",
    ], topology_rows)
    write_gzip_csv(output / "candidate_mapping_anomalies.csv.gz", [
        "old_security_id", "ticker", "first_session", "last_session", "disposition", "overlapping_corrected_security_ids",
    ], candidate_mapping_anomalies)
    write_gzip_csv(output / "prospective_unresolved_corrected_topology.csv.gz", [
        "security_id", "ticker", "first_session", "last_session", "observations",
        "unknown_type_observations", "missing_sector_observations", "old_candidate_fragments",
        "old_security_ids", "observed_ciks", "causal_issuer_ciks", "reasons",
    ], prospective_unresolved)
    write_gzip_csv(output / "identity_boundary_records.csv.gz", list(boundary_records[0]) if boundary_records else ["ticker"], boundary_records)
    write_gzip_csv(output / "blocking_identity_conflicts.csv.gz", list(blocking[0]) if blocking else ["ticker"], blocking)

    baseline_unresolved = json.loads((v3_authority_root / "summary.json").read_text(encoding="utf-8"))
    unresolved_observations = sum(int(row.get("observations") or 0) for row in prospective_unresolved)
    unknown_type_observations = sum(int(row.get("unknown_type_observations") or 0) for row in prospective_unresolved)
    missing_sector_observations = sum(int(row.get("missing_sector_observations") or 0) for row in prospective_unresolved)
    summary = {
        "schema": SCHEMA,
        "status": "PASS" if not blocking and not candidate_mapping_anomalies and not conflicting_type_sids else "REVIEW_REQUIRED",
        "identity_source_sha": identity_source_sha,
        "identity_source_file_sha256": sha256_file(source_file),
        "identity_authority": module.IDENTITY_AUTHORITY,
        "old_guard_rows": len(old_guard),
        "corrected_guard_rows": len(corrected),
        "old_guard_rows_uniquely_mapped": len(old_to_new),
        "old_guard_mapping_dispositions": dict(sorted(topology_counts.items())),
        "corrected_episodes_with_multiple_old_fragments": sum(value > 1 for value in fragments_per_new.values()),
        "maximum_old_fragments_in_one_corrected_episode": max(fragments_per_new.values(), default=0),
        "candidate_episode_rows": len(candidate_rows),
        "corrected_candidate_episodes_with_metadata_gaps": len(aggregate),
        "candidate_mapping_anomalies": len(candidate_mapping_anomalies),
        "blocking_identity_conflicts": len(blocking),
        "identity_boundary_audit": identity_audit,
        "remapped_v2_identity_events": remapped_identity_events,
        "corrected_episodes_with_causal_issuer_cik": len({sid for sid, _cik in issuer_pairs}),
        "remapped_v2_type_events": remapped_v2_type_events,
        "v3_current_form_type_events_reallocated": v3_type_events,
        "corrected_episodes_with_type_evidence": len(type_sids),
        "security_type_conflict_episodes": len(conflicting_type_sids),
        "remapped_v2_sic_events": remapped_v2_sic_events,
        "v3_sic_events_reallocated": v3_sic_events,
        "corrected_episodes_with_sic_evidence": len(sic_sids),
        "v3_identity_events_reallocated": v3_identity_events,
        "corrected_episodes_with_v3_identity_evidence": len(v3_identity_sids),
        "old_guard_review_rows": len(review_rows),
        "old_guard_review_row_dispositions_under_corrected_topology": dict(sorted(review_dispositions.items())),
        "old_guard_review_target_episodes_with_any_now_allocatable_evidence": sum(
            "NOW_ALLOCATES_TO_TARGET_CORRECTED_EPISODE" in values
            for values in review_target_episode_dispositions.values()
        ),
        "exact_resolution_count_available": exact_resolution_available,
        "baseline_unresolved_old_topology_after_v3": int(baseline_unresolved["unresolved_episode_records_after_v3"]),
        "prospective_unresolved_corrected_topology": len(prospective_unresolved) if exact_resolution_available else None,
        "prospective_resolved_corrected_candidate_episodes": resolved_corrected_candidates if exact_resolution_available else None,
        "prospective_unresolved_observations": unresolved_observations if exact_resolution_available else None,
        "prospective_unknown_type_observations": unknown_type_observations if exact_resolution_available else None,
        "prospective_missing_sector_observations": missing_sector_observations if exact_resolution_available else None,
        "policy": {
            "security_identity_from_price_tape_and_causal_terminal_boundaries": True,
            "sec_cik_cannot_create_security_episode": True,
            "unknown_never_means_ineligible": True,
            "v3_candidate_target_security_id_is_not_authority": True,
            "type_requires_already_authorized_v2_or_current_approved_form_same_filing_identity": True,
            "sic_requires_causal_issuer_identity": True,
            "no_canonical_dataset_was_rewritten": True,
        },
        "next_gate": (
            "rebuild canonical PIT metadata on corrected guard and run full observation-level coverage audit"
            if exact_resolution_available and not blocking and not conflicting_type_sids
            else "resolve topology/anomaly blockers before canonical rebuild"
        ),
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        "# Corrected historical identity topology",
        "",
        f"Old guard rows: **{len(old_guard):,}**",
        f"Corrected tape/terminal guard rows: **{len(corrected):,}**",
        f"Blocking corrected identity conflicts: **{len(blocking):,}**",
        f"Old candidate rows crossing corrected boundaries: **{len(candidate_mapping_anomalies):,}**",
        "",
        f"Old V3 unresolved episodes: **{int(baseline_unresolved['unresolved_episode_records_after_v3']):,}**",
    ]
    if exact_resolution_available:
        lines.append(f"Prospective unresolved corrected-topology episodes: **{len(prospective_unresolved):,}**")
    lines.extend([
        "",
        "Security identity comes from tape continuity + causal terminal/relisting evidence; CIK is issuer evidence only.",
        "No missing evidence is treated as ineligibility and no canonical package is modified by this diagnostic.",
    ])
    (output / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_checksums(output)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--identity-source-root", type=Path, required=True)
    parser.add_argument("--identity-source-sha", required=True)
    parser.add_argument("--v2-root", type=Path, required=True)
    parser.add_argument("--v3-candidate-root", type=Path, required=True)
    parser.add_argument("--v3-authority-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = main_rebuild(
        identity_source_root=args.identity_source_root,
        identity_source_sha=args.identity_source_sha,
        v2_root=args.v2_root,
        v3_candidate_root=args.v3_candidate_root,
        v3_authority_root=args.v3_authority_root,
        output=args.output,
    )
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
