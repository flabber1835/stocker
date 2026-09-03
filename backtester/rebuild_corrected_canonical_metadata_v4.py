#!/usr/bin/env python3
"""Apply issuer-safe V4 candidates to the corrected metadata overlay and re-audit.

This is an evidence/allocation audit. It never rewrites canonical prices and never
turns missing evidence into ineligibility. All availability is strict prior:
usable_after < decision_session.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from backtester import historical_metadata_reconstruction_v2 as v2
from backtester import rebuild_historical_metadata_identity_topology_v3 as topo
from backtester import mine_historical_metadata_candidates_v4_issuer_safe as safe

SCHEMA = "backtester.historical-metadata-reconstruction-v4.issuer-safe-canonical-observation-audit/1"
V3_SHA256 = "989b58576dd684301cac88bebeb2d7107e1cfbb3fbc28e1b1e2a1a5df2372247"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
IDENTITY_QUALITIES = {
    "SEC_OWNERSHIP_ISSUER_TRADING_SYMBOL_XML",
    "SEC_EXPLICIT_TRADING_SYMBOL_LABEL",
}
TYPE_QUALITY = "CURRENT_FORM_EXACT_TICKER_CLASS_CANDIDATE"
SIC_QUALITIES = {
    "HEADER_SIC_CAUSAL_CIK",
    "HEADER_SIC_SAME_FILING_EXACT_TICKER_BOOTSTRAP",
}


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


def _write_gzip(path: Path, fields: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    topo.write_gzip_csv(path, list(fields), rows)


def _source_url_cik(url: object) -> str:
    return safe.v3.cik_from_url(str(url or ""))


def _guard_index(guard_rows: list[dict[str, str]]):
    by_ticker = topo.by_ticker_guard(guard_rows)
    by_sid = {str(row["security_id"]): row for row in guard_rows}
    if len(by_sid) != len(guard_rows):
        raise RuntimeError("corrected guard contains duplicate security_id")
    return by_ticker, by_sid


def _candidate_date_allowed(row: Mapping[str, str], guard: Mapping[str, str], by_ticker) -> bool:
    filed = topo.normalize_date(row.get("filed"))
    if not filed:
        return False
    first, last = str(guard["first_session"]), str(guard["last_session"])
    if first <= filed <= last:
        return True
    if filed >= first:
        return False
    low = f"{max(1994, int(first[:4]) - 3)}-01-01"
    if filed < low:
        return False
    ticker = topo.norm_ticker(row.get("ticker"))
    sid = str(guard["security_id"])
    for other in by_ticker.get(ticker, ()):
        if str(other.get("security_id")) == sid:
            continue
        if str(other.get("first_session")) < first and str(other.get("last_session")) >= filed:
            return False
    return True


def _validate_safe_candidate(row: Mapping[str, str], unresolved: Mapping[str, str], guard: Mapping[str, str], by_ticker) -> str:
    if str(row.get("admission_effect")) != "NONE_CANDIDATE_ONLY":
        return "prior_admission_effect"
    if str(row.get("security_id")) != str(unresolved.get("security_id")):
        return "security_id_drift"
    if topo.norm_ticker(row.get("ticker")) != topo.norm_ticker(unresolved.get("ticker")):
        return "ticker_drift"
    if topo.normalize_date(row.get("first_session")) != topo.normalize_date(unresolved.get("first_session")):
        return "first_session_drift"
    if topo.normalize_date(row.get("last_session")) != topo.normalize_date(unresolved.get("last_session")):
        return "last_session_drift"
    cik = topo.validate_cik(row.get("candidate_cik"))
    source_cik = topo.validate_cik(row.get("source_cik"))
    url_cik = _source_url_cik(row.get("source_url"))
    if not cik or not source_cik or source_cik != url_cik:
        return "invalid_source_or_candidate_cik"
    source_sha = str(row.get("source_sha256") or "").lower()
    if not SHA256_RE.fullmatch(source_sha):
        return "invalid_source_sha256"
    form = str(row.get("form") or "").upper()
    if form in safe.v3.OWNERSHIP_FORMS:
        if row.get("issuer_cik_source") != "OWNERSHIP_XML_ISSUER_CIK":
            return "ownership_issuer_cik_not_filing_bound"
        expected = str(cik == source_cik).lower()
        if str(row.get("issuer_cik_matches_source")) != expected:
            return "ownership_source_match_flag_invalid"
    else:
        if cik != source_cik or row.get("issuer_cik_source") != "SOURCE_URL_CIK_NON_OWNERSHIP":
            return "non_ownership_candidate_cik_not_source_bound"
    if not _candidate_date_allowed(row, guard, by_ticker):
        return "candidate_date_not_allocatable"
    return ""


def build(*, canonical: Path, v2_root: Path, v3_root: Path, corrected_root: Path,
          baseline_audit_root: Path, v4_root: Path, output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    v2.verify_package(v2_root)
    v2.verify_package(corrected_root)
    baseline = json.loads((baseline_audit_root / "summary.json").read_text())
    corrected_summary = json.loads((corrected_root / "summary.json").read_text())
    v3_summary = json.loads((v3_root / "summary.json").read_text())
    v4_summary = json.loads((v4_root / "summary.json").read_text())
    if baseline.get("status") != "PASS" or baseline.get("admission_status") != "REVIEW_REQUIRED":
        raise RuntimeError("baseline corrected observation audit is not REVIEW_REQUIRED/PASS")
    if int(baseline.get("unresolved_after_corrected_overlay", {}).get("episodes", -1)) != 10795:
        raise RuntimeError("baseline unresolved inventory is not the definitive 10,795-episode audit")
    if corrected_summary.get("status") != "PASS":
        raise RuntimeError("corrected topology is not PASS")
    for key in ("blocking_identity_conflicts", "candidate_mapping_anomalies", "security_type_conflict_episodes"):
        if int(corrected_summary.get(key, -1)) != 0:
            raise RuntimeError(f"corrected topology blocker: {key}={corrected_summary.get(key)}")
    candidate_path = v3_root / "candidate_evidence.csv.gz"
    if v3_summary.get("status") != "PASS" or v3_summary.get("candidate_only") is not True or topo.sha256_file(candidate_path) != V3_SHA256:
        raise RuntimeError("original V3 candidate corpus identity mismatch")
    if v4_summary.get("schema") != safe.MERGE_SCHEMA or v4_summary.get("status") != "PASS" or v4_summary.get("candidate_only") is not True or int(v4_summary.get("merged_shards", -1)) != 32:
        raise RuntimeError("issuer-safe V4 candidate corpus is not a complete 32-shard PASS")

    unresolved_rows = list(topo.iter_gzip_csv(baseline_audit_root / "definitive_unresolved_episodes.csv.gz"))
    unresolved_by_sid = {str(row["security_id"]): row for row in unresolved_rows}
    if len(unresolved_by_sid) != 10795:
        raise RuntimeError("baseline unresolved inventory row count mismatch")

    guard = list(topo.iter_gzip_csv(corrected_root / "corrected_episode_guard.csv.gz"))
    by_ticker, guard_by_sid = _guard_index(guard)
    corrected_sids = set(guard_by_sid)
    mapping: dict[str, str] = {}
    for row in topo.iter_gzip_csv(corrected_root / "old_to_corrected_episode_mapping.csv.gz"):
        if row.get("disposition") != "CONTAINED" or row.get("corrected_security_id") not in corrected_sids:
            raise RuntimeError(f"invalid corrected mapping: {row}")
        old, new = str(row["old_security_id"]), str(row["corrected_security_id"])
        if old in mapping and mapping[old] != new:
            raise RuntimeError(f"old security maps to multiple corrected episodes: {old}")
        mapping[old] = new

    # Reconstruct causal issuer proof dates from immutable V2 + original V3 evidence.
    issuer_pairs: set[tuple[str, str]] = set()
    first_issuer: dict[tuple[str, str], str] = {}
    first_issuer_sid: dict[str, str] = {}
    for row in topo.iter_gzip_csv(v2_root / "timeline" / "identity_events.csv.gz"):
        filed = topo.normalize_date(row.get("filed"))
        usable = topo.normalize_date(row.get("usable_after")) or filed
        sid = topo.allocate_date(row.get("ticker", ""), filed, by_ticker)
        cik = topo.validate_cik(row.get("cik"))
        if not sid or not cik or not usable:
            continue
        issuer_pairs.add((sid, cik))
        first_issuer[(sid, cik)] = min(first_issuer.get((sid, cik), usable), usable)
        first_issuer_sid[sid] = min(first_issuer_sid.get(sid, usable), usable)

    for row in topo.iter_gzip_csv(candidate_path):
        if row.get("candidate_kind") != "IDENTITY_EXACT_TICKER" or row.get("candidate_quality") not in IDENTITY_QUALITIES:
            continue
        filed = topo.normalize_date(row.get("filed"))
        sid = topo.allocate_date(row.get("ticker", ""), filed, by_ticker)
        cik = topo.validate_cik(row.get("candidate_cik"))
        if not sid or not cik or not filed:
            continue
        issuer_pairs.add((sid, cik))
        first_issuer[(sid, cik)] = min(first_issuer.get((sid, cik), filed), filed)
        first_issuer_sid[sid] = min(first_issuer_sid.get(sid, filed), filed)

    safe_rows = list(topo.iter_gzip_csv(v4_root / "candidate_evidence.csv.gz"))
    if len(safe_rows) != int(v4_summary.get("candidate_rows", -1)):
        raise RuntimeError("issuer-safe V4 candidate row count mismatch")
    accepted: list[dict[str, str]] = []
    rejected: list[dict[str, str]] = []
    for row in safe_rows:
        sid = str(row.get("security_id") or "")
        unresolved = unresolved_by_sid.get(sid)
        guard_row = guard_by_sid.get(sid)
        reason = "candidate_targets_non_definitive_episode" if not unresolved or not guard_row else _validate_safe_candidate(row, unresolved, guard_row, by_ticker)
        if reason:
            rejected.append(dict(row) | {"rejection_reason": reason})
        else:
            accepted.append(row)

    identity_keys: set[tuple[str, str, str, str, str]] = set()
    v4_identity_events: list[dict[str, object]] = []
    for row in accepted:
        if row.get("candidate_kind") != "IDENTITY_EXACT_TICKER" or row.get("candidate_quality") not in IDENTITY_QUALITIES:
            continue
        sid = str(row["security_id"])
        cik = topo.validate_cik(row.get("candidate_cik"))
        filed = topo.normalize_date(row.get("filed"))
        key = (sid, cik, filed, str(row.get("accession") or ""), str(row.get("source_sha256") or ""))
        identity_keys.add(key)
        issuer_pairs.add((sid, cik))
        first_issuer[(sid, cik)] = min(first_issuer.get((sid, cik), filed), filed)
        first_issuer_sid[sid] = min(first_issuer_sid.get(sid, filed), filed)
        v4_identity_events.append({
            "security_id": sid, "ticker": topo.norm_ticker(row.get("ticker")), "usable_after": filed,
            "cik": cik, "accession": row.get("accession", ""), "source_sha256": row.get("source_sha256", ""),
            "source_cik": row.get("source_cik", ""), "issuer_cik_source": row.get("issuer_cik_source", ""),
            "origin": "V4_ISSUER_SAFE_EXACT_TICKER",
        })

    type_points: dict[tuple[str, str], set[str]] = defaultdict(set)
    type_rows: list[dict[str, object]] = []
    for row in topo.iter_gzip_csv(baseline_audit_root / "corrected_security_type_events.csv.gz"):
        classification = str(row.get("classification") or "")
        sid, usable = str(row.get("security_id") or ""), topo.normalize_date(row.get("usable_after"))
        if classification in {"common", "non_common"} and sid and usable:
            type_points[(sid, usable)].add(classification)
            type_rows.append(dict(row))
    v4_type_events: list[dict[str, object]] = []
    for row in accepted:
        if row.get("candidate_kind") != "SECURITY_TYPE_EXACT_TICKER_CLASS" or row.get("candidate_quality") != TYPE_QUALITY:
            continue
        sid = str(row["security_id"])
        cik = topo.validate_cik(row.get("candidate_cik"))
        filed = topo.normalize_date(row.get("filed"))
        key = (sid, cik, filed, str(row.get("accession") or ""), str(row.get("source_sha256") or ""))
        classification = str(row.get("classification") or "")
        if key not in identity_keys or classification not in {"common", "non_common"}:
            rejected.append(dict(row) | {"rejection_reason": "type_without_same_filing_identity_proof"})
            continue
        event = {
            "security_id": sid, "ticker": topo.norm_ticker(row.get("ticker")), "usable_after": filed,
            "classification": classification, "cik": cik, "accession": row.get("accession", ""),
            "origin": "V4_ISSUER_SAFE_CURRENT_FORM",
        }
        type_points[(sid, filed)].add(classification)
        type_rows.append(event)
        v4_type_events.append(event)

    sic_points: dict[tuple[str, str], set[str]] = defaultdict(set)
    sic_rows: list[dict[str, object]] = []
    for row in topo.iter_gzip_csv(baseline_audit_root / "corrected_sic_events.csv.gz"):
        sid, usable = str(row.get("security_id") or ""), topo.normalize_date(row.get("usable_after"))
        sic = "".join(ch for ch in str(row.get("sic") or "") if ch.isdigit()).zfill(4)
        if sid and usable and len(sic) == 4:
            sic_points[(sid, usable)].add(sic)
            sic_rows.append(dict(row))
    v4_sic_events: list[dict[str, object]] = []
    for row in accepted:
        if row.get("candidate_kind") != "SIC_HEADER" or row.get("candidate_quality") not in SIC_QUALITIES:
            continue
        sid = str(row["security_id"])
        cik = topo.validate_cik(row.get("candidate_cik"))
        filed = topo.normalize_date(row.get("filed"))
        sic_digits = "".join(ch for ch in str(row.get("sic") or "") if ch.isdigit())
        sic = sic_digits.zfill(4) if 3 <= len(sic_digits) <= 4 else ""
        key = (sid, cik, filed, str(row.get("accession") or ""), str(row.get("source_sha256") or ""))
        if not sic:
            rejected.append(dict(row) | {"rejection_reason": "invalid_sic"})
            continue
        if (sid, cik) not in issuer_pairs:
            rejected.append(dict(row) | {"rejection_reason": "sic_without_issuer_identity"})
            continue
        if row.get("cik_authority") == "DISCOVERY_ONLY_HINT" and key not in identity_keys:
            rejected.append(dict(row) | {"rejection_reason": "discovery_sic_without_same_filing_identity"})
            continue
        proof = first_issuer[(sid, cik)]
        effective = max(filed, proof)
        event = {
            "security_id": sid, "ticker": topo.norm_ticker(row.get("ticker")), "usable_after": effective,
            "identity_proof_usable_after": proof, "cik": cik, "sic": sic,
            "accession": row.get("accession", ""), "origin": "V4_ISSUER_SAFE_SIC",
        }
        sic_points[(sid, effective)].add(sic)
        sic_rows.append(event)
        v4_sic_events.append(event)

    type_dates, type_values, type_conflicts = _timeline(type_points)
    sic_dates, sic_values, sic_conflicts = _timeline(sic_points)
    issuer_dates = {sid: [when] for sid, when in first_issuer_sid.items()}
    issuer_values = {sid: ["PROVED"] for sid in first_issuer_sid}

    episode_state: dict[str, dict[str, object]] = {}
    totals = Counter()
    files = v2.observation_files(canonical)
    target_sids = set(unresolved_by_sid)
    for index, path in enumerate(files, 1):
        with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                session = topo.normalize_date(row.get("session"))
                if not session or not (2006 <= int(session[:4]) <= 2026):
                    continue
                sid = mapping.get(str(row.get("security_id") or ""), "")
                if sid not in target_sids:
                    continue
                item = episode_state.setdefault(sid, {
                    "security_id": sid, "ticker": topo.norm_ticker(row.get("ticker")),
                    "first_session": unresolved_by_sid[sid]["first_session"], "last_session": unresolved_by_sid[sid]["last_session"],
                    "rows": 0, "type_base": 0, "type_resolved": 0, "type_unresolved": 0, "type_first": "", "type_last": "",
                    "sector_base": 0, "sector_resolved": 0, "sector_unresolved": 0, "sector_first": "", "sector_last": "",
                    "issuer_base": 0, "issuer_resolved": 0, "issuer_unresolved": 0,
                })
                item["rows"] = int(item["rows"]) + 1
                if _unknown_type(row.get("security_type")):
                    item["type_base"] = int(item["type_base"]) + 1
                    value = _prior(type_dates, type_values, sid, session)
                    if value and value != "CONFLICT":
                        item["type_resolved"] = int(item["type_resolved"]) + 1
                    else:
                        item["type_unresolved"] = int(item["type_unresolved"]) + 1
                        item["type_first"] = item["type_first"] or session
                        item["type_last"] = session
                        totals["type_unresolved"] += 1
                if _missing_sector(row):
                    item["sector_base"] = int(item["sector_base"]) + 1
                    value = _prior(sic_dates, sic_values, sid, session)
                    if value and value != "CONFLICT":
                        item["sector_resolved"] = int(item["sector_resolved"]) + 1
                    else:
                        item["sector_unresolved"] = int(item["sector_unresolved"]) + 1
                        item["sector_first"] = item["sector_first"] or session
                        item["sector_last"] = session
                        totals["sector_unresolved"] += 1
                if _unknown_issuer(row.get("issuer_identity")):
                    item["issuer_base"] = int(item["issuer_base"]) + 1
                    if _prior(issuer_dates, issuer_values, sid, session):
                        item["issuer_resolved"] = int(item["issuer_resolved"]) + 1
                    else:
                        item["issuer_unresolved"] = int(item["issuer_unresolved"]) + 1
                        totals["issuer_unresolved"] += 1
        print(f"[V4 OBS AUDIT] {index}/{len(files)} {path.name} type_unresolved={totals['type_unresolved']} sector_unresolved={totals['sector_unresolved']}", flush=True)

    remaining = []
    for sid in sorted(target_sids):
        item = episode_state.get(sid)
        if item is None:
            continue
        tu, su = int(item["type_unresolved"]), int(item["sector_unresolved"])
        if not tu and not su:
            continue
        if tu and su:
            bucket = "TYPE_AND_SECTOR"
        elif tu:
            bucket = "TYPE_ONLY"
        else:
            bucket = "SECTOR_ONLY"
        reasons = []
        if tu: reasons.append("unknown_security_type_after_v4")
        if su: reasons.append("missing_sector_after_v4")
        item["bucket"] = bucket
        item["reasons"] = ";".join(reasons)
        remaining.append(item)

    baseline_u = baseline["unresolved_after_corrected_overlay"]
    if len(remaining) > 10795 or totals["type_unresolved"] > int(baseline_u["unknown_type_observations"]) or totals["sector_unresolved"] > int(baseline_u["missing_sector_observations"]):
        raise RuntimeError("V4 overlay regressed definitive unresolved coverage")

    _write_gzip(output / "v4_authorized_identity_events.csv.gz", ["security_id","ticker","usable_after","cik","accession","source_sha256","source_cik","issuer_cik_source","origin"], v4_identity_events)
    _write_gzip(output / "v4_authorized_security_type_events.csv.gz", ["security_id","ticker","usable_after","classification","cik","accession","origin"], v4_type_events)
    _write_gzip(output / "v4_authorized_sic_events.csv.gz", ["security_id","ticker","usable_after","identity_proof_usable_after","cik","sic","accession","origin"], v4_sic_events)
    rejection_fields = list(safe.FIELDS) + ["rejection_reason"]
    _write_gzip(output / "v4_candidate_rejections.csv.gz", rejection_fields, rejected)
    _write_gzip(output / "security_type_conflicts_v4.csv.gz", ["security_id","usable_after","values"], type_conflicts)
    _write_gzip(output / "sic_conflicts_v4.csv.gz", ["security_id","usable_after","values"], sic_conflicts)
    remaining_fields = [
        "security_id","ticker","first_session","last_session","rows",
        "type_base","type_resolved","type_unresolved","type_first","type_last",
        "sector_base","sector_resolved","sector_unresolved","sector_first","sector_last",
        "issuer_base","issuer_resolved","issuer_unresolved","bucket","reasons",
    ]
    _write_gzip(output / "definitive_unresolved_episodes_v4.csv.gz", remaining_fields, remaining)

    summary = {
        "schema": SCHEMA,
        "status": "PASS",
        "admission_status": "PASS" if not remaining else "REVIEW_REQUIRED",
        "candidate_only_input": True,
        "canonical_price_dataset_rewritten": False,
        "causal_rule": "usable_after < decision_session",
        "unknown_never_means_ineligible": True,
        "baseline_unresolved_episodes": 10795,
        "v4_candidate_rows": len(safe_rows),
        "v4_candidate_rows_validated": len(accepted),
        "v4_candidate_rows_rejected": len(rejected),
        "v4_identity_events_authorized": len(v4_identity_events),
        "v4_security_type_events_authorized": len(v4_type_events),
        "v4_sic_events_authorized": len(v4_sic_events),
        "security_type_conflict_points": len(type_conflicts),
        "sic_conflict_points": len(sic_conflicts),
        "unresolved_after_v4": {
            "episodes": len(remaining),
            "unknown_type_observations": int(totals["type_unresolved"]),
            "missing_sector_observations": int(totals["sector_unresolved"]),
            "unknown_issuer_observations": int(totals["issuer_unresolved"]),
            "episode_buckets": dict(Counter(str(row["bucket"]) for row in remaining)),
        },
        "resolved_by_v4_increment": {
            "episodes": 10795 - len(remaining),
            "unknown_type_observations": int(baseline_u["unknown_type_observations"]) - int(totals["type_unresolved"]),
            "missing_sector_observations": int(baseline_u["missing_sector_observations"]) - int(totals["sector_unresolved"]),
            "unknown_issuer_observations": int(baseline_u["unknown_issuer_observations"]) - int(totals["issuer_unresolved"]),
        },
        "next_gate": "target external historical authority only at the residual produced by this issuer-safe audit",
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    lines = [
        "# Issuer-safe V4 corrected canonical observation audit", "",
        f"Baseline unresolved episodes: **10,795**",
        f"Remaining unresolved episodes: **{len(remaining):,}**",
        f"Episodes closed by retained SEC V4: **{10795-len(remaining):,}**",
        f"Remaining type observations: **{int(totals['type_unresolved']):,}**",
        f"Remaining sector observations: **{int(totals['sector_unresolved']):,}**",
        "", "No canonical price rows were rewritten. Unknown metadata remains unresolved/fail-closed.",
    ]
    (output / "SUMMARY.md").write_text("\n".join(lines) + "\n")
    topo.write_checksums(output)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--canonical-dataset", type=Path, required=True)
    parser.add_argument("--v2-root", type=Path, required=True)
    parser.add_argument("--v3-root", type=Path, required=True)
    parser.add_argument("--corrected-topology-root", type=Path, required=True)
    parser.add_argument("--baseline-audit-root", type=Path, required=True)
    parser.add_argument("--v4-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(
        canonical=args.canonical_dataset, v2_root=args.v2_root, v3_root=args.v3_root,
        corrected_root=args.corrected_topology_root, baseline_audit_root=args.baseline_audit_root,
        v4_root=args.v4_root, output=args.output,
    )
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
