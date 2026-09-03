#!/usr/bin/env python3
"""Reconstruct the authenticated 2007 IWV/Russell discovery baseline.

The June-2007 IWV filing establishes an exact, hash-pinned 2,976-row observation
set. The archived two-pass mapper relates those names to validated 2006/2010
Russell snapshots for discovery only. Because the 2010 snapshot is future
information, that mapping is never promoted to point-in-time identity authority.

This module reproduces the archived abbreviation-normalized diagnostic exactly:
2,584 mapped names, 52 ambiguous names, and 340 unmatched names. It packages
those categories into the V4 closure-input shape without changing their meaning:
  * mapped names -> NO_AUTHORITY until strict-prior identity evidence exists;
  * ambiguous names -> AMBIGUOUS;
  * unmatched names -> NO_AUTHORITY with an explicit NAME_UNMATCHED reason.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib.util
import io
import json
import shutil
import sys
from pathlib import Path

SCHEMA = "backtester.historical-metadata-2007-closure-input/1"
EXPECTED_ROWS = 2976
EXPECTED_AMBIGUOUS = 52
EXPECTED_UNMATCHED = 340
EXPECTED_MAPPED = EXPECTED_ROWS - EXPECTED_AMBIGUOUS - EXPECTED_UNMATCHED
DECISION_SESSION = "2007-06-29"
ARCHIVE_ROLE = "IWV_FILED_HOLDINGS_CORROBORATION_ONLY"

SOURCE_FIELDS = [
    "source_row_id", "company_name", "ticker", "membership_authority",
    "membership_source_url", "membership_source_member",
    "membership_source_sha256", "decision_session",
]
ADJ_FIELDS = [
    "source_row_id", "resolution_status", "ticker", "security_id",
    "candidate_cik", "classification", "form_authority", "form",
    "accession", "filed", "usable_after", "source_url", "source_member",
    "source_sha256", "reason_code",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_gzip_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                w = csv.DictWriter(text, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import archived mapper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build(args: argparse.Namespace) -> dict:
    archive = args.archive.resolve()
    mapper_path = archive / "tools/pit_russell_2007_iwv_name_map.py"
    abbrev_path = archive / "tools/pit_russell_2007_iwv_abbrev_map.py"
    russell_2006 = archive / "research/pit_russell_archive/annual_universes/russell3000_2006.csv"
    russell_2010 = archive / "research/pit_russell_archive/annual_universes/russell3000_2010.csv"
    for path in (mapper_path, abbrev_path, russell_2006, russell_2010):
        if not path.is_file():
            raise SystemExit(f"required archived input missing: {path}")

    mapper = load_module(mapper_path, "pit_russell_2007_iwv_name_map")
    abbrev = load_module(abbrev_path, "pit_russell_2007_iwv_abbrev_map")
    pdf = mapper.fetch_iwv_pdf()
    holdings = mapper.extract_holdings(mapper.render_iwv_window(pdf))
    sources = mapper.load_source(russell_2006, 2006) + mapper.load_source(russell_2010, 2010)
    raw_exact = mapper.build_indexes(sources)
    sig_exact: dict[str, list] = {}
    for item in sources:
        sig_exact.setdefault(abbrev.signature(item.company), []).append(item)

    mapped: dict[str, dict] = {}
    ambiguous: dict[str, dict] = {}
    unmatched: dict[str, dict] = {}
    method_counts: dict[str, int] = {}
    for holding in holdings:
        canonical = mapper.canonical_company(holding.company)
        signature = abbrev.signature(holding.company)
        candidates = raw_exact.get(canonical, [])
        ticker = abbrev.unique_ticker(candidates)
        method = "exact_canonical" if ticker else ""
        if not ticker:
            candidates = mapper.prefix_candidates(canonical, sources)
            ticker = abbrev.unique_ticker(candidates)
            method = "literal_prefix" if ticker else ""
        if not ticker:
            candidates = sig_exact.get(signature, [])
            ticker = abbrev.unique_ticker(candidates)
            method = "abbreviation_signature_exact" if ticker else ""
        if not ticker:
            candidates = abbrev.prefix_candidates(signature, sources)
            ticker = abbrev.unique_ticker(candidates)
            method = "abbreviation_signature_prefix" if ticker else ""
        if ticker:
            mapped[holding.company] = {"ticker": ticker, "method": method, "signature": signature}
            method_counts[method] = method_counts.get(method, 0) + 1
        elif candidates:
            ambiguous[holding.company] = {
                "candidate_tickers": sorted({x.ticker for x in candidates}),
                "signature": signature,
            }
        else:
            unmatched[holding.company] = {"signature": signature}

    counts = (len(holdings), len(mapped), len(ambiguous), len(unmatched))
    expected = (EXPECTED_ROWS, EXPECTED_MAPPED, EXPECTED_AMBIGUOUS, EXPECTED_UNMATCHED)
    if counts != expected:
        raise SystemExit(f"2007 archive baseline drift: observed={counts} expected={expected}")
    ticker_counts: dict[str, int] = {}
    for item in mapped.values():
        ticker_counts[item["ticker"]] = ticker_counts.get(item["ticker"], 0) + 1
    duplicate_mapped_tickers = {k: v for k, v in sorted(ticker_counts.items()) if v > 1}
    if duplicate_mapped_tickers:
        raise SystemExit(f"unexpected duplicate mapped tickers: {duplicate_mapped_tickers}")

    out = args.output.resolve()
    if out.exists():
        shutil.rmtree(out)
    evidence = out / "evidence"
    evidence.mkdir(parents=True)
    pdf_member = "iwv_2007_06_30.pdf"
    pdf_path = evidence / pdf_member
    pdf_path.write_bytes(pdf)
    pdf_sha = sha256_file(pdf_path)
    if pdf_sha != mapper.EXPECTED_IWV_PDF_SHA256:
        raise SystemExit(f"IWV PDF hash drift: {pdf_sha}")

    source_rows: list[dict[str, str]] = []
    adjudication_rows: list[dict[str, str]] = []
    diagnostic_rows: list[dict[str, str]] = []
    for ordinal, holding in enumerate(holdings, 1):
        sid = f"2007-{ordinal:04d}"
        item = mapped.get(holding.company)
        ticker = item["ticker"] if item else ""
        source_rows.append({
            "source_row_id": sid,
            "company_name": holding.company,
            "ticker": ticker,
            "membership_authority": ARCHIVE_ROLE,
            "membership_source_url": mapper.IWV_PDF_URL,
            "membership_source_member": pdf_member,
            "membership_source_sha256": pdf_sha,
            "decision_session": DECISION_SESSION,
        })
        if holding.company in ambiguous:
            status = "AMBIGUOUS"
            reason = "ARCHIVE_NAME_MAP_AMBIGUOUS_DISCOVERY_ONLY"
            candidates = ";".join(ambiguous[holding.company]["candidate_tickers"])
            signature = ambiguous[holding.company]["signature"]
        elif holding.company in unmatched:
            status = "NO_AUTHORITY"
            reason = "ARCHIVE_NAME_UNMATCHED_DISCOVERY_ONLY"
            candidates = ""
            signature = unmatched[holding.company]["signature"]
        else:
            status = "NO_AUTHORITY"
            reason = "ARCHIVE_NAME_TO_TICKER_MAP_DISCOVERY_ONLY"
            candidates = ticker
            signature = item["signature"]
        adjudication_rows.append({
            "source_row_id": sid,
            "resolution_status": status,
            "ticker": ticker,
            "security_id": "",
            "candidate_cik": "",
            "classification": "",
            "form_authority": "",
            "form": "",
            "accession": "",
            "filed": "",
            "usable_after": "",
            "source_url": "",
            "source_member": "",
            "source_sha256": "",
            "reason_code": reason,
        })
        diagnostic_rows.append({
            "source_row_id": sid,
            "company_name": holding.company,
            "archive_category": "mapped" if item else ("ambiguous" if holding.company in ambiguous else "unmatched"),
            "archive_ticker": ticker,
            "candidate_tickers": candidates,
            "signature": signature,
            "method": item["method"] if item else "",
        })

    write_gzip_csv(out / "source_holdings_2007.csv.gz", SOURCE_FIELDS, source_rows)
    write_gzip_csv(out / "adjudications_2007.csv.gz", ADJ_FIELDS, adjudication_rows)
    write_gzip_csv(
        out / "archive_mapping_diagnostics_2007.csv.gz",
        ["source_row_id", "company_name", "archive_category", "archive_ticker", "candidate_tickers", "signature", "method"],
        diagnostic_rows,
    )

    manifest = {
        "schema": SCHEMA,
        "target_year": 2007,
        "expected_rows": EXPECTED_ROWS,
        "archive_commit": args.archive_commit,
        "archive_mapper_sha256": sha256_file(mapper_path),
        "archive_abbrev_mapper_sha256": sha256_file(abbrev_path),
        "archive_russell_2006_sha256": sha256_file(russell_2006),
        "archive_russell_2010_sha256": sha256_file(russell_2010),
        "iwv_pdf_sha256": pdf_sha,
        "iwv_holdings_rows_sha256": mapper.EXPECTED_HOLDINGS_ROWS_SHA256,
        "membership_role": ARCHIVE_ROLE,
        "certification_membership_authority": False,
        "baseline_mapped_discovery": len(mapped),
        "baseline_ambiguous": len(ambiguous),
        "baseline_name_unmatched": len(unmatched),
        "baseline_unclassified": 0,
        "baseline_no_identity_authority": EXPECTED_ROWS - len(ambiguous),
        "duplicate_mapped_tickers": duplicate_mapped_tickers,
        "mapping_method_counts": method_counts,
        "causality_note": "2010 Russell snapshot is future to 2007 and is discovery-only; it cannot certify a 2007 identity.",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    files = sorted(p for p in out.rglob("*") if p.is_file() and p.name != "SHA256SUMS.txt")
    (out / "SHA256SUMS.txt").write_text(
        "".join(f"{sha256_file(p)}  {p.relative_to(out).as_posix()}\n" for p in files),
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--archive-commit", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    build(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
