#!/usr/bin/env python3
"""Validate one preserved full Russell 3000 membership PDF against its companion CSV.

Research-only corpus construction. The PDF and source CSV are fetched from the public
preservation repository, parsed deterministically, cross-checked on ticker membership,
and converted into a canonical annual universe plus machine-readable provenance.
"""

from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
import hashlib
import io
import json
from pathlib import Path
import urllib.request

import pit_russell_pdf_membership_extract as pdfparse


def fetch(url: str, timeout: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "stocker-pit-russell-research/1"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def canonical_rows(rows: list[pdfparse.MembershipRow]) -> list[dict[str, str]]:
    by_ticker: dict[str, str] = {}
    for row in rows:
        ticker = row.ticker.strip().upper()
        company = pdfparse.normalize(row.company)
        prior = by_ticker.get(ticker)
        if prior is not None and prior != company:
            raise RuntimeError(f"ambiguous PDF ticker {ticker}: {prior!r} vs {company!r}")
        by_ticker[ticker] = company
    return [{"ticker": ticker, "company": by_ticker[ticker]} for ticker in sorted(by_ticker)]


def rows_hash(rows: list[dict[str, str]]) -> str:
    payload = "".join(f"{row['ticker']}\t{row['company']}\n" for row in rows).encode()
    return hashlib.sha256(payload).hexdigest()


def csv_membership(payload: bytes) -> tuple[set[str], dict[str, str]]:
    text = payload.decode("utf-8-sig", errors="strict")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or "Ticker" not in reader.fieldnames or "Company" not in reader.fieldnames:
        raise RuntimeError(f"unexpected CSV header: {reader.fieldnames!r}")
    tickers: set[str] = set()
    companies: dict[str, str] = {}
    for row in reader:
        ticker = pdfparse.normalize(row.get("Ticker", "")).upper()
        company = pdfparse.normalize(row.get("Company", ""))
        if not ticker:
            continue
        if not pdfparse.is_ticker(ticker):
            raise RuntimeError(f"invalid non-empty ticker in preserved CSV: {ticker!r}")
        prior = companies.get(ticker)
        if prior is not None and prior != company:
            raise RuntimeError(f"ambiguous CSV ticker {ticker}: {prior!r} vs {company!r}")
        tickers.add(ticker)
        companies[ticker] = company
    return tickers, companies


def write_canonical_csv(path: Path, rows: list[dict[str, str]]) -> str:
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["ticker", "company"])
    for row in rows:
        writer.writerow([row["ticker"], row["company"]])
    payload = buf.getvalue().encode()
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--effective-date", required=True)
    p.add_argument("--pdf-url", required=True)
    p.add_argument("--csv-url", required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--min-rows", type=int, default=2800)
    p.add_argument("--max-rows", type=int, default=3200)
    p.add_argument("--timeout", type=int, default=60)
    args = p.parse_args()

    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    pdf = fetch(args.pdf_url, args.timeout)
    source_csv = fetch(args.csv_url, args.timeout)
    if not pdf.startswith(b"%PDF-"):
        raise RuntimeError(f"source is not PDF: {args.pdf_url}")

    bbox1 = pdfparse._run_pdftotext(pdf, "bbox-layout")
    bbox2 = pdfparse._run_pdftotext(pdf, "bbox-layout")
    rows1 = canonical_rows(pdfparse.parse_bbox_xml(bbox1))
    rows2 = canonical_rows(pdfparse.parse_bbox_xml(bbox2))
    hash1 = rows_hash(rows1)
    hash2 = rows_hash(rows2)
    deterministic = rows1 == rows2 and hash1 == hash2

    csv_tickers, _ = csv_membership(source_csv)
    pdf_tickers = {row["ticker"] for row in rows1}
    missing_from_pdf = sorted(csv_tickers - pdf_tickers)
    missing_from_csv = sorted(pdf_tickers - csv_tickers)
    row_count = len(rows1)
    count_ok = args.min_rows <= row_count <= args.max_rows
    crosscheck_ok = not missing_from_pdf and not missing_from_csv

    canonical_path = out / f"russell3000_{args.year}.csv"
    canonical_sha = write_canonical_csv(canonical_path, rows1)
    result = {
        "schema": 1,
        "generated_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "year": args.year,
        "effective_date": args.effective_date,
        "source_pdf_url": args.pdf_url,
        "source_csv_url": args.csv_url,
        "source_pdf_sha256": hashlib.sha256(pdf).hexdigest(),
        "source_pdf_bytes": len(pdf),
        "source_csv_sha256": hashlib.sha256(source_csv).hexdigest(),
        "parser_contract": "preserved_full_membership_pdf_bbox_header_columns_v1",
        "row_count": row_count,
        "unique_tickers": len(pdf_tickers),
        "rows_sha256": hash1,
        "canonical_csv_sha256": canonical_sha,
        "count_gate": "PASS" if count_ok else "FAIL",
        "determinism_gate": "PASS" if deterministic else "FAIL",
        "pdf_csv_membership_gate": "PASS" if crosscheck_ok else "FAIL",
        "missing_from_pdf": missing_from_pdf,
        "missing_from_csv": missing_from_csv,
        "evidence_grade": "A" if count_ok and deterministic and crosscheck_ok else "UNACCEPTED",
    }
    (out / "manifest.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))

    if not count_ok or not deterministic or not crosscheck_ok:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
