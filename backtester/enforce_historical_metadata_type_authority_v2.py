#!/usr/bin/env python3
"""Enforce listed-security type source precedence for reconstruction v2.

Form 3/4/5 Table I titles are retained as supplementary instrument evidence but
never admitted as the listed ticker's security type. Positive common/non-common
classification requires an SEC periodic/registration filing where the exact
historical trading symbol and class description co-occur on the same filing.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
from pathlib import Path

from backtester import historical_metadata_reconstruction_v2 as base

SCHEMA = "backtester.historical-metadata-reconstruction-v2.security-type-authority/2"


def demote_bulk(bulk_dir: Path) -> dict:
    path = bulk_dir / "bulk_security_type_sources.csv.gz"
    tmp = bulk_dir / ".bulk_security_type_sources.demoted.csv.gz"
    observed = {"common": 0, "non_common": 0, "unknown": 0}
    fields = [
        "accession", "filed", "cik", "sec_symbol", "document_type", "classification",
        "observed_classification", "security_title_evidence", "authority", "archive", "archive_sha256",
    ]

    def rows():
        with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                classification = str(row.get("classification") or "unknown")
                observed[classification if classification in observed else "unknown"] += 1
                item = dict(row)
                item["observed_classification"] = classification
                item["classification"] = "unknown"
                item["authority"] = "SUPPLEMENTARY_ONLY_SEC_FORM345_NONDERIVATIVE_TITLE_NOT_LISTED_CLASS_AUTHORITY"
                yield item

    base.write_gzip_csv(tmp, fields, rows())
    tmp.replace(path)
    coverage_path = bulk_dir / "bulk_coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage.update({
        "security_type_authority_schema": SCHEMA,
        "form345_type_role": "supplementary_only_not_admitted",
        "supplementary_type_observations": observed,
        "admitted_security_type_sources": 0,
        "demotion_mode": "streaming_bounded_memory",
    })
    coverage_path.write_text(json.dumps(coverage, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    base.write_checksums(bulk_dir)
    return coverage


def filter_web(web_dir: Path) -> dict:
    path = web_dir / "web_security_type_sources.csv.gz"
    rows = base.read_gzip_csv(path) if path.exists() else []
    identity_rows = base.read_gzip_csv(web_dir / "web_identity_sources.csv.gz") if (web_dir / "web_identity_sources.csv.gz").exists() else []
    identity_keys = {
        (
            str(row.get("accession") or ""),
            base.validate_cik(row.get("cik")),
            base.norm_ticker(row.get("sec_symbol")),
            str(row.get("source_sha256") or ""),
        )
        for row in identity_rows
        if str(row.get("accession") or "") and base.validate_cik(row.get("cik")) and base.norm_ticker(row.get("sec_symbol"))
    }
    allowed_forms = {value.upper() for value in base.PERIODIC_FORMS}
    kept = []
    rejected = []
    for row in rows:
        form = str(row.get("document_type") or "").upper()
        classification = str(row.get("classification") or "unknown")
        evidence = str(row.get("security_title_evidence") or "").strip()
        symbol = base.norm_ticker(row.get("sec_symbol"))
        cik = base.validate_cik(row.get("cik"))
        accession = str(row.get("accession") or "")
        source_sha = str(row.get("source_sha256") or "")
        same_filing_identity = (accession, cik, symbol, source_sha) in identity_keys
        if (
            form in allowed_forms
            and classification in {"common", "non_common"}
            and evidence
            and symbol
            and cik
            and accession
            and source_sha
            and same_filing_identity
        ):
            item = dict(row)
            item["authority"] = "SEC_PERIODIC_OR_REGISTRATION_SAME_FILING_EXACT_TICKER_IDENTITY_AND_CLASS"
            kept.append(item)
        else:
            rejected.append({
                "security_id_hint": row.get("security_id_hint", ""),
                "accession": accession,
                "filed": row.get("filed", ""),
                "cik": cik,
                "sec_symbol": symbol,
                "document_type": form,
                "classification": classification,
                "reason": (
                    "missing_same_filing_exact_ticker_identity_proof"
                    if not same_filing_identity
                    else "not_periodic_registration_exact_ticker_class_authority"
                ),
                "source_url": row.get("source_url", ""),
                "source_sha256": source_sha,
            })
    fields = [
        "security_id_hint", "accession", "filed", "cik", "sec_symbol", "document_type", "classification",
        "security_title_evidence", "authority", "source_url", "source_sha256",
    ]
    base.write_gzip_csv(path, fields, kept)
    base.write_gzip_csv(web_dir / "web_security_type_rejected.csv.gz", [
        "security_id_hint", "accession", "filed", "cik", "sec_symbol", "document_type",
        "classification", "reason", "source_url", "source_sha256",
    ], rejected)

    sic_rows = base.read_gzip_csv(web_dir / "web_sic_sources.csv.gz") if (web_dir / "web_sic_sources.csv.gz").exists() else []
    normalized_evidence = base.normalized_web_evidence_hash(identity_rows, kept, sic_rows)

    checkpoint_path = web_dir / "checkpoint.json"
    if checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        checkpoint["normalized_evidence_sha256"] = normalized_evidence
        checkpoint["security_type_authority_schema"] = SCHEMA
        checkpoint["post_fetch_security_type_authority_filter"] = True
        checkpoint_path.write_text(json.dumps(checkpoint, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    coverage_path = web_dir / "web_coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage.update({
        "security_type_authority_schema": SCHEMA,
        "security_type_source_rule": "periodic/registration same-source exact historical ticker identity proof plus class description",
        "admitted_security_type_sources": len(kept),
        "rejected_non_authoritative_security_type_sources": len(rejected),
        "normalized_evidence_sha256": normalized_evidence,
    })
    coverage_path.write_text(json.dumps(coverage, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    base.write_checksums(web_dir, exclude={".http-cache"})
    return coverage


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("demote-bulk")
    p.add_argument("--bulk-dir", type=Path, required=True)
    p = sub.add_parser("filter-web")
    p.add_argument("--web-dir", type=Path, required=True)
    args = parser.parse_args()
    result = demote_bulk(args.bulk_dir) if args.cmd == "demote-bulk" else filter_web(args.web_dir)
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
