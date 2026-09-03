#!/usr/bin/env python3
"""Issuer-safe V4 miner for retained SEC historical-metadata evidence.

The V3 miner used the SEC archive/submissions URL CIK as candidate issuer CIK.
That is unsafe for Forms 3/4/5 because EDGAR ownership filings may be stored
under a reporting-owner CIK. V4 requires the filing's <issuerCik> for ownership
forms, preserves the URL CIK only as source provenance, and remains
candidate-only.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Mapping

from backtester import mine_historical_metadata_candidates_v3 as v3

SCHEMA = "backtester.historical-metadata-reconstruction-v4.issuer-safe-candidate-mine/1"
MERGE_SCHEMA = "backtester.historical-metadata-reconstruction-v4.issuer-safe-candidate-merge/1"
ISSUER_CIK_RE = re.compile(
    r"<issuerCik[^>]*>\s*(?:<!\[CDATA\[)?\s*(\d{1,10})\s*(?:\]\]>)?\s*</issuerCik>",
    re.I | re.S,
)


def valid_cik(value: object) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    return digits.zfill(10) if 1 <= len(digits) <= 10 else ""


def split_ciks(value: object) -> set[str]:
    return {cik for cik in (valid_cik(part) for part in str(value or "").split(";")) if cik}


def issuer_cik_for_filing(*, form: str, raw_text: str, source_cik: str) -> tuple[str, str]:
    """Return issuer CIK and proof type; fail closed for ownership forms."""
    if form not in v3.OWNERSHIP_FORMS:
        return valid_cik(source_cik), "SOURCE_URL_CIK_NON_OWNERSHIP"
    match = ISSUER_CIK_RE.search(raw_text)
    if not match:
        return "", "OWNERSHIP_XML_ISSUER_CIK_MISSING"
    issuer = valid_cik(match.group(1))
    return (issuer, "OWNERSHIP_XML_ISSUER_CIK") if issuer else ("", "OWNERSHIP_XML_ISSUER_CIK_INVALID")


def write_gzip_csv(path: Path, fields: list[str], rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", compresslevel=9, mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
                writer.writeheader()
                for row in rows:
                    writer.writerow({field: row.get(field, "") for field in fields})


def read_gzip_csv(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def target_rows(inventory: Path) -> tuple[list[dict[str, str]], dict[str, list[dict[str, object]]]]:
    rows = read_gzip_csv(inventory)
    by_source_cik: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        target_ciks = split_ciks(row.get("target_ciks"))
        causal_ciks = split_ciks(row.get("timeline_identity_ciks"))
        hint_ciks = split_ciks(row.get("web_plan_ciks"))
        if not target_ciks:
            target_ciks = causal_ciks | hint_ciks
        for source_cik in sorted(target_ciks):
            item: dict[str, object] = dict(row)
            item["_source_target_cik"] = source_cik
            item["_causal_ciks"] = causal_ciks
            item["_hint_ciks"] = hint_ciks
            by_source_cik[source_cik].append(item)
    return rows, by_source_cik


def candidate_authority(issuer_cik: str, episode: Mapping[str, object]) -> str:
    causal = episode.get("_causal_ciks") or set()
    return "CAUSALLY_ESTABLISHED" if issuer_cik in causal else "DISCOVERY_ONLY_HINT"


def source_relation(source_cik: str, episode: Mapping[str, object]) -> str:
    if source_cik in (episode.get("_causal_ciks") or set()):
        return "CAUSAL_TARGET"
    if source_cik in (episode.get("_hint_ciks") or set()):
        return "DISCOVERY_HINT_TARGET"
    return "UNCLASSIFIED_TARGET"


FIELDS = [
    "shard", "security_id", "ticker", "first_session", "last_session", "resolution_route",
    "candidate_cik", "cik_authority", "source_cik", "source_cik_target_relation",
    "issuer_cik_source", "issuer_cik_matches_source", "candidate_kind", "candidate_quality",
    "form", "filed", "accession", "classification", "sic", "evidence_excerpt", "source_url",
    "source_sha256", "artifact_member", "admission_effect",
]


def _base_row(*, shard: str, episode: Mapping[str, object], ticker: str, issuer_cik: str,
              source_cik: str, issuer_cik_source: str, form: str, filed: str, accession: str,
              source_url: str, source_sha256: str, artifact_member: str) -> dict[str, object]:
    return {
        "shard": shard,
        "security_id": episode["security_id"],
        "ticker": ticker,
        "first_session": episode.get("first_session", ""),
        "last_session": episode.get("last_session", ""),
        "resolution_route": episode.get("resolution_route", ""),
        "candidate_cik": issuer_cik,
        "cik_authority": candidate_authority(issuer_cik, episode),
        "source_cik": source_cik,
        "source_cik_target_relation": source_relation(source_cik, episode),
        "issuer_cik_source": issuer_cik_source,
        "issuer_cik_matches_source": str(issuer_cik == source_cik).lower(),
        "form": form,
        "filed": filed,
        "accession": accession,
        "source_url": source_url,
        "source_sha256": source_sha256,
        "artifact_member": artifact_member,
        "admission_effect": "NONE_CANDIDATE_ONLY",
    }


def mine(shard_root: Path, inventory: Path, output: Path, shard: str) -> dict:
    verified_files = v3.verify_checksums(shard_root)
    runner = json.loads((shard_root / "shard_runner_coverage.json").read_text(encoding="utf-8"))
    web = json.loads((shard_root / "web_coverage.json").read_text(encoding="utf-8"))
    if runner.get("status") != "PASS" or str(runner.get("shard")) != shard:
        raise RuntimeError(f"shard runner authority mismatch for {shard}: {runner}")
    if web.get("status") != "PASS" or not web.get("complete"):
        raise RuntimeError(f"shard {shard} is not transport-complete")

    _inventory_rows, by_source_cik = target_rows(inventory)
    manifest = read_gzip_csv(shard_root / "web_source_manifest.csv.gz")
    source_candidates = [
        row for row in manifest
        if row.get("status") == "200" and v3.cik_from_url(str(row.get("url") or "")) in by_source_cik
    ]

    candidate_rows: list[dict[str, object]] = []
    counters = Counter()
    source_hashes_seen: set[str] = set()
    for index, source in enumerate(source_candidates, 1):
        source_url = str(source.get("url") or "")
        source_cik = v3.cik_from_url(source_url)
        member = str(source.get("artifact_member") or "")
        digest = str(source.get("sha256") or "")
        if not member:
            raise RuntimeError(f"HTTP 200 target source lacks artifact_member: {source_url}")
        path = shard_root / member
        if not path.is_file():
            raise RuntimeError(f"raw source missing: {member}")
        actual = v3.sha256_file(path)
        if digest and actual != digest:
            raise RuntimeError(f"raw source hash mismatch: {member}")
        source_hashes_seen.add(actual)
        counters["target_source_objects_verified"] += 1

        if "/submissions/" in source_url.lower():
            counters["target_submission_objects"] += 1
            continue

        raw_text = path.read_bytes().decode("utf-8", errors="replace")
        visible = v3.visible_text(raw_text)
        form, filed, accession, sic = v3.filing_metadata(raw_text, source_url)
        issuer_cik, issuer_cik_source = issuer_cik_for_filing(
            form=form, raw_text=raw_text, source_cik=source_cik
        )
        counters["target_filing_objects"] += 1
        if form in v3.OWNERSHIP_FORMS:
            counters["ownership_filing_objects"] += 1
            if not issuer_cik:
                counters["ownership_missing_or_invalid_issuer_cik"] += 1
                continue
            if issuer_cik != source_cik:
                counters["ownership_source_cik_differs_from_issuer_cik"] += 1
            else:
                counters["ownership_source_cik_matches_issuer_cik"] += 1
        elif not issuer_cik:
            counters["non_ownership_missing_source_cik"] += 1
            continue

        for episode in by_source_cik[source_cik]:
            ticker = str(episode.get("ticker") or "").upper()
            if not ticker or not v3.within_episode_window(
                filed, str(episode.get("first_session") or ""), str(episode.get("last_session") or "")
            ):
                continue
            proofs = v3.explicit_ticker_proofs(raw_text, visible, ticker)
            base = _base_row(
                shard=shard, episode=episode, ticker=ticker, issuer_cik=issuer_cik,
                source_cik=source_cik, issuer_cik_source=issuer_cik_source, form=form, filed=filed,
                accession=accession, source_url=source_url, source_sha256=actual, artifact_member=member,
            )
            if proofs:
                proof_kind, proof_excerpt = proofs[0]
                candidate_rows.append(base | {
                    "candidate_kind": "IDENTITY_EXACT_TICKER",
                    "candidate_quality": proof_kind,
                    "classification": "",
                    "sic": "",
                    "evidence_excerpt": proof_excerpt,
                })
                counters["identity_candidates"] += 1
                if form in v3.OWNERSHIP_FORMS:
                    counters["ownership_identity_candidates_issuer_cik_bound"] += 1

                classification, class_evidence = v3.class_candidate_near_ticker(visible, ticker)
                if classification != "unknown":
                    if form in v3.CURRENT_AUTHORITY_FORMS:
                        quality = "CURRENT_FORM_EXACT_TICKER_CLASS_CANDIDATE"
                    elif form in v3.EXTENDED_CANDIDATE_FORMS:
                        quality = "EXTENDED_FORM_EXACT_TICKER_CLASS_CANDIDATE"
                    elif form in v3.OWNERSHIP_FORMS:
                        quality = "OWNERSHIP_FORM_SUPPLEMENTARY_CLASS_ONLY"
                    else:
                        quality = "OTHER_FORM_EXACT_TICKER_CLASS_CANDIDATE"
                    candidate_rows.append(base | {
                        "candidate_kind": "SECURITY_TYPE_EXACT_TICKER_CLASS",
                        "candidate_quality": quality,
                        "classification": classification,
                        "sic": "",
                        "evidence_excerpt": class_evidence,
                    })
                    counters["security_type_candidates"] += 1
                    counters[f"security_type_{quality}"] += 1

            if sic and (candidate_authority(issuer_cik, episode) == "CAUSALLY_ESTABLISHED" or proofs):
                quality = (
                    "HEADER_SIC_CAUSAL_CIK"
                    if candidate_authority(issuer_cik, episode) == "CAUSALLY_ESTABLISHED"
                    else "HEADER_SIC_SAME_FILING_EXACT_TICKER_BOOTSTRAP"
                )
                candidate_rows.append(base | {
                    "candidate_kind": "SIC_HEADER",
                    "candidate_quality": quality,
                    "classification": "",
                    "sic": sic,
                    "evidence_excerpt": f"STANDARD INDUSTRIAL CLASSIFICATION [{sic}]",
                })
                counters["sic_candidates"] += 1

        if index % 100 == 0 or index == len(source_candidates):
            print(f"[V4 SAFE MINE] shard={shard} sources={index}/{len(source_candidates)} candidates={len(candidate_rows)}", flush=True)

    key_fields = (
        "security_id", "candidate_cik", "candidate_kind", "candidate_quality", "form", "filed",
        "accession", "classification", "sic", "source_sha256",
    )
    chosen: dict[tuple[str, ...], dict[str, object]] = {}
    for row in sorted(candidate_rows, key=lambda item: (str(item.get("source_url", "")), str(item.get("artifact_member", "")))):
        key = tuple(str(row.get(field, "")) for field in key_fields)
        chosen.setdefault(key, row)
    candidate_rows = [chosen[key] for key in sorted(chosen)]

    output.mkdir(parents=True, exist_ok=True)
    write_gzip_csv(output / "candidate_evidence.csv.gz", FIELDS, candidate_rows)
    summary = {
        "schema": SCHEMA,
        "status": "PASS",
        "shard": shard,
        "candidate_only": True,
        "admission_effect": "NONE",
        "issuer_cik_contract": "Forms 3/4/5 require filing <issuerCik>; URL CIK is provenance only",
        "verified_shard_files": verified_files,
        "target_source_objects_considered": len(source_candidates),
        "unique_target_source_hashes_verified": len(source_hashes_seen),
        "candidate_rows": len(candidate_rows),
        "counts": dict(counters),
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def merge(inputs: Path, output: Path, expected_shards: int = 32) -> dict:
    summaries: list[dict] = []
    rows: list[dict[str, str]] = []
    for path in sorted(inputs.rglob("summary.json")):
        summary = json.loads(path.read_text(encoding="utf-8"))
        if summary.get("schema") != SCHEMA or summary.get("status") != "PASS" or summary.get("candidate_only") is not True:
            raise RuntimeError(f"invalid V4 issuer-safe shard summary: {path}")
        summaries.append(summary)
        rows.extend(read_gzip_csv(path.parent / "candidate_evidence.csv.gz"))
    shards = {str(summary.get("shard")) for summary in summaries}
    expected = {f"{index:02d}" for index in range(expected_shards)}
    if shards != expected:
        raise RuntimeError(f"V4 shard mismatch: missing={sorted(expected-shards)} extra={sorted(shards-expected)}")

    key_fields = (
        "security_id", "candidate_cik", "candidate_kind", "candidate_quality", "form", "filed",
        "accession", "classification", "sic", "source_sha256",
    )
    chosen: dict[tuple[str, ...], dict[str, str]] = {}
    for row in sorted(rows, key=lambda item: (str(item.get("source_url", "")), str(item.get("artifact_member", "")))):
        key = tuple(str(row.get(field, "")) for field in key_fields)
        chosen.setdefault(key, row)
    rows = [chosen[key] for key in sorted(chosen)]

    output.mkdir(parents=True, exist_ok=True)
    write_gzip_csv(output / "candidate_evidence.csv.gz", FIELDS, rows)
    by_kind = Counter(row.get("candidate_kind", "") for row in rows)
    by_quality = Counter(row.get("candidate_quality", "") for row in rows)
    episodes_by_kind: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        episodes_by_kind[row.get("candidate_kind", "")].add(row.get("security_id", ""))
    ownership_identity = [
        row for row in rows
        if row.get("candidate_kind") == "IDENTITY_EXACT_TICKER" and row.get("form") in v3.OWNERSHIP_FORMS
    ]
    summary = {
        "schema": MERGE_SCHEMA,
        "status": "PASS",
        "candidate_only": True,
        "admission_effect": "NONE",
        "merged_shards": len(shards),
        "candidate_rows": len(rows),
        "candidate_counts_by_kind": dict(by_kind),
        "candidate_counts_by_quality": dict(by_quality),
        "episodes_with_identity_candidates": len(episodes_by_kind.get("IDENTITY_EXACT_TICKER", set())),
        "episodes_with_security_type_candidates": len(episodes_by_kind.get("SECURITY_TYPE_EXACT_TICKER_CLASS", set())),
        "episodes_with_sic_candidates": len(episodes_by_kind.get("SIC_HEADER", set())),
        "ownership_identity_candidates": len(ownership_identity),
        "ownership_identity_source_cik_mismatches": sum(row.get("issuer_cik_matches_source") == "false" for row in ownership_identity),
        "next_gate": "authority allocation and strict-prior observation audit; candidate corpus alone changes no eligibility",
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("mine")
    p.add_argument("--shard-root", type=Path, required=True)
    p.add_argument("--inventory", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--shard", required=True)
    p = sub.add_parser("merge")
    p.add_argument("--inputs", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--expected-shards", type=int, default=32)
    args = parser.parse_args()
    result = mine(args.shard_root, args.inventory, args.output, args.shard) if args.cmd == "mine" else merge(args.inputs, args.output, args.expected_shards)
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
