#!/usr/bin/env python3
"""Extract legacy Russell 3000 company/ticker rows from archived one-record-per-line PDFs.

Research only. Raw archived PDF and Poppler text remain ephemeral. Persisted output
contains provenance, hashes, parser diagnostics, and factual company/ticker rows.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Sequence

import pit_russell_archive_probe as archive
from pit_russell_pdf_membership_extract import MembershipRow, is_ticker, normalize, query_exact_capture

NON_DATA_FRAGMENTS = (
    "russell 3000 index",
    "membership list",
    "company symbol",
    "company ticker",
    "copyright",
    "www.russell",
)
PAGE_RE = re.compile(r"^page\s+\d+", re.IGNORECASE)


def parse_raw_records(text: str) -> list[MembershipRow]:
    """Parse legacy PDFs where Poppler emits one complete constituent per raw line.

    Contract: the final whitespace token is the ticker and all preceding text is the
    company label. Lines without a valid terminal ticker are ignored. Exact duplicate
    company/ticker pairs are deduplicated; conflicting company labels for one ticker are
    preserved for the caller's ambiguity gate.
    """
    rows: list[MembershipRow] = []
    seen: set[tuple[str, str]] = set()
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = normalize(raw.replace("\f", " "))
        if not line:
            continue
        folded = line.casefold()
        if PAGE_RE.match(line) or any(fragment in folded for fragment in NON_DATA_FRAGMENTS):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        ticker = parts[-1]
        if not is_ticker(ticker):
            continue
        company = normalize(" ".join(parts[:-1]))
        if len(company) < 2 or is_ticker(company):
            continue
        key = (ticker.upper(), company)
        if key in seen:
            continue
        seen.add(key)
        rows.append(MembershipRow(ticker.upper(), company, line_no))
    return rows


def pdf_to_raw_text(payload: bytes) -> str:
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        raise RuntimeError("pdftotext is unavailable on this runner")
    with tempfile.TemporaryDirectory(prefix="russell-legacy-") as tmp:
        pdf_path = Path(tmp) / "source.pdf"
        txt_path = Path(tmp) / "source.txt"
        pdf_path.write_bytes(payload)
        proc = subprocess.run(
            [pdftotext, "-raw", str(pdf_path), str(txt_path)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"pdftotext -raw failed rc={proc.returncode}: {proc.stderr.strip()[:500]}"
            )
        return txt_path.read_text(errors="replace")


def write_outputs(output_dir: Path, result: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "membership.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    (output_dir / "report.md").write_text(
        "# Archived legacy Russell 3000 membership extraction\n\n"
        "Research evidence only. Raw PDF/text is not persisted.\n\n"
        f"- Capture: `{result['capture']['timestamp']}`\n"
        f"- Archived original: `{result['capture']['original']}`\n"
        f"- PDF SHA-256: `{result['pdf_sha256']}`\n"
        f"- PDF bytes: **{result['pdf_bytes']:,}**\n"
        f"- Raw non-empty lines: **{result['raw_nonempty_lines']:,}**\n"
        f"- Parsed company/ticker rows: **{result['row_count']:,}**\n"
        f"- Unique tickers: **{result['unique_tickers']:,}**\n"
        f"- Ambiguous tickers: **{len(result['ambiguous_tickers'])}**\n"
        f"- Count gate: **{result['count_gate']}**\n"
        f"- Ambiguity gate: **{result['ambiguity_gate']}**\n"
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", required=True)
    p.add_argument("--timestamp", required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--timeout", type=int, default=30)
    p.add_argument("--attempts", type=int, default=5)
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

    raw_text = pdf_to_raw_text(payload)
    rows = parse_raw_records(raw_text)
    by_ticker: dict[str, set[str]] = {}
    for row in rows:
        by_ticker.setdefault(row.ticker, set()).add(row.company)
    ambiguous = {
        ticker: sorted(companies)
        for ticker, companies in sorted(by_ticker.items())
        if len(companies) > 1
    }
    count_ok = args.min_rows <= len(rows) <= args.max_rows
    ambiguity_ok = not ambiguous
    result = {
        "schema": 1,
        "generated_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "raw_pdf_persisted": False,
        "raw_text_persisted": False,
        "parser_contract": "poppler_raw_one_record_per_line_terminal_ticker_v1",
        "capture": asdict(capture),
        "fetch_final_url": final_url,
        "fetch_content_type": content_type,
        "pdf_sha256": hashlib.sha256(payload).hexdigest(),
        "pdf_bytes": len(payload),
        "raw_text_sha256": hashlib.sha256(raw_text.encode()).hexdigest(),
        "raw_nonempty_lines": sum(1 for line in raw_text.splitlines() if normalize(line.replace("\f", " "))),
        "row_count": len(rows),
        "unique_tickers": len(by_ticker),
        "ambiguous_tickers": ambiguous,
        "count_gate": "PASS" if count_ok else "FAIL",
        "ambiguity_gate": "PASS" if ambiguity_ok else "FAIL",
        "min_rows": args.min_rows,
        "max_rows": args.max_rows,
        "rows": [asdict(row) for row in rows],
    }
    write_outputs(args.output_dir, result)
    print(
        json.dumps(
            {
                "rows": len(rows),
                "unique_tickers": len(by_ticker),
                "ambiguous_tickers": len(ambiguous),
                "count_gate": result["count_gate"],
                "ambiguity_gate": result["ambiguity_gate"],
                "pdf_sha256": result["pdf_sha256"],
            },
            sort_keys=True,
        )
    )
    return 0 if count_ok and ambiguity_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
