#!/usr/bin/env python3
"""Validate a preserved full Russell 3000 membership PDF against its companion CSV.

This validator trusts the PDF's explicit Company/Symbol column structure. Short all-caps
company names are valid company cells and must not be rejected merely because they look
like ticker symbols. Known historical ticker exceptions are accepted only in Symbol cells.
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
import xml.etree.ElementTree as ET

import pit_russell_pdf_membership_extract as base

PRESERVED_SOURCE_TICKER_EXCEPTIONS = {"LTD"}


def fetch(url: str, timeout: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "stocker-pit-russell-research/2"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def is_preserved_ticker(value: str) -> bool:
    ticker = base.normalize(value).upper()
    if ticker in PRESERVED_SOURCE_TICKER_EXCEPTIONS:
        return True
    return base.is_ticker(ticker)


def parse_preserved_bbox(xml_text: str) -> list[base.MembershipRow]:
    root = ET.fromstring(xml_text)
    pages = [e for e in root.iter() if base._tag_name(e.tag) == "page"]
    rows: list[base.MembershipRow] = []
    seen: set[tuple[str, str]] = set()
    inherited = None
    source_line = 0

    for page in pages:
        visual_rows = base._page_visual_rows(page)
        positions = base._choose_column_positions(visual_rows) or inherited
        if positions is None:
            continue
        company_starts, symbol_starts = positions
        if len(company_starts) != len(symbol_starts):
            continue
        inherited = positions
        ordered = sorted(
            [(x, "company") for x in company_starts] + [(x, "symbol") for x in symbol_starts],
            key=lambda item: item[0],
        )
        starts = [x for x, _ in ordered]
        kinds = [kind for _, kind in ordered]

        for words in visual_rows:
            source_line += 1
            if base._header_positions(words):
                continue
            cells: list[list[str]] = [[] for _ in starts]
            for word in words:
                cells[base._assign_column(word.x, starts)].append(word.text)
            values = [base.normalize(" ".join(cell)) for cell in cells]
            for idx in range(1, len(values)):
                if kinds[idx - 1] != "company" or kinds[idx] != "symbol":
                    continue
                company = values[idx - 1]
                ticker = values[idx].upper()
                if not company or len(company) < 2 or not is_preserved_ticker(ticker):
                    continue
                # Column position is authoritative for role. Do not reject a company merely
                # because its text (INTUIT, KEYCORP, NSTAR, etc.) resembles a ticker.
                if company.upper() in {"COMPANY", "NAME", "MEMBERSHIP", "RUSSELL", "INDEX"}:
                    continue
                key = (ticker, company)
                if key in seen:
                    continue
                seen.add(key)
                rows.append(base.MembershipRow(ticker, company, source_line))
    return rows


def canonical_rows(rows: list[base.MembershipRow]) -> list[dict[str, str]]:
    by_ticker: dict[str, str] = {}
    for row in rows:
        ticker = row.ticker.strip().upper()
        company = base.normalize(row.company)
        prior = by_ticker.get(ticker)
        if prior is not None and prior != company:
            raise RuntimeError(f"ambiguous PDF ticker {ticker}: {prior!r} vs {company!r}")
        by_ticker[ticker] = company
    return [{"ticker": t, "company": by_ticker[t]} for t in sorted(by_ticker)]


def rows_hash(rows: list[dict[str, str]]) -> str:
    return hashlib.sha256("".join(f"{r['ticker']}\t{r['company']}\n" for r in rows).encode()).hexdigest()


def csv_membership(payload: bytes) -> set[str]:
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig", errors="strict")))
    if not reader.fieldnames or "Ticker" not in reader.fieldnames or "Company" not in reader.fieldnames:
        raise RuntimeError(f"unexpected CSV header: {reader.fieldnames!r}")
    tickers: set[str] = set()
    companies: dict[str, str] = {}
    for row in reader:
        ticker = base.normalize(row.get("Ticker", "")).upper()
        company = base.normalize(row.get("Company", ""))
        if not ticker:
            continue
        if not is_preserved_ticker(ticker):
            raise RuntimeError(f"invalid non-empty ticker in preserved CSV: {ticker!r}")
        prior = companies.get(ticker)
        if prior is not None and prior != company:
            raise RuntimeError(f"ambiguous CSV ticker {ticker}: {prior!r} vs {company!r}")
        companies[ticker] = company
        tickers.add(ticker)
    return tickers


def write_csv(path: Path, rows: list[dict[str, str]]) -> str:
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(["ticker", "company"])
    writer.writerows((r["ticker"], r["company"]) for r in rows)
    payload = buf.getvalue().encode()
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--membership-date", required=True)
    p.add_argument("--pdf-url", required=True)
    p.add_argument("--csv-url", required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--min-rows", type=int, default=2800)
    p.add_argument("--max-rows", type=int, default=3200)
    p.add_argument("--timeout", type=int, default=60)
    args = p.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    pdf = fetch(args.pdf_url, args.timeout)
    source_csv = fetch(args.csv_url, args.timeout)
    if not pdf.startswith(b"%PDF-"):
        raise RuntimeError("source is not a PDF")

    bbox1 = base._run_pdftotext(pdf, "bbox-layout")
    bbox2 = base._run_pdftotext(pdf, "bbox-layout")
    rows1 = canonical_rows(parse_preserved_bbox(bbox1))
    rows2 = canonical_rows(parse_preserved_bbox(bbox2))
    deterministic = rows1 == rows2 and rows_hash(rows1) == rows_hash(rows2)
    csv_tickers = csv_membership(source_csv)
    pdf_tickers = {r["ticker"] for r in rows1}
    missing_from_pdf = sorted(csv_tickers - pdf_tickers)
    missing_from_csv = sorted(pdf_tickers - csv_tickers)
    count_ok = args.min_rows <= len(rows1) <= args.max_rows
    crosscheck_ok = not missing_from_pdf and not missing_from_csv

    canonical_path = args.output_dir / f"russell3000_{args.year}.csv"
    canonical_sha = write_csv(canonical_path, rows1)
    result = {
        "schema": 2,
        "generated_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "year": args.year,
        "membership_date": args.membership_date,
        "membership_date_basis": "date encoded by preserved Russell membership-list source filename",
        "pit_effective_boundary_status": "NOT_YET_CERTIFIED",
        "source_pdf_url": args.pdf_url,
        "source_csv_url": args.csv_url,
        "source_pdf_sha256": hashlib.sha256(pdf).hexdigest(),
        "source_pdf_bytes": len(pdf),
        "source_csv_sha256": hashlib.sha256(source_csv).hexdigest(),
        "parser_contract": "preserved_full_membership_structural_company_symbol_columns_v2",
        "row_count": len(rows1),
        "unique_tickers": len(pdf_tickers),
        "rows_sha256": rows_hash(rows1),
        "canonical_csv_sha256": canonical_sha,
        "count_gate": "PASS" if count_ok else "FAIL",
        "determinism_gate": "PASS" if deterministic else "FAIL",
        "pdf_csv_membership_gate": "PASS" if crosscheck_ok else "FAIL",
        "missing_from_pdf": missing_from_pdf,
        "missing_from_csv": missing_from_csv,
        "preserved_source_ticker_exceptions": sorted(PRESERVED_SOURCE_TICKER_EXCEPTIONS),
        "evidence_grade": "A_SOURCE_MEMBERSHIP" if count_ok and deterministic and crosscheck_ok else "UNACCEPTED",
    }
    (args.output_dir / "manifest.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))
    return 0 if count_ok and deterministic and crosscheck_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
