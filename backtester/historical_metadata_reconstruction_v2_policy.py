#!/usr/bin/env python3
"""Fail-closed policy layer for historical metadata reconstruction v2.

This module contains the admission rules that are intentionally stricter than
source discovery. It prevents inferred vendor aliases from becoming authority,
plans web fallback against the first still-unresolved observation rather than
against episode-level coverage, and gates final admission on strict-prior
canonical observation coverage.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from backtester import historical_metadata_reconstruction_v2 as base

POLICY_SCHEMA = "backtester.historical-metadata-reconstruction-v2.policy/1"
ALIAS_POLICY = "disabled_without_independent_historical_alias_proof"


def _unknown_type(row: Mapping[str, str]) -> bool:
    value = str(row.get("security_type") or "").strip().lower()
    return not value or value == "unknown"


def _missing_sector(row: Mapping[str, str]) -> bool:
    return not str(row.get("sic") or "").strip() or not str(row.get("ff12") or "").strip()


def _candidate_rows(path: Path) -> list[dict[str, str]]:
    return base.read_gzip_csv(path)


def _strict_prior(rows: Sequence[Mapping[str, str]], session: str, date_key: str = "usable_after") -> list[Mapping[str, str]]:
    return [row for row in rows if str(row.get(date_key) or "") and str(row.get(date_key)) < session]


def harden_candidates(canonical_dataset: Path, candidates_dir: Path) -> dict:
    """Attach exact first-gap dates and disable unproven vendor alias inference."""
    candidate_path = candidates_dir / "candidate_episodes.csv.gz"
    if not candidate_path.exists():
        raise base.ReconstructionError(f"missing candidates: {candidate_path}")
    rows = _candidate_rows(candidate_path)
    by_key = {(row["security_id"], base.norm_ticker(row["ticker"])): row for row in rows}
    if len(by_key) != len(rows):
        raise base.ReconstructionError("duplicate candidate security episode")

    gap: dict[tuple[str, str], dict[str, str]] = {
        key: {
            "first_unknown_type_session": "",
            "last_unknown_type_session": "",
            "first_missing_sector_session": "",
            "last_missing_sector_session": "",
        }
        for key in by_key
    }
    seen_ciks: dict[tuple[str, str], set[str]] = defaultdict(set)

    files = base.observation_files(canonical_dataset)
    for index, path in enumerate(files, 1):
        with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
            for observation in csv.DictReader(fh):
                sid = str(observation.get("security_id") or "").strip()
                ticker = base.norm_ticker(observation.get("ticker"))
                key = (sid, ticker)
                if key not in by_key:
                    continue
                session = str(observation.get("session") or "")[:10]
                if not session:
                    continue
                if _unknown_type(observation):
                    rec = gap[key]
                    if not rec["first_unknown_type_session"]:
                        rec["first_unknown_type_session"] = session
                    rec["last_unknown_type_session"] = session
                if _missing_sector(observation):
                    rec = gap[key]
                    if not rec["first_missing_sector_session"]:
                        rec["first_missing_sector_session"] = session
                    rec["last_missing_sector_session"] = session
                cik = base.parse_issuer_authority(observation.get("issuer_id"))
                if cik:
                    seen_ciks[key].add(cik)
        print(f"[POLICY] gap-scan partition={index}/{len(files)} {path.name}", flush=True)

    security_ids = {str(row["security_id"]) for row in rows}
    output_rows: list[dict[str, object]] = []
    leaked: list[tuple[str, str]] = []
    for key, row in sorted(by_key.items()):
        claimed = {
            base.validate_cik(value)
            for value in str(row.get("observed_ciks") or "").split(";")
            if base.validate_cik(value)
        }
        actual = seen_ciks.get(key, set())
        if claimed != actual:
            raise base.ReconstructionError(
                f"candidate CIK set does not match canonical issuer authority for {key}: "
                f"candidate={sorted(claimed)} canonical={sorted(actual)}"
            )
        for cik in claimed:
            if cik in security_ids or cik == key[0]:
                leaked.append((key[0], cik))
        hardened = dict(row)
        hardened.update(gap[key])
        hardened["observed_ciks"] = ";".join(sorted(actual))
        hardened["alias_symbol"] = ""
        hardened["alias_safe"] = "false"
        hardened["alias_policy"] = ALIAS_POLICY
        output_rows.append(hardened)

    if leaked:
        raise base.ReconstructionError(f"security ids leaked into CIK fields: {leaked[:10]}")

    fields = [
        "security_id", "ticker", "first_session", "last_session", "observations",
        "unknown_type_observations", "missing_sector_observations", "observed_ciks",
        "first_unknown_type_session", "last_unknown_type_session",
        "first_missing_sector_session", "last_missing_sector_session",
        "alias_symbol", "alias_safe", "alias_policy",
    ]
    base.write_gzip_csv(candidate_path, fields, output_rows)

    coverage_path = candidates_dir / "candidate_coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8")) if coverage_path.exists() else {}
    coverage.update({
        "policy_schema": POLICY_SCHEMA,
        "alias_policy": ALIAS_POLICY,
        "safe_vendor_alias_episodes": 0,
        "episodes_with_unknown_type_gap": sum(bool(g["first_unknown_type_session"]) for g in gap.values()),
        "episodes_with_missing_sector_gap": sum(bool(g["first_missing_sector_session"]) for g in gap.values()),
        "candidate_sha256": base.sha256_file(candidate_path),
        "security_id_in_cik_fields": 0,
    })
    coverage_path.write_text(json.dumps(coverage, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    base.write_checksums(candidates_dir)
    return coverage


def _find_zip_member(zf: zipfile.ZipFile, target: str) -> str:
    wanted = target.upper()
    matches = [name for name in zf.namelist() if Path(name).name.upper() == wanted]
    if len(matches) != 1:
        raise base.ReconstructionError(f"expected exactly one {target} in archive, got {matches}")
    return matches[0]


def parse_bulk_hardened(sec_dir: Path, candidates_path: Path, output: Path) -> dict:
    """Parse retained SEC bulk ZIPs with bounded memory and exact provenance."""
    candidates = base.load_candidates(candidates_path)
    if any(candidate.alias_safe or candidate.alias_symbol for candidate in candidates):
        raise base.ReconstructionError("authoritative bulk parse refuses inferred vendor aliases")
    exact_symbols = {candidate.ticker for candidate in candidates}
    candidate_ciks = {cik for candidate in candidates for cik in candidate.observed_ciks}
    output.mkdir(parents=True, exist_ok=True)

    archive_rows: list[dict[str, object]] = []
    identity_rows: list[dict[str, object]] = []
    type_rows: list[dict[str, object]] = []
    title_source_rows: list[dict[str, object]] = []

    archives = [sec_dir / name for name in base.expected_archive_names()]
    for index, archive in enumerate(archives, 1):
        if not archive.exists():
            raise base.ReconstructionError(f"missing SEC bulk archive: {archive}")
        archive_digest = base.sha256_file(archive)
        with zipfile.ZipFile(archive) as zf:
            bad = zf.testzip()
            if bad:
                raise base.ReconstructionError(f"corrupt ZIP member {bad} in {archive.name}")
            names = {
                "SUBMISSION.tsv": _find_zip_member(zf, "SUBMISSION.tsv"),
                "NONDERIV_TRANS.tsv": _find_zip_member(zf, "NONDERIV_TRANS.tsv"),
                "NONDERIV_HOLDING.tsv": _find_zip_member(zf, "NONDERIV_HOLDING.tsv"),
            }
            member_data = {label: zf.read(name) for label, name in names.items()}
            member_hashes = {label: base.sha256_bytes(data) for label, data in member_data.items()}
            for label, data in member_data.items():
                archive_rows.append({
                    "archive": archive.name,
                    "archive_sha256": archive_digest,
                    "archive_bytes": archive.stat().st_size,
                    "member": label,
                    "member_sha256": member_hashes[label],
                    "member_bytes": len(data),
                })

            relevant: dict[str, dict[str, str]] = {}
            for row in base._dict_reader_from_bytes(member_data["SUBMISSION.tsv"]):
                accession = row.get("ACCESSION_NUMBER", "")
                filed = base.normalize_date(row.get("FILING_DATE", ""))
                cik = base.validate_cik(row.get("ISSUERCIK", ""))
                symbol = base.norm_ticker(row.get("ISSUERTRADINGSYMBOL", ""))
                if not accession or not filed or not cik or not symbol:
                    continue
                if symbol not in exact_symbols and cik not in candidate_ciks:
                    continue
                relevant[accession] = {
                    "accession": accession,
                    "filed": filed,
                    "cik": cik,
                    "sec_symbol": symbol,
                    "document_type": str(row.get("DOCUMENT_TYPE", "")).upper(),
                }

            titles: dict[str, set[str]] = defaultdict(set)
            title_sources: dict[tuple[str, str, str], dict[str, object]] = {}
            for member_label, source_table in (
                ("NONDERIV_TRANS.tsv", "NONDERIV_TRANS"),
                ("NONDERIV_HOLDING.tsv", "NONDERIV_HOLDING"),
            ):
                for row in base._dict_reader_from_bytes(member_data[member_label]):
                    accession = row.get("ACCESSION_NUMBER", "")
                    if accession not in relevant:
                        continue
                    title = base.clean_title(row.get("SECURITY_TITLE", ""))
                    if not title:
                        continue
                    titles[accession].add(title)
                    key = (accession, title, source_table)
                    title_sources.setdefault(key, {
                        "accession": accession,
                        "security_title": title,
                        "source_table": source_table,
                        "archive": archive.name,
                        "archive_sha256": archive_digest,
                        "member_sha256": member_hashes[member_label],
                    })

            for accession, submission in sorted(relevant.items()):
                identity_rows.append({
                    **submission,
                    "source_kind": "SEC_FORM345_BULK_SUBMISSION",
                    "archive": archive.name,
                    "archive_sha256": archive_digest,
                    "member": "SUBMISSION.tsv",
                    "member_sha256": member_hashes["SUBMISSION.tsv"],
                })
                classification, evidence = base.classify_titles(titles.get(accession, ()))
                if evidence:
                    type_rows.append({
                        **submission,
                        "classification": classification,
                        "security_title_evidence": evidence,
                        "authority": "SEC Form 3/4/5 non-derivative Table I titles joined to SUBMISSION",
                        "archive": archive.name,
                        "archive_sha256": archive_digest,
                    })
            title_source_rows.extend(title_sources.values())

        print(
            f"[POLICY-BULK] archive={index}/{len(archives)} {archive.name} "
            f"identities={len(identity_rows)} types={len(type_rows)}",
            flush=True,
        )

    def dedup(rows: Iterable[Mapping[str, object]], keys: Sequence[str]) -> list[dict[str, object]]:
        chosen: dict[tuple[str, ...], dict[str, object]] = {}
        for row in rows:
            key = tuple(str(row.get(k, "")) for k in keys)
            chosen.setdefault(key, dict(row))
        return [chosen[key] for key in sorted(chosen)]

    archive_rows = dedup(archive_rows, ("archive", "member", "member_sha256"))
    identity_rows = dedup(identity_rows, ("accession", "filed", "cik", "sec_symbol", "archive_sha256"))
    type_rows = dedup(type_rows, ("accession", "filed", "cik", "sec_symbol", "classification", "archive_sha256"))
    title_source_rows = dedup(title_source_rows, ("accession", "security_title", "source_table", "archive_sha256"))

    base.write_gzip_csv(output / "source_archives.csv.gz", [
        "archive", "archive_sha256", "archive_bytes", "member", "member_sha256", "member_bytes",
    ], archive_rows)
    base.write_gzip_csv(output / "bulk_identity_sources.csv.gz", [
        "accession", "filed", "cik", "sec_symbol", "document_type", "source_kind",
        "archive", "archive_sha256", "member", "member_sha256",
    ], identity_rows)
    base.write_gzip_csv(output / "bulk_security_type_sources.csv.gz", [
        "accession", "filed", "cik", "sec_symbol", "document_type", "classification",
        "security_title_evidence", "authority", "archive", "archive_sha256",
    ], type_rows)
    base.write_gzip_csv(output / "bulk_security_title_sources.csv.gz", [
        "accession", "security_title", "source_table", "archive", "archive_sha256", "member_sha256",
    ], title_source_rows)
    summary = {
        "schema": f"{base.SCHEMA_PREFIX}.bulk-corpus/2",
        "status": "PASS",
        "policy_schema": POLICY_SCHEMA,
        "alias_policy": ALIAS_POLICY,
        "archives": len(archives),
        "archive_member_manifest_rows": len(archive_rows),
        "identity_sources": len(identity_rows),
        "security_type_sources": len(type_rows),
        "security_title_sources": len(title_source_rows),
        "source": "retained SEC Insider Transactions Data Sets Form 3/4/5 quarterly ZIPs",
        "derivative_tables_used_for_type": False,
        "title_source_retention": "unique accession/title/source-table rows only",
    }
    (output / "bulk_coverage.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    base.write_checksums(output)
    return summary


def _index_by_sid(path: Path) -> dict[str, list[dict[str, str]]]:
    result: dict[str, list[dict[str, str]]] = defaultdict(list)
    if not path.exists():
        return result
    for row in base.read_gzip_csv(path):
        sid = str(row.get("security_id") or "")
        if sid:
            result[sid].append(row)
    return result


def build_strict_web_plan(
    candidates_path: Path,
    timeline_dir: Path,
    output: Path,
    discovery_path: Path | None = None,
) -> dict:
    """Plan only gaps lacking evidence strictly before the first affected observation."""
    candidates = _candidate_rows(candidates_path)
    identities = _index_by_sid(timeline_dir / "identity_events.csv.gz")
    types = _index_by_sid(timeline_dir / "security_type_events.csv.gz")
    sics = _index_by_sid(timeline_dir / "sic_events.csv.gz")
    discovery = base.load_discovery_map(discovery_path) if discovery_path and discovery_path.exists() else {}

    plan_rows: list[dict[str, object]] = []
    no_cik: list[dict[str, object]] = []
    for candidate in candidates:
        sid = str(candidate["security_id"])
        ticker = base.norm_ticker(candidate["ticker"])
        first_type_gap = str(candidate.get("first_unknown_type_session") or "")
        first_sector_gap = str(candidate.get("first_missing_sector_session") or "")
        first_need = min([value for value in (first_type_gap, first_sector_gap) if value], default="")
        if not first_need:
            continue

        identity_prior = _strict_prior(identities.get(sid, ()), first_need)
        need_identity = not identity_prior
        need_type = bool(first_type_gap) and not _strict_prior(types.get(sid, ()), first_type_gap)
        need_sic = bool(first_sector_gap) and not _strict_prior(sics.get(sid, ()), first_sector_gap)
        if not (need_identity or need_type or need_sic):
            continue

        ciks = {
            base.validate_cik(value)
            for value in str(candidate.get("observed_ciks") or "").split(";")
            if base.validate_cik(value)
        }
        for row in identities.get(sid, ()):
            cik = base.validate_cik(row.get("cik"))
            if cik:
                ciks.add(cik)

        discovery_ciks: set[str] = set()
        if not ciks:
            discovery_ciks = set(discovery.get(ticker, set()))
            ciks.update(discovery_ciks)

        if not ciks:
            no_cik.append({
                "security_id": sid,
                "ticker": ticker,
                "first_need_session": first_need,
                "need_identity": str(need_identity).lower(),
                "need_type": str(need_type).lower(),
                "need_sic": str(need_sic).lower(),
                "reason": "no_valid_cik_for_web_fallback",
            })
            continue

        prior_identity_ciks = {
            base.validate_cik(row.get("cik")) for row in identity_prior if base.validate_cik(row.get("cik"))
        }
        for cik in sorted(ciks):
            discovery_only = cik not in prior_identity_ciks
            plan_rows.append({
                "security_id": sid,
                "ticker": ticker,
                "alias_symbol": "",
                "cik": cik,
                "need_identity": str(need_identity or discovery_only).lower(),
                "need_type": str(need_type).lower(),
                "need_sic": str(need_sic).lower(),
                "discovery_only_cik_hint": str(discovery_only).lower(),
                "first_session": str(candidate["first_session"]),
                "last_session": str(candidate["last_session"]),
                "first_need_session": first_need,
                "first_unknown_type_session": first_type_gap,
                "first_missing_sector_session": first_sector_gap,
            })

    chosen: dict[tuple[str, str], dict[str, object]] = {}
    for row in plan_rows:
        chosen[(str(row["security_id"]), str(row["cik"]))] = row
    plan_rows = [chosen[key] for key in sorted(chosen)]
    output.mkdir(parents=True, exist_ok=True)
    base.write_gzip_csv(output / "web_plan.csv.gz", [
        "security_id", "ticker", "alias_symbol", "cik", "need_identity", "need_type", "need_sic",
        "discovery_only_cik_hint", "first_session", "last_session", "first_need_session",
        "first_unknown_type_session", "first_missing_sector_session",
    ], plan_rows)
    base.write_gzip_csv(output / "web_plan_no_cik.csv.gz", [
        "security_id", "ticker", "first_need_session", "need_identity", "need_type", "need_sic", "reason",
    ], no_cik)
    summary = {
        "schema": f"{base.SCHEMA_PREFIX}.web-plan/2",
        "status": "PASS",
        "policy_schema": POLICY_SCHEMA,
        "alias_policy": ALIAS_POLICY,
        "gap_rule": "web fallback is required unless evidence usable_after is strictly before first unresolved observation",
        "episode_cik_rows": len(plan_rows),
        "unique_ciks": len({str(row["cik"]) for row in plan_rows}),
        "episodes_without_cik": len(no_cik),
        "discovery_index_role": "discovery-only; never causal authority" if discovery_path else "not supplied",
    }
    (output / "web_plan_coverage.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    base.write_checksums(output)
    return summary


def fetch_web_policy(**kwargs) -> dict:
    """Run the bounded fetch and distinguish source absence from network incompleteness."""
    result = base.fetch_web_fallback(**kwargs)
    if result.get("complete") and not result.get("failures"):
        result["status"] = "PASS"
        result["source_absences"] = int(result.get("transport", {}).get("terminal_absences", 0))
        coverage = Path(kwargs["output"]) / "web_coverage.json"
        coverage.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        base.write_checksums(Path(kwargs["output"]), exclude={".http-cache"})
    return result


def apply_admission_status(manifest_path: Path, coverage_path: Path, timeline_path: Path) -> dict:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    web = manifest.get("web", {})
    rates = coverage.get("resolution_rates", {})

    gates = {
        "web_transport_complete": web.get("status") == "PASS" and bool(web.get("complete")),
        "timeline_no_conflicts": timeline.get("status") == "PASS"
        and int(timeline.get("ambiguous_identity_events", 0)) == 0
        and int(timeline.get("security_type_conflicts", 0)) == 0,
        "timeline_no_unresolved_episodes": int(timeline.get("unresolved_episode_records", 0)) == 0,
        "all_unknown_type_observations_resolved_strict_prior": float(rates.get("security_type", 0.0)) == 1.0,
        "all_missing_sector_observations_resolved_strict_prior": float(rates.get("sector", 0.0)) == 1.0,
    }
    ready = all(gates.values())
    manifest["policy_schema"] = POLICY_SCHEMA
    manifest["alias_policy"] = ALIAS_POLICY
    manifest["admission_gates"] = gates
    manifest["admission_status"] = "READY" if ready else "REVIEW_REQUIRED"
    if not ready and manifest.get("status") == "PASS":
        manifest["status"] = "PARTIAL"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("harden-candidates")
    p.add_argument("--canonical-dataset", type=Path, required=True)
    p.add_argument("--candidates-dir", type=Path, required=True)

    p = sub.add_parser("parse-bulk")
    p.add_argument("--sec-dir", type=Path, required=True)
    p.add_argument("--candidates", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)

    p = sub.add_parser("build-plan")
    p.add_argument("--candidates", type=Path, required=True)
    p.add_argument("--timeline", type=Path, required=True)
    p.add_argument("--discovery", type=Path)
    p.add_argument("--output", type=Path, required=True)

    p = sub.add_parser("fetch-web")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--source-sha", required=True)
    p.add_argument("--canonical-hash", required=True)
    p.add_argument("--candidates-sha", required=True)
    p.add_argument("--parser-sha", required=True)
    p.add_argument("--min-interval", type=float, default=0.5)
    p.add_argument("--max-runtime", type=float, default=18000)
    p.add_argument("--probe-limit", type=int, default=0)
    p.add_argument("--no-resume", action="store_true")

    p = sub.add_parser("admission-status")
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--coverage", type=Path, required=True)
    p.add_argument("--timeline", type=Path, required=True)

    args = parser.parse_args()
    if args.cmd == "harden-candidates":
        result = harden_candidates(args.canonical_dataset, args.candidates_dir)
    elif args.cmd == "parse-bulk":
        result = parse_bulk_hardened(args.sec_dir, args.candidates, args.output)
    elif args.cmd == "build-plan":
        result = build_strict_web_plan(args.candidates, args.timeline, args.output, args.discovery)
    elif args.cmd == "fetch-web":
        result = fetch_web_policy(
            plan_path=args.plan,
            output=args.output,
            source_sha=args.source_sha,
            canonical_hash=args.canonical_hash,
            candidates_sha=args.candidates_sha,
            parser_sha=args.parser_sha,
            min_interval=args.min_interval,
            max_runtime=args.max_runtime,
            resume=not args.no_resume,
            probe_limit=args.probe_limit,
        )
        if result.get("status") != "PASS":
            print(json.dumps(result, indent=2, sort_keys=True), flush=True)
            return 2
    elif args.cmd == "admission-status":
        result = apply_admission_status(args.manifest, args.coverage, args.timeline)
    else:
        raise AssertionError(args.cmd)
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
