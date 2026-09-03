#!/usr/bin/env python3
"""Extract factual company/ticker membership rows from one archived Russell PDF.

Research only. The archived PDF and its pdftotext representation remain ephemeral.
Persisted output contains provenance, integrity hashes, parser diagnostics, and factual
company/ticker rows used for reconstruction validation.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, UTC
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Sequence

import pit_russell_archive_probe as archive

TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
EXCLUDED = {
    "RUSSELL", "INDEX", "TICKER", "SYMBOL", "COMPANY", "NAME", "FINAL",
    "MEMBERSHIP", "PAGE", "INC", "CORP", "LLC", "LTD", "NYSE", "NASDAQ",
    "AMEX", "OTC", "US", "USA",
}


@dataclass(frozen=True)
class MembershipRow:
    ticker: str
    company: str
    source_line: int


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def is_ticker(value: str) -> bool:
    value = normalize(value)
    upper = value.upper()
    return value == upper and TICKER_RE.fullmatch(upper) is not None and upper not in EXCLUDED


def parse_layout_text(text: str) -> list[MembershipRow]:
    """Parse layout-preserving text into adjacent Company | Symbol pairs.

    Historical Russell PDFs use one or more company/symbol column pairs. We split
    only on runs of two or more spaces, preserving spaces inside company names, then
    pair each ticker-like field with the immediately preceding non-ticker field.
    """
    rows: list[MembershipRow] = []
    seen: set[tuple[str, str]] = set()
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.replace("\f", " ").rstrip()
        if not line.strip():
            continue
        fields = [normalize(x) for x in re.split(r"\s{2,}", line.strip()) if normalize(x)]
        if len(fields) < 2:
            continue
        for idx in range(1, len(fields)):
            ticker = fields[idx]
            company = fields[idx - 1]
            if not is_ticker(ticker):
                continue
            if is_ticker(company) or company.upper() in EXCLUDED or len(company) < 3:
                continue
            key = (ticker.upper(), company)
            if key in seen:
                continue
            seen.add(key)
            rows.append(MembershipRow(ticker.upper(), company, line_no))
    return rows


def query_exact_capture(url: str, timestamp: str, timeout: int, attempts: int) -> archive.Capture:
    year = int(timestamp[:4])
    payload, status, _, _ = archive._request(
        archive.build_cdx_url(url, year, year), timeout=timeout, attempts=attempts
    )
    if status != 200:
        raise RuntimeError(f"CDX HTTP {status}")
    captures = archive.dedupe_captures(archive.parse_cdx_payload(url, payload))
    matches = [row for row in captures if row.timestamp == timestamp]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one CDX capture for {timestamp}, found {len(matches)}; "
            f"available={[row.timestamp for row in captures]}"
        )
    return matches[0]


def pdf_to_layout_text(payload: bytes) -> str:
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        raise RuntimeError("pdftotext is unavailable on this runner")
    with tempfile.TemporaryDirectory(prefix="russell-pdf-") as tmp:
        pdf_path = Path(tmp) / "source.pdf"
        txt_path = Path(tmp) / "source.txt"
        pdf_path.write_bytes(payload)
        proc = subprocess.run(
            [pdftotext, "-layout", str(pdf_path), str(txt_path)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"pdftotext failed rc={proc.returncode}: {proc.stderr.strip()[:500]}")
        return txt_path.read_text(errors="replace")


def write_outputs(output_dir: Path, result: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "membership.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    lines = [
        "# Archived Russell 3000 membership extraction",
        "",
        "Research evidence only. Raw PDF/text is not persisted.",
        "",
        f"- Capture: `{result['capture']['timestamp']}`",
        f"- Archived original: `{result['capture']['original']}`",
        f"- PDF SHA-256: `{result['pdf_sha256']}`",
        f"- PDF bytes: **{result['pdf_bytes']:,}**",
        f"- Parsed company/ticker rows: **{result['row_count']:,}**",
        f"- Unique tickers: **{result['unique_tickers']:,}**",
        f"- Ambiguous tickers with multiple company labels: **{len(result['ambiguous_tickers'])}**",
        f"- Count gate: **{result['count_gate']}**",
        "",
    ]
    (output_dir / "report.md").write_text("\n".join(lines))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", required=True)
    p.add_argument("--timestamp", required=True, help="Exact Wayback CDX timestamp")
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--timeout", type=int, default=30)
    p.add_argument("--attempts", type=int, default=4)
    p.add_argument("--min-rows", type=int, default=2500)
    p.add_argument("--max-rows", type=int, default=3500)
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    capture = query_exact_capture(args.url, args.timestamp, args.timeout, args.attempts)
    payload, status, content_type, final_url = archive._request(
        capture.raw_archive_url, timeout=args.timeout, attempts=args.attempts
    )
    if status != 200 or not payload.startswith(b"%PDF-"):
        raise RuntimeError(
            f"archive payload is not a PDF: status={status} content_type={content_type!r} bytes={len(payload)}"
        )
    text = pdf_to_layout_text(payload)
    rows = parse_layout_text(text)
    by_ticker: dict[str, set[str]] = {}
    for row in rows:
        by_ticker.setdefault(row.ticker, set()).add(row.company)
    ambiguous = {
        ticker: sorted(companies)
        for ticker, companies in sorted(by_ticker.items())
        if len(companies) > 1
    }
    count_ok = args.min_rows <= len(rows) <= args.max_rows
    result = {
        "schema": 1,
        "generated_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "raw_pdf_persisted": False,
        "raw_text_persisted": False,
        "parser_contract": "pdftotext_layout_then_adjacent_company_symbol",
        "capture": asdict(capture),
        "fetch_final_url": final_url,
        "fetch_content_type": content_type,
        "pdf_sha256": hashlib.sha256(payload).hexdigest(),
        "pdf_bytes": len(payload),
        "row_count": len(rows),
        "unique_tickers": len(by_ticker),
        "ambiguous_tickers": ambiguous,
        "count_gate": "PASS" if count_ok else "FAIL",
        "min_rows": args.min_rows,
        "max_rows": args.max_rows,
        "rows": [asdict(row) for row in rows],
    }
    write_outputs(args.output_dir, result)
    print(json.dumps({
        "rows": len(rows),
        "unique_tickers": len(by_ticker),
        "ambiguous_tickers": len(ambiguous),
        "count_gate": result["count_gate"],
        "pdf_sha256": result["pdf_sha256"],
    }, sort_keys=True))
    return 0 if count_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
