#!/usr/bin/env python3
"""Extract Russell 3000 reconstitution additions/deletions from official dated PDFs.

Research only. The raw PDF and Poppler text remain ephemeral. Output records source
hashes and deterministic factual company/ticker rows; it does not by itself establish
publication-time causality.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Sequence
import urllib.request

from pit_russell_pdf_membership_extract import is_ticker, normalize

INDUSTRIES = tuple(sorted((
    "Consumer Discretionary",
    "Consumer Staples",
    "Basic Materials",
    "Telecommunications",
    "Real Estate",
    "Health Care",
    "Technology",
    "Financials",
    "Industrials",
    "Utilities",
    "Energy",
), key=len, reverse=True))
NON_DATA = (
    "russell 3000", "reconstitution", "company symbol industry", "ftse russell",
    "lseg.com", "final index", "preliminary index", "russell us indexes",
)


@dataclass(frozen=True)
class DeltaRow:
    ticker: str
    company: str
    industry: str
    source_line: int


def fetch_pdf(url: str, timeout: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "stocker-pit-russell-research/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = response.read()
    if not payload.startswith(b"%PDF-"):
        raise RuntimeError(f"source is not PDF: {url}")
    return payload


def pdf_to_layout(payload: bytes) -> str:
    exe = shutil.which("pdftotext")
    if not exe:
        raise RuntimeError("pdftotext unavailable")
    with tempfile.TemporaryDirectory(prefix="russell-delta-") as tmp:
        pdf = Path(tmp) / "source.pdf"
        txt = Path(tmp) / "source.txt"
        pdf.write_bytes(payload)
        proc = subprocess.run([exe, "-layout", str(pdf), str(txt)], capture_output=True, text=True)
        if proc.returncode:
            raise RuntimeError(f"pdftotext failed rc={proc.returncode}: {proc.stderr[:400]}")
        return txt.read_text(errors="replace")


def parse_layout(text: str) -> list[DeltaRow]:
    rows: list[DeltaRow] = []
    seen: set[tuple[str, str, str]] = set()
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = normalize(raw.replace("\f", " "))
        if not line:
            continue
        folded = line.casefold()
        if any(fragment in folded for fragment in NON_DATA):
            continue
        industry = next((name for name in INDUSTRIES if line.endswith(name)), None)
        if industry is None:
            continue
        prefix = normalize(line[:-len(industry)])
        parts = prefix.split()
        if len(parts) < 2:
            continue
        ticker = parts[-1].upper()
        company = normalize(" ".join(parts[:-1]))
        if not is_ticker(ticker) or not company:
            continue
        key = (ticker, company, industry)
        if key in seen:
            continue
        seen.add(key)
        rows.append(DeltaRow(ticker, company, industry, line_no))
    return rows


def rows_sha256(rows: Sequence[DeltaRow]) -> str:
    canonical = json.dumps(
        [{"ticker": r.ticker, "company": r.company, "industry": r.industry} for r in rows],
        ensure_ascii=False, separators=(",", ":"),
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", required=True)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--kind", choices=("additions", "deletions"), required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--timeout", type=int, default=30)
    p.add_argument("--min-rows", type=int, default=20)
    p.add_argument("--max-rows", type=int, default=500)
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    payload = fetch_pdf(args.url, args.timeout)
    text = pdf_to_layout(payload)
    rows1 = parse_layout(text)
    rows2 = parse_layout(text)
    deterministic = rows1 == rows2
    by_ticker: dict[str, set[str]] = {}
    for row in rows1:
        by_ticker.setdefault(row.ticker, set()).add(row.company)
    ambiguous = {k: sorted(v) for k, v in sorted(by_ticker.items()) if len(v) > 1}
    count_ok = args.min_rows <= len(rows1) <= args.max_rows
    result = {
        "schema": 1,
        "generated_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "year": args.year,
        "kind": args.kind,
        "source_url": args.url,
        "raw_pdf_persisted": False,
        "raw_text_persisted": False,
        "parser_contract": "poppler_layout_terminal_icb_industry_preceding_symbol_v1",
        "pdf_sha256": hashlib.sha256(payload).hexdigest(),
        "pdf_bytes": len(payload),
        "layout_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "row_count": len(rows1),
        "unique_tickers": len(by_ticker),
        "ambiguous_tickers": ambiguous,
        "rows_sha256": rows_sha256(rows1),
        "count_gate": "PASS" if count_ok else "FAIL",
        "ambiguity_gate": "PASS" if not ambiguous else "FAIL",
        "determinism_gate": "PASS" if deterministic else "FAIL",
        "rows": [asdict(row) for row in rows1],
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "delta.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    (args.output_dir / "report.md").write_text(
        f"# Russell 3000 {args.year} {args.kind}\n\n"
        f"- Source: `{args.url}`\n"
        f"- PDF SHA-256: `{result['pdf_sha256']}`\n"
        f"- Rows: **{len(rows1)}**\n"
        f"- Unique tickers: **{len(by_ticker)}**\n"
        f"- Ambiguous tickers: **{len(ambiguous)}**\n"
        f"- Rows SHA-256: `{result['rows_sha256']}`\n"
        f"- Count gate: **{result['count_gate']}**\n"
        f"- Ambiguity gate: **{result['ambiguity_gate']}**\n"
        f"- Determinism gate: **{result['determinism_gate']}**\n"
    )
    print(json.dumps({k: result[k] for k in (
        "year", "kind", "row_count", "unique_tickers", "pdf_sha256", "rows_sha256",
        "count_gate", "ambiguity_gate", "determinism_gate"
    )}, sort_keys=True))
    return 0 if count_ok and not ambiguous and deterministic else 2


if __name__ == "__main__":
    raise SystemExit(main())
