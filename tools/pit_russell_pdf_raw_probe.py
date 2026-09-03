#!/usr/bin/env python3
"""Diagnose Poppler raw-text ordering for archived Russell membership PDFs.

Research only. Raw PDF/text stays ephemeral. Persisted output contains structural
statistics, hashes, and a very small factual sample sufficient to define a parser.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
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
from pit_russell_pdf_membership_extract import is_ticker, normalize, query_exact_capture

HEADER_WORDS = {
    "company", "symbol", "ticker", "russell", "russell 3000", "membership",
    "russell 3000 index", "company symbol", "company ticker",
}


def classify_line(value: str) -> str:
    text = normalize(value)
    if not text:
        return "blank"
    folded = text.casefold()
    if folded in HEADER_WORDS or ("company" in folded and ("symbol" in folded or "ticker" in folded)):
        return "header"
    if is_ticker(text):
        return "ticker"
    if re.fullmatch(r"[\d\s./-]+", text):
        return "numeric"
    if any(ch.isalpha() for ch in text):
        return "text"
    return "other"


def raw_structure(text: str, sample_limit: int = 24) -> dict:
    rows = []
    for raw in text.splitlines():
        value = normalize(raw.replace("\f", " "))
        if not value:
            continue
        rows.append((value, classify_line(value)))

    classes = [kind for _, kind in rows]
    transitions = Counter(zip(classes, classes[1:]))
    class_counts = Counter(classes)

    preceding_candidates: list[tuple[str, str]] = []
    following_candidates: list[tuple[str, str]] = []
    for idx, (value, kind) in enumerate(rows):
        if kind == "ticker" and idx > 0 and rows[idx - 1][1] == "text":
            preceding_candidates.append((value, rows[idx - 1][0]))
        if kind == "ticker" and idx + 1 < len(rows) and rows[idx + 1][1] == "text":
            following_candidates.append((value, rows[idx + 1][0]))

    # Keep a tiny sample only. The probe exists to determine structural ordering;
    # it is not a mechanism for republishing the constituent document.
    samples = []
    for ticker, company in preceding_candidates[:sample_limit]:
        samples.append({"direction": "preceding", "ticker": ticker, "company": company})
    remaining = max(0, sample_limit - len(samples))
    for ticker, company in following_candidates[:remaining]:
        samples.append({"direction": "following", "ticker": ticker, "company": company})

    return {
        "nonempty_lines": len(rows),
        "class_counts": dict(sorted(class_counts.items())),
        "transition_counts": {
            f"{a}->{b}": count
            for (a, b), count in sorted(transitions.items())
        },
        "preceding_company_candidates": len(preceding_candidates),
        "following_company_candidates": len(following_candidates),
        "preceding_unique_tickers": len({ticker for ticker, _ in preceding_candidates}),
        "following_unique_tickers": len({ticker for ticker, _ in following_candidates}),
        "sample": samples,
        "structure_prefix": [
            {
                "index": idx,
                "class": kind,
                "chars": len(value),
                "tokens": len(value.split()),
            }
            for idx, (value, kind) in enumerate(rows[:80])
        ],
    }


def pdf_to_raw_text(payload: bytes) -> str:
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        raise RuntimeError("pdftotext is unavailable")
    with tempfile.TemporaryDirectory(prefix="russell-raw-") as tmp:
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
            raise RuntimeError(f"pdftotext -raw failed rc={proc.returncode}: {proc.stderr.strip()[:500]}")
        return txt_path.read_text(errors="replace")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--timestamp", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--attempts", type=int, default=5)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    capture = query_exact_capture(args.url, args.timestamp, args.timeout, args.attempts)
    payload, status, content_type, final_url = archive._request(
        capture.raw_archive_url, timeout=args.timeout, attempts=args.attempts
    )
    if status != 200 or not payload.startswith(b"%PDF-"):
        raise RuntimeError(f"not a PDF: status={status} content_type={content_type!r}")
    raw_text = pdf_to_raw_text(payload)
    structure = raw_structure(raw_text)
    result = {
        "schema": 1,
        "generated_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "raw_pdf_persisted": False,
        "raw_text_persisted": False,
        "capture": asdict(capture),
        "fetch_final_url": final_url,
        "pdf_sha256": hashlib.sha256(payload).hexdigest(),
        "pdf_bytes": len(payload),
        "raw_text_sha256": hashlib.sha256(raw_text.encode()).hexdigest(),
        "structure": structure,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "raw_structure.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    (args.output_dir / "report.md").write_text(
        "# Russell PDF raw ordering probe\n\n"
        "Research diagnostics only. Raw PDF/text is not persisted.\n\n"
        f"- Capture: `{capture.timestamp}`\n"
        f"- Nonempty raw lines: **{structure['nonempty_lines']:,}**\n"
        f"- Ticker lines: **{structure['class_counts'].get('ticker', 0):,}**\n"
        f"- Ticker with preceding text: **{structure['preceding_company_candidates']:,}**\n"
        f"- Ticker with following text: **{structure['following_company_candidates']:,}**\n"
        f"- Preceding unique tickers: **{structure['preceding_unique_tickers']:,}**\n"
        f"- Following unique tickers: **{structure['following_unique_tickers']:,}**\n"
    )
    print(json.dumps({
        "nonempty_lines": structure["nonempty_lines"],
        "ticker_lines": structure["class_counts"].get("ticker", 0),
        "preceding_candidates": structure["preceding_company_candidates"],
        "following_candidates": structure["following_company_candidates"],
        "preceding_unique_tickers": structure["preceding_unique_tickers"],
        "following_unique_tickers": structure["following_unique_tickers"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
