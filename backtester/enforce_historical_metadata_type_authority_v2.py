#!/usr/bin/env python3
"""Enforce listed-security type source precedence for reconstruction v2.

Form 3/4/5 Table I titles are retained as supplementary instrument evidence but
never admitted as the listed ticker's security type. Positive common/non-common
classification requires an SEC periodic/registration filing where the exact
historical trading symbol and class description co-occur on the filing cover.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from backtester import historical_metadata_reconstruction_v2 as base

SCHEMA = "backtester.historical-metadata-reconstruction-v2.security-type-authority/1"


def demote_bulk(bulk_dir: Path) -> dict:
    path = bulk_dir / "bulk_security_type_sources.csv.gz"
    rows = base.read_gzip_csv(path)
    output = []
    observed = {"common": 0, "non_common": 0, "unknown": 0}
    for row in rows:
        classification = str(row.get("classification") or "unknown")
        observed[classification if classification in observed else "unknown"] += 1
        item = dict(row)
        item["observed_classification"] = classification
        item["classification"] = "unknown"
        item["authority"] = "SUPPLEMENTARY_ONLY_SEC_FORM345_NONDERIVATIVE_TITLE_NOT_LISTED_CLASS_AUTHORITY"
        output.append(item)
    fields = [
        "accession", "filed", "cik", "sec_symbol", "document_type", "classification",
        "observed_classification", "security_title_evidence", "authority", "archive", "archive_sha256",
    ]
    base.write_gzip_csv(path, fields, output)
    coverage_path = bulk_dir / "bulk_coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage.update({
        "security_type_authority_schema": SCHEMA,
        "form345_type_role": "supplementary_only_not_admitted",
        "supplementary_type_observations": observed,
        "admitted_security_type_sources": 0,
    })
    coverage_path.write_text(json.dumps(coverage, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    base.write_checksums(bulk_dir)
    return coverage


def filter_web(web_dir: Path) -> dict:
    path = web_dir / "web_security_type_sources.csv.gz"
    rows = base.read_gzip_csv(path) if path.exists() else []
    allowed_forms = {value.upper() for value in base.PERIODIC_FORMS}
    kept = []
    rejected = []
    for row in rows:
        form = str(row.get("document_type") or "").upper()
        classification = str(row.get("classification") or "unknown")
        evidence = str(row.get("security_title_evidence") or "").strip()
        symbol = base.norm_ticker(row.get("sec_symbol"))
        if form in allowed_forms and classification in {"common", "non_common"} and evidence and symbol:
            item = dict(row)
            item["authority"] = "SEC_PERIODIC_OR_REGISTRATION_COVER_EXACT_TICKER_CLASS_COOCCURRENCE"
            kept.append(item)
        else:
            rejected.append({
                "security_id_hint": row.get("security_id_hint", ""),
                "accession": row.get("accession", ""),
                "filed": row.get("filed", ""),
                "cik": row.get("cik", ""),
                "sec_symbol": row.get("sec_symbol", ""),
                "document_type": form,
                "classification": classification,
                "reason": "not_periodic_registration_exact_ticker_class_authority",
                "source_url": row.get("source_url", ""),
                "source_sha256": row.get("source_sha256", ""),
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
    coverage_path = web_dir / "web_coverage.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage.update({
        "security_type_authority_schema": SCHEMA,
        "security_type_source_rule": "periodic/registration SEC cover exact historical ticker and class co-occurrence",
        "admitted_security_type_sources": len(kept),
        "rejected_non_authoritative_security_type_sources": len(rejected),
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
