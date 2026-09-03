#!/usr/bin/env python3
"""Observation-level audit of the corrected strict-PIT historical metadata overlay."""
from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Mapping, Sequence

from backtester import historical_metadata_reconstruction_v2 as v2
from backtester import rebuild_historical_metadata_identity_topology_v3 as topo

SCHEMA = "backtester.historical-metadata-reconstruction-v3.corrected-canonical-observation-audit/1"
V3_SHA256 = "989b58576dd684301cac88bebeb2d7107e1cfbb3fbc28e1b1e2a1a5df2372247"


def _unknown_type(value: object) -> bool:
    return str(value or "").strip().lower() in {"", "unknown", "none", "nan"}


def _missing_sector(row: Mapping[str, object]) -> bool:
    return not str(row.get("sic") or "").strip() or not str(row.get("ff12") or "").strip()


def _unknown_issuer(value: object) -> bool:
    text = str(value or "").strip()
    return not text or text.startswith("SEC_UNKNOWN:")


def _timeline(points: Mapping[tuple[str, str], set[str]]):
    rows: dict[str, list[tuple[str, str]]] = defaultdict(list)
    conflicts = []
    for (sid, when), values in sorted(points.items()):
        clean = sorted(v for v in values if v)
        if len(clean) == 1:
            value = clean[0]
        elif len(clean) > 1:
            value = "CONFLICT"
            conflicts.append({"security_id": sid, "usable_after": when, "values": ";".join(clean)})
        else:
            continue
        rows[sid].append((when, value))
    dates, values = {}, {}
    for sid, entries in rows.items():
        entries.sort()
        dates[sid] = [x[0] for x in entries]
        values[sid] = [x[1] for x in entries]
    return dates, values, conflicts


def _prior(dates: Mapping[str, Sequence[str]], values: Mapping[str, Sequence[str]], sid: str, session: str) -> str:
    source = dates.get(sid, ())
    index = bisect.bisect_left(source, session) - 1
    return "" if index < 0 else str(values[sid][index])


def _unallocated(target: list[dict], row: Mapping[str, object], reason: str) -> None:
    target.append({
        "ticker": topo.norm_ticker(row.get("ticker")),
        "filed": topo.normalize_date(row.get("filed")),
        "cik": topo.validate_cik(row.get("candidate_cik") or row.get("cik")),
        "kind": str(row.get("candidate_kind") or ""),
        "quality": str(row.get("candidate_quality") or ""),
        "accession": str(row.get("accession") or ""),
        "source_sha256": str(row.get("source_sha256") or ""),
        "reason": reason,
    })


def build(*, canonical: Path, v2_root: Path, v3_root: Path, corrected_root: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    corrected_summary = json.loads((corrected_root / "summary.json").read_text())
    if corrected_summary.get("status") != "PASS" or corrected_summary.get("exact_resolution_count_available") is not True:
        raise RuntimeError("corrected topology is not an exact PASS artifact")
    for key in ("blocking_identity_conflicts", "candidate_mapping_anomalies", "security_type_conflict_episodes"):
        if int(corrected_summary.get(key, -1)) != 0:
            raise RuntimeError(f"corrected topology blocker: {key}={corrected_summary.get(key)}")

    v3_summary = json.loads((v3_root / "summary.json").read_text())
    candidate_path = v3_root / "candidate_evidence.csv.gz"
    if v3_summary.get("status") != "PASS" or v3_summary.get("candidate_only") is not True or int(v3_summary.get("candidate_rows", -1)) != 22140:
        raise RuntimeError("V3 candidate artifact contract mismatch")
    if topo.sha256_file(candidate_path) != V3_SHA256:
        raise RuntimeError("V3 candidate evidence hash mismatch")

    guard = list(topo.iter_gzip_csv(corrected_root / "corrected_episode_guard.csv.gz"))
    by_ticker = topo.by_ticker_guard(guard)
    corrected_sids = {row["security_id"] for row in guard}
    mapping = {}
    old_ticker = {}
    old_by_new: dict[str, set[str]] = defaultdict(set)
    for row in topo.iter_gzip_csv(corrected_root / "old_to_corrected_episode_mapping.csv.gz"):
        if row.get("disposition") != "CONTAINED" or row.get("corrected_security_id") not in corrected_sids:
            raise RuntimeError(f"invalid corrected mapping: {row}")
        old, new = row["old_security_id"], row["corrected_security_id"]
        if old in mapping and mapping[old] != new:
            raise RuntimeError(f"old security maps to multiple corrected episodes: {old}")
        mapping[old] = new
        old_ticker[old] = topo.norm_ticker(row.get("ticker"))
        old_by_new[new].add(old)
    if len(mapping) != int(corrected_summary["old_guard_rows"]):
        raise RuntimeError("corrected mapping is incomplete")

    v3_rows = list(topo.iter_gzip_csv(candidate_path))
    counts = Counter()
    unallocated = []
    issuer_pairs: set[tuple[str, str]] = set()
    first_issuer: dict[tuple[str, str], str] = {}
    first_issuer_sid: dict[str, str] = {}

    for row in topo.iter_gzip_csv(v2_root / "timeline" / "identity_events.csv.gz"):
        filed = topo.normalize_date(row.get("filed"))
        usable = topo.normalize_date(row.get("usable_after")) or filed
        sid = topo.allocate_date(row.get("ticker", ""), filed, by_ticker)
        cik = topo.validate_cik(row.get("cik"))
        if not sid or not cik or not usable:
            _unallocated(unallocated, row, "V2_IDENTITY_NOT_ALLOCATABLE")
            continue
        issuer_pairs.add((sid, cik))
        first_issuer[(sid, cik)] = min(first_issuer.get((sid, cik), usable), usable)
        first_issuer_sid[sid] = min(first_issuer_sid.get(sid, usable), usable)
        counts["v2_identity_events"] += 1

    identity_key: dict[tuple[str, str, str, str, str], str] = {}
    for row in v3_rows:
        if row.get("candidate_kind") != "IDENTITY_EXACT_TICKER" or row.get("candidate_quality") not in topo.IDENTITY_QUALITIES:
            continue
        filed = topo.normalize_date(row.get("filed"))
        sid = topo.allocate_date(row.get("ticker", ""), filed, by_ticker)
        cik = topo.validate_cik(row.get("candidate_cik"))
        if not sid or not cik or not filed:
            _unallocated(unallocated, row, "V3_IDENTITY_NOT_ALLOCATABLE")
            continue
        key = topo.exact_ticker_source_key(row, filed)
        if key in identity_key and identity_key[key] != sid:
            raise RuntimeError(f"ticker-scoped SEC source maps to multiple corrected episodes: {key}")
        identity_key[key] = sid
        issuer_pairs.add((sid, cik))
        first_issuer[(sid, cik)] = min(first_issuer.get((sid, cik), filed), filed)
        first_issuer_sid[sid] = min(first_issuer_sid.get(sid, filed), filed)
        counts["v3_identity_events"] += 1

    type_points: dict[tuple[str, str], set[str]] = defaultdict(set)
    type_rows = []
    for row in topo.iter_gzip_csv(v2_root / "timeline" / "security_type_events.csv.gz"):
        classification = str(row.get("classification") or "")
        if classification not in {"common", "non_common"}:
            continue
        filed = topo.normalize_date(row.get("filed"))
        usable = topo.normalize_date(row.get("usable_after")) or filed
        sid = topo.allocate_date(row.get("ticker", ""), filed, by_ticker)
        if not sid or not usable:
            _unallocated(unallocated, row, "V2_TYPE_NOT_ALLOCATABLE")
            continue
        type_points[(sid, usable)].add(classification)
        type_rows.append({"security_id": sid, "ticker": topo.norm_ticker(row.get("ticker")), "usable_after": usable, "classification": classification, "cik": topo.validate_cik(row.get("cik")), "accession": row.get("accession", ""), "origin": "V2_AUTHORIZED"})
        counts["v2_type_events"] += 1
    for row in v3_rows:
        if row.get("candidate_kind") != "SECURITY_TYPE_EXACT_TICKER_CLASS" or row.get("candidate_quality") != topo.TYPE_QUALITY:
            continue
        classification = str(row.get("classification") or "")
        filed = topo.normalize_date(row.get("filed"))
        sid = identity_key.get(topo.exact_ticker_source_key(row, filed), "")
        if classification not in {"common", "non_common"} or not sid or not filed:
            _unallocated(unallocated, row, "V3_TYPE_WITHOUT_SAME_FILING_IDENTITY")
            continue
        type_points[(sid, filed)].add(classification)
        type_rows.append({"security_id": sid, "ticker": topo.norm_ticker(row.get("ticker")), "usable_after": filed, "classification": classification, "cik": topo.validate_cik(row.get("candidate_cik")), "accession": row.get("accession", ""), "origin": "V3_AUTHORIZED"})
        counts["v3_type_events"] += 1
    topo.write_gzip_csv(output / "corrected_security_type_events.csv.gz", ["security_id", "ticker", "usable_after", "classification", "cik", "accession", "origin"], type_rows)
    type_dates, type_values, type_conflicts = _timeline(type_points)
    topo.write_gzip_csv(output / "security_type_conflicts.csv.gz", ["security_id", "usable_after", "values"], type_conflicts)

    sic_points: dict[tuple[str, str], set[str]] = defaultdict(set)
    sic_rows = []
    for row in topo.iter_gzip_csv(v2_root / "timeline" / "sic_events.csv.gz"):
        filed = topo.normalize_date(row.get("filed"))
        usable = topo.normalize_date(row.get("usable_after")) or filed
        proof_date = topo.normalize_date(row.get("identity_proof_filed")) or usable or filed
        sid = topo.allocate_date(row.get("ticker", ""), proof_date, by_ticker)
        cik = topo.validate_cik(row.get("cik"))
        sic = "".join(ch for ch in str(row.get("sic") or "") if ch.isdigit())
        if not sid or (sid, cik) not in issuer_pairs or not usable or not (3 <= len(sic) <= 4):
            _unallocated(unallocated, row, "V2_SIC_WITHOUT_CAUSAL_ISSUER")
            continue
        proof = first_issuer[(sid, cik)]
        effective, sic = max(usable, proof), sic.zfill(4)
        sic_points[(sid, effective)].add(sic)
        sic_rows.append({"security_id": sid, "ticker": topo.norm_ticker(row.get("ticker")), "usable_after": effective, "identity_proof_usable_after": proof, "cik": cik, "sic": sic, "accession": row.get("accession", ""), "origin": "V2_AUTHORIZED"})
        counts["v2_sic_events"] += 1
    for row in v3_rows:
        if row.get("candidate_kind") != "SIC_HEADER":
            continue
        filed = topo.normalize_date(row.get("filed"))
        sid = topo.allocate_date(row.get("ticker", ""), filed, by_ticker)
        cik = topo.validate_cik(row.get("candidate_cik"))
        sic = "".join(ch for ch in str(row.get("sic") or "") if ch.isdigit())
        if not sid or (sid, cik) not in issuer_pairs or not filed or not (3 <= len(sic) <= 4):
            _unallocated(unallocated, row, "V3_SIC_WITHOUT_CAUSAL_ISSUER")
            continue
        if row.get("cik_authority") == "DISCOVERY_ONLY_HINT" and identity_key.get(topo.exact_ticker_source_key(row, filed)) != sid:
            _unallocated(unallocated, row, "V3_DISCOVERY_SIC_WITHOUT_SAME_FILING_IDENTITY")
            continue
        proof = first_issuer[(sid, cik)]
        effective, sic = max(filed, proof), sic.zfill(4)
        sic_points[(sid, effective)].add(sic)
        sic_rows.append({"security_id": sid, "ticker": topo.norm_ticker(row.get("ticker")), "usable_after": effective, "identity_proof_usable_after": proof, "cik": cik, "sic": sic, "accession": row.get("accession", ""), "origin": "V3_AUTHORIZED"})
        counts["v3_sic_events"] += 1
    topo.write_gzip_csv(output / "corrected_sic_events.csv.gz", ["security_id", "ticker", "usable_after", "identity_proof_usable_after", "cik", "sic", "accession", "origin"], sic_rows)
    sic_dates, sic_values, sic_conflicts = _timeline(sic_points)
    topo.write_gzip_csv(output / "sic_conflicts.csv.gz", ["security_id", "usable_after", "values"], sic_conflicts)
    topo.write_gzip_csv(output / "unallocated_evidence.csv.gz", ["ticker", "filed", "cik", "kind", "quality", "accession", "source_sha256", "reason"], unallocated)

    totals = Counter()
    yearly: dict[str, Counter] = defaultdict(Counter)
    episodes: dict[str, dict] = {}
    missing_mapping = []
    files = v2.observation_files(canonical)
    for index, path in enumerate(files, 1):
        with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                session = topo.normalize_date(row.get("session"))
                if not session or not (2006 <= int(session[:4]) <= 2026):
                    continue
                old = str(row.get("security_id") or "")
                sid = mapping.get(old, "")
                if not sid:
                    totals["missing_mapping"] += 1
                    if len(missing_mapping) < 20:
                        missing_mapping.append({"session": session, "security_id": old, "ticker": row.get("ticker", "")})
                    continue
                ticker = topo.norm_ticker(row.get("ticker"))
                if old_ticker.get(old) and old_ticker[old] != ticker:
                    raise RuntimeError(f"observation/guard ticker mismatch: {(old, session, ticker)}")
                year = session[:4]
                totals["rows"] += 1
                yearly[year]["rows"] += 1
                item = episodes.setdefault(sid, {"security_id": sid, "ticker": ticker, "first_session": session, "last_session": session, "rows": 0, "type_base": 0, "type_resolved": 0, "type_unresolved": 0, "type_first": "", "type_last": "", "sector_base": 0, "sector_resolved": 0, "sector_unresolved": 0, "sector_first": "", "sector_last": "", "issuer_base": 0, "issuer_resolved": 0, "issuer_unresolved": 0})
                item["first_session"] = min(item["first_session"], session)
                item["last_session"] = max(item["last_session"], session)
                item["rows"] += 1
                if _unknown_type(row.get("security_type")):
                    totals["type_base"] += 1; yearly[year]["type_base"] += 1; item["type_base"] += 1
                    if _prior(type_dates, type_values, sid, session) in {"common", "non_common"}:
                        totals["type_resolved"] += 1; yearly[year]["type_resolved"] += 1; item["type_resolved"] += 1
                    else:
                        totals["type_unresolved"] += 1; yearly[year]["type_unresolved"] += 1; item["type_unresolved"] += 1
                        item["type_first"] = item["type_first"] or session; item["type_last"] = session
                if _missing_sector(row):
                    totals["sector_base"] += 1; yearly[year]["sector_base"] += 1; item["sector_base"] += 1
                    value = _prior(sic_dates, sic_values, sid, session)
                    if value.isdigit() and 3 <= len(value) <= 4:
                        totals["sector_resolved"] += 1; yearly[year]["sector_resolved"] += 1; item["sector_resolved"] += 1
                    else:
                        totals["sector_unresolved"] += 1; yearly[year]["sector_unresolved"] += 1; item["sector_unresolved"] += 1
                        item["sector_first"] = item["sector_first"] or session; item["sector_last"] = session
                if _unknown_issuer(row.get("issuer_id")):
                    totals["issuer_base"] += 1; yearly[year]["issuer_base"] += 1; item["issuer_base"] += 1
                    if first_issuer_sid.get(sid, "") and first_issuer_sid[sid] < session:
                        totals["issuer_resolved"] += 1; yearly[year]["issuer_resolved"] += 1; item["issuer_resolved"] += 1
                    else:
                        totals["issuer_unresolved"] += 1; yearly[year]["issuer_unresolved"] += 1; item["issuer_unresolved"] += 1
        print(f"[OBS_AUDIT] {index}/{len(files)} {path.name} rows={totals['rows']} type_unresolved={totals['type_unresolved']} sector_unresolved={totals['sector_unresolved']}", flush=True)
    if totals["missing_mapping"]:
        raise RuntimeError(f"canonical observations missing corrected mapping: {totals['missing_mapping']} examples={missing_mapping}")

    baseline = json.loads((v2_root / "canonical_coverage.json").read_text())["totals"]
    if totals["type_base"] != int(baseline["unknown_type_observations"]) or totals["sector_base"] != int(baseline["missing_sector_observations"]):
        raise RuntimeError("frozen canonical baseline counts changed")

    unresolved, buckets = [], Counter()
    for sid, item in sorted(episodes.items()):
        type_gap, sector_gap = item["type_unresolved"] > 0, item["sector_unresolved"] > 0
        if not (type_gap or sector_gap):
            continue
        bucket = "TYPE_AND_SECTOR" if type_gap and sector_gap else ("TYPE_ONLY" if type_gap else "SECTOR_ONLY")
        buckets[bucket] += 1
        unresolved.append({**item, "old_security_ids": ";".join(sorted(old_by_new.get(sid, ()))), "bucket": bucket, "reasons": ";".join((["unknown_security_type_after_overlay"] if type_gap else []) + (["missing_sector_after_overlay"] if sector_gap else []))})
    fields = ["security_id", "ticker", "first_session", "last_session", "rows", "old_security_ids", "type_base", "type_resolved", "type_unresolved", "type_first", "type_last", "sector_base", "sector_resolved", "sector_unresolved", "sector_first", "sector_last", "issuer_base", "issuer_resolved", "issuer_unresolved", "bucket", "reasons"]
    topo.write_gzip_csv(output / "definitive_unresolved_episodes.csv.gz", fields, unresolved)

    admission = "PASS" if not unresolved and not type_conflicts and not sic_conflicts else "REVIEW_REQUIRED"
    summary = {
        "schema": SCHEMA,
        "status": "PASS",
        "admission_status": admission,
        "causal_rule": "usable_after < decision_session",
        "canonical_price_dataset_rewritten": False,
        "corrected_metadata_overlay_built": True,
        "unknown_never_means_ineligible": True,
        "canonical_observation_rows": totals["rows"],
        "old_security_ids_mapped": len(mapping),
        "corrected_security_episodes_observed": len(episodes),
        "evidence_counts": dict(sorted(counts.items())),
        "unallocated_evidence_rows": len(unallocated),
        "security_type_conflict_points": len(type_conflicts),
        "sic_conflict_points": len(sic_conflicts),
        "baseline": {"unknown_type_observations": totals["type_base"], "missing_sector_observations": totals["sector_base"], "unknown_issuer_observations": totals["issuer_base"]},
        "resolved_by_corrected_overlay": {"unknown_type_observations": totals["type_resolved"], "missing_sector_observations": totals["sector_resolved"], "unknown_issuer_observations": totals["issuer_resolved"]},
        "unresolved_after_corrected_overlay": {"unknown_type_observations": totals["type_unresolved"], "missing_sector_observations": totals["sector_unresolved"], "unknown_issuer_observations": totals["issuer_unresolved"], "episodes": len(unresolved), "episode_buckets": dict(sorted(buckets.items()))},
        "prospective_topology_inventory": {"episodes": int(corrected_summary["prospective_unresolved_corrected_topology"]), "observations": int(corrected_summary["prospective_unresolved_observations"])},
        "observation_level_delta_vs_prospective_episodes": len(unresolved) - int(corrected_summary["prospective_unresolved_corrected_topology"]),
        "years": {year: dict(c) for year, c in sorted(yearly.items())},
        "next_gate": "materialize corrected canonical PIT metadata package" if admission == "PASS" else "expand historical authority for definitive unresolved inventory",
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    (output / "SUMMARY.md").write_text(
        "# Corrected canonical PIT metadata observation audit\n\n"
        f"- Audit status: **PASS**\n- Admission status: **{admission}**\n"
        f"- Canonical observations audited: **{totals['rows']:,}**\n"
        f"- Definitive unresolved episodes: **{len(unresolved):,}**\n"
        f"- Unknown-type observations remaining: **{totals['type_unresolved']:,}**\n"
        f"- Missing-sector observations remaining: **{totals['sector_unresolved']:,}**\n\n"
        "Unknown evidence is never treated as ineligibility. The frozen price/action package was not modified.\n"
    )
    topo.write_checksums(output)
    return summary


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--canonical-dataset", type=Path, required=True)
    p.add_argument("--v2-root", type=Path, required=True)
    p.add_argument("--v3-candidate-root", type=Path, required=True)
    p.add_argument("--corrected-topology-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    result = build(canonical=a.canonical_dataset, v2_root=a.v2_root, v3_root=a.v3_candidate_root, corrected_root=a.corrected_topology_root, output=a.output)
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
