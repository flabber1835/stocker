#!/usr/bin/env python3
"""Diagnose 2005/2006 Russell 3000 PDF structure without accepting corpus rows.

Research-only diagnostic. Raw PDF and full extracted text remain ephemeral. Persisted
outputs contain hashes, structural statistics, candidate parser counts, and small samples.
An optional --pdf-output writes the already-fetched PDF to an ephemeral runner path so
subsequent diagnostics can reuse the exact bytes without a second Wayback request.
"""

from __future__ import annotations

import argparse
from collections import Counter
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
from pit_russell_pdf_membership_extract import is_ticker, normalize, query_exact_capture


def run_pdftotext(payload: bytes, mode: str) -> str:
    exe = shutil.which("pdftotext")
    if not exe:
        raise RuntimeError("pdftotext unavailable")
    with tempfile.TemporaryDirectory(prefix="russell-early-diag-") as tmp:
        pdf = Path(tmp) / "source.pdf"
        out = Path(tmp) / "out.txt"
        pdf.write_bytes(payload)
        args = [exe]
        if mode != "plain":
            args.append(f"-{mode}")
        args += [str(pdf), str(out)]
        proc = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode:
            raise RuntimeError(f"pdftotext {mode} rc={proc.returncode}: {proc.stderr[:400]}")
        return out.read_text(errors="replace")


def candidate_terminal_ticker_lines(text: str) -> tuple[list[tuple[str, str]], dict]:
    rows: list[tuple[str, str]] = []
    rejected = Counter()
    for raw in text.splitlines():
        line = normalize(raw.replace("\f", " "))
        if not line:
            continue
        tokens = line.split()
        if len(tokens) < 2:
            rejected["too_short"] += 1
            continue
        ticker = tokens[-1].upper()
        company = normalize(" ".join(tokens[:-1]))
        if not is_ticker(ticker):
            rejected["last_token_not_ticker"] += 1
            continue
        if is_ticker(company) or len(company) < 3:
            rejected["company_invalid"] += 1
            continue
        rows.append((ticker, company))
    return rows, dict(rejected)


def candidate_split_whitespace(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.replace("\f", " ").rstrip()
        if not line.strip():
            continue
        fields = [normalize(x) for x in re.split(r"\s{2,}", line.strip()) if normalize(x)]
        if len(fields) < 2:
            continue
        for idx in range(1, len(fields)):
            ticker = fields[idx].upper()
            company = fields[idx - 1]
            if is_ticker(ticker) and not is_ticker(company) and len(company) >= 3:
                out.append((ticker, company))
    return out


def summarize_pairs(pairs: list[tuple[str, str]]) -> dict:
    by_ticker: dict[str, set[str]] = {}
    for ticker, company in pairs:
        by_ticker.setdefault(ticker, set()).add(company)
    ambiguous = {k: sorted(v) for k, v in by_ticker.items() if len(v) > 1}
    exact = len(set(pairs))
    sample = [{"ticker": t, "company": c} for t, c in list(dict.fromkeys(pairs))[:20]]
    return {
        "rows": len(pairs),
        "exact_unique_pairs": exact,
        "unique_tickers": len(by_ticker),
        "ambiguous_tickers": len(ambiguous),
        "sample": sample,
    }


def structural_summary(text: str) -> dict:
    lines = [normalize(x.replace("\f", " ")) for x in text.splitlines()]
    lines = [x for x in lines if x]
    token_counts = Counter(min(len(x.split()), 20) for x in lines)
    ticker_token_counts = Counter()
    for line in lines:
        ticker_token_counts[sum(1 for token in line.split() if is_ticker(token.upper()))] += 1
    return {
        "nonempty_lines": len(lines),
        "token_count_histogram": dict(sorted(token_counts.items())),
        "ticker_tokens_per_line_histogram": dict(sorted(ticker_token_counts.items())),
        "line_length_min": min((len(x) for x in lines), default=0),
        "line_length_max": max((len(x) for x in lines), default=0),
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", required=True)
    p.add_argument("--timestamp", required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--pdf-output", type=Path, default=None, help="Ephemeral local path for reusing the fetched PDF")
    p.add_argument("--timeout", type=int, default=30)
    p.add_argument("--attempts", type=int, default=5)
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    cap = query_exact_capture(args.url, args.timestamp, args.timeout, args.attempts)
    payload, status, content_type, final_url = archive._request(cap.raw_archive_url, timeout=args.timeout, attempts=args.attempts)
    if status != 200 or not payload.startswith(b"%PDF-"):
        raise RuntimeError(f"not PDF status={status} content_type={content_type!r}")

    pdf_sha256 = hashlib.sha256(payload).hexdigest()
    if args.pdf_output is not None:
        args.pdf_output.parent.mkdir(parents=True, exist_ok=True)
        args.pdf_output.write_bytes(payload)

    modes = {}
    for mode in ("raw", "layout", "plain"):
        text = run_pdftotext(payload, mode)
        terminal, rejected = candidate_terminal_ticker_lines(text)
        split = candidate_split_whitespace(text)
        modes[mode] = {
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "structure": structural_summary(text),
            "terminal_ticker_candidate": summarize_pairs(terminal),
            "terminal_rejections": rejected,
            "split_whitespace_candidate": summarize_pairs(split),
        }

    result = {
        "schema": 2,
        "generated_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "capture": asdict(cap),
        "fetch_final_url": final_url,
        "pdf_sha256": pdf_sha256,
        "pdf_bytes": len(payload),
        "raw_pdf_persisted": False,
        "ephemeral_pdf_reuse": args.pdf_output is not None,
        "full_text_persisted": False,
        "accepted_as_corpus": False,
        "modes": modes,
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "diagnostic.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    summary = [
        "# Early Russell PDF parser diagnostic",
        "",
        "Diagnostic only; no rows are accepted into the corpus.",
        "",
        f"- Capture: `{cap.timestamp}`",
        f"- PDF SHA-256: `{result['pdf_sha256']}`",
        f"- PDF bytes: **{len(payload):,}**",
        f"- Ephemeral local reuse enabled: **{result['ephemeral_pdf_reuse']}**",
        "",
    ]
    for mode, data in modes.items():
        t = data["terminal_ticker_candidate"]
        s = data["split_whitespace_candidate"]
        summary += [
            f"## {mode}",
            f"- Nonempty lines: **{data['structure']['nonempty_lines']:,}**",
            f"- Terminal-ticker candidate: **{t['rows']:,} rows / {t['unique_tickers']:,} unique tickers / {t['ambiguous_tickers']:,} ambiguous**",
            f"- Split-whitespace candidate: **{s['rows']:,} rows / {s['unique_tickers']:,} unique tickers / {s['ambiguous_tickers']:,} ambiguous**",
            "",
        ]
    (args.output_dir / "report.md").write_text("\n".join(summary))
    print(json.dumps({m: {
        "lines": d["structure"]["nonempty_lines"],
        "terminal_unique": d["terminal_ticker_candidate"]["unique_tickers"],
        "split_unique": d["split_whitespace_candidate"]["unique_tickers"],
    } for m, d in modes.items()}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
