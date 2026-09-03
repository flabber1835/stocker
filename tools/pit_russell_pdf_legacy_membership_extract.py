#!/usr/bin/env python3
"""Extract 2005/2006 Russell 3000 membership from measured PDF geometry.

Research only. Raw archived PDF and Poppler bbox XML remain ephemeral. The early
Russell PDFs use two side-by-side ticker/company groups. Membership acceptance is
anchored to the measured ticker starts at x=90 and x=330 and fails closed on source
hash changes, anchored ticker rows without company text, conflicting ticker labels, or
non-deterministic row reconstruction.
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
import xml.etree.ElementTree as ET

import pit_russell_archive_probe as archive
from pit_russell_pdf_membership_extract import MembershipRow, normalize, query_exact_capture


EXPECTED_PDF_SHA256 = {
    "20051030075845": "d849ad9c3c6f08aaa4f8acc3351b046211ed27f54bb1599b3d3ca01ca99d595b",
    "20060710045437": "18080cd078342b05dba51f2fe75b1d1c0dd85de1a8e715fc0ce18090a44d7024",
}

# The company tab is normally near 135/375, but pages 11 and 20 prove that it can
# move left. The ticker starts remain stable, so each half-page is delimited by its
# ticker anchor and the next half-page boundary.
GROUPS = ((90.0, 306.0), (330.0, 612.0))
NOMINAL_COMPANY_STARTS = (135.0, 375.0)
ANCHOR_TOLERANCE = 3.0
Y_TOLERANCE = 1.5
EARLY_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
NON_DATA_ANCHORS = {"TICKER", "SYMBOL", "COMPANY", "NAME", "RUSSELL", "INDEX", "MEMBERSHIP", "PAGE", "FINAL"}


@dataclass(frozen=True)
class PositionedWord:
    x: float
    y: float
    text: str


@dataclass(frozen=True)
class ParseIssue:
    page: int
    visual_row: int
    side: int
    reason: str
    ticker_cell: str
    company_cell: str


def _tag_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _visual_rows(page: ET.Element) -> list[list[PositionedWord]]:
    fragments: list[tuple[float, list[PositionedWord]]] = []
    for line in page.iter():
        if _tag_name(line.tag) != "line":
            continue
        words: list[PositionedWord] = []
        for word in line.iter():
            if _tag_name(word.tag) != "word":
                continue
            text = normalize("".join(word.itertext()))
            if not text:
                continue
            words.append(
                PositionedWord(
                    x=float(word.attrib.get("xMin", line.attrib.get("xMin", "0"))),
                    y=float(word.attrib.get("yMin", line.attrib.get("yMin", "0"))),
                    text=text,
                )
            )
        if words:
            fragments.append((sum(word.y for word in words) / len(words), words))

    fragments.sort(key=lambda item: item[0])
    grouped: list[tuple[float, list[PositionedWord]]] = []
    for y, words in fragments:
        if grouped and abs(y - grouped[-1][0]) <= Y_TOLERANCE:
            old_y, old_words = grouped[-1]
            grouped[-1] = ((old_y + y) / 2.0, old_words + words)
        else:
            grouped.append((y, list(words)))
    return [sorted(words, key=lambda word: (word.x, word.text)) for _, words in grouped]


def _cell_text(words: Sequence[PositionedWord]) -> str:
    return normalize(" ".join(word.text for word in sorted(words, key=lambda word: word.x)))


def is_early_ticker(value: str) -> bool:
    value = normalize(value)
    upper = value.upper()
    return value == upper and EARLY_TICKER_RE.fullmatch(upper) is not None and upper not in NON_DATA_ANCHORS


def parse_bbox_records(xml_text: str) -> tuple[list[MembershipRow], list[ParseIssue]]:
    """Parse each half-page from its stable ticker anchor.

    The anchored word is the ticker. Every later word in the same half-page visual row
    belongs to that company. Text at the anchor that is not ticker-shaped is document
    furniture. A valid anchored ticker with no following company text is unexplained and
    fails the ambiguity gate.
    """
    root = ET.fromstring(xml_text)
    pages = [element for element in root.iter() if _tag_name(element.tag) == "page"]
    rows: list[MembershipRow] = []
    issues: list[ParseIssue] = []
    seen: set[tuple[str, str]] = set()
    source_line = 0

    for page_no, page in enumerate(pages, start=1):
        width = float(page.attrib.get("width", "0"))
        if abs(width - 612.0) > 0.5:
            raise RuntimeError(f"unexpected page width on page {page_no}: {width}")
        for visual_row, words in enumerate(_visual_rows(page), start=1):
            source_line += 1
            for side, (ticker_x, end_x) in enumerate(GROUPS):
                anchored = sorted(
                    (word for word in words if abs(word.x - ticker_x) <= ANCHOR_TOLERANCE),
                    key=lambda word: (abs(word.x - ticker_x), word.x, word.text),
                )
                if not anchored:
                    continue
                ticker_word = anchored[0]
                ticker = ticker_word.text
                if not is_early_ticker(ticker):
                    continue
                company_words = [
                    word for word in words
                    if word.x > ticker_word.x + 0.5 and word.x < end_x
                ]
                company = _cell_text(company_words)
                if not company:
                    issues.append(ParseIssue(page_no, visual_row, side, "missing_company", ticker, company))
                    continue

                key = (ticker.upper(), company)
                if key in seen:
                    continue
                seen.add(key)
                rows.append(MembershipRow(ticker.upper(), company, source_line))

    return rows, issues


def pdf_to_bbox(payload: bytes) -> str:
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        raise RuntimeError("pdftotext is unavailable on this runner")
    with tempfile.TemporaryDirectory(prefix="russell-early-bbox-") as tmp:
        pdf_path = Path(tmp) / "source.pdf"
        xml_path = Path(tmp) / "source.xml"
        pdf_path.write_bytes(payload)
        proc = subprocess.run(
            [pdftotext, "-bbox-layout", str(pdf_path), str(xml_path)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"pdftotext -bbox-layout failed rc={proc.returncode}: {proc.stderr.strip()[:500]}"
            )
        return xml_path.read_text(errors="replace")


def rows_sha256(rows: Sequence[MembershipRow]) -> str:
    canonical = json.dumps(
        [{"ticker": row.ticker, "company": row.company} for row in rows],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


def write_outputs(output_dir: Path, result: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "membership.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    (output_dir / "report.md").write_text(
        "# Archived early Russell 3000 geometry extraction\n\n"
        "Research evidence only. Raw PDF/bbox XML is not persisted.\n\n"
        f"- Capture: `{result['capture']['timestamp']}`\n"
        f"- PDF SHA-256: `{result['pdf_sha256']}`\n"
        f"- PDF hash gate: **{result['pdf_hash_gate']}**\n"
        f"- Pages: **{result['page_count']}**\n"
        f"- Parsed company/ticker rows: **{result['row_count']:,}**\n"
        f"- Unique tickers: **{result['unique_tickers']:,}**\n"
        f"- Conflicting ticker labels: **{len(result['ambiguous_tickers'])}**\n"
        f"- Unexplained geometry rows: **{len(result['unexplained_rows'])}**\n"
        f"- Membership rows SHA-256: `{result['rows_sha256']}`\n"
        f"- Determinism gate: **{result['determinism_gate']}**\n"
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
    p.add_argument("--min-rows", type=int, default=2900)
    p.add_argument("--max-rows", type=int, default=3100)
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    expected_hash = EXPECTED_PDF_SHA256.get(args.timestamp)
    if expected_hash is None:
        raise RuntimeError(f"no certified early-PDF hash for timestamp {args.timestamp}")

    capture = query_exact_capture(args.url, args.timestamp, args.timeout, args.attempts)
    payload, status, content_type, final_url = archive._request(
        capture.raw_archive_url, timeout=args.timeout, attempts=args.attempts
    )
    if status != 200 or not payload.startswith(b"%PDF-"):
        raise RuntimeError(
            f"archive payload is not a PDF: status={status} content_type={content_type!r} bytes={len(payload)}"
        )

    pdf_hash = hashlib.sha256(payload).hexdigest()
    hash_ok = pdf_hash == expected_hash
    if not hash_ok:
        raise RuntimeError(f"source PDF hash mismatch: expected={expected_hash} actual={pdf_hash}")

    bbox_xml = pdf_to_bbox(payload)
    first_rows, first_issues = parse_bbox_records(bbox_xml)
    second_rows, second_issues = parse_bbox_records(bbox_xml)
    deterministic = first_rows == second_rows and first_issues == second_issues
    rows = first_rows
    issues = first_issues

    by_ticker: dict[str, set[str]] = {}
    for row in rows:
        by_ticker.setdefault(row.ticker, set()).add(row.company)
    ambiguous = {
        ticker: sorted(companies)
        for ticker, companies in sorted(by_ticker.items())
        if len(companies) > 1
    }
    count_ok = args.min_rows <= len(rows) <= args.max_rows
    ambiguity_ok = not ambiguous and not issues
    page_count = sum(1 for element in ET.fromstring(bbox_xml).iter() if _tag_name(element.tag) == "page")
    result = {
        "schema": 3,
        "generated_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "raw_pdf_persisted": False,
        "raw_bbox_persisted": False,
        "parser_contract": "poppler_bbox_measured_612pt_two_halfpage_stable_ticker_anchor_v3",
        "geometry": {
            "page_width": 612.0,
            "ticker_anchors": [90.0, 330.0],
            "nominal_company_starts": list(NOMINAL_COMPANY_STARTS),
            "anchor_tolerance": ANCHOR_TOLERANCE,
        },
        "capture": asdict(capture),
        "fetch_final_url": final_url,
        "fetch_content_type": content_type,
        "pdf_sha256": pdf_hash,
        "expected_pdf_sha256": expected_hash,
        "pdf_hash_gate": "PASS" if hash_ok else "FAIL",
        "pdf_bytes": len(payload),
        "bbox_sha256": hashlib.sha256(bbox_xml.encode()).hexdigest(),
        "page_count": page_count,
        "row_count": len(rows),
        "unique_tickers": len(by_ticker),
        "ambiguous_tickers": ambiguous,
        "unexplained_rows": [asdict(issue) for issue in issues],
        "rows_sha256": rows_sha256(rows),
        "determinism_gate": "PASS" if deterministic else "FAIL",
        "count_gate": "PASS" if count_ok else "FAIL",
        "ambiguity_gate": "PASS" if ambiguity_ok else "FAIL",
        "min_rows": args.min_rows,
        "max_rows": args.max_rows,
        "rows": [asdict(row) for row in rows],
    }
    write_outputs(args.output_dir, result)
    print(json.dumps({
        "rows": len(rows),
        "unique_tickers": len(by_ticker),
        "ambiguous_tickers": len(ambiguous),
        "unexplained_rows": len(issues),
        "rows_sha256": result["rows_sha256"],
        "pdf_hash_gate": result["pdf_hash_gate"],
        "determinism_gate": result["determinism_gate"],
        "count_gate": result["count_gate"],
        "ambiguity_gate": result["ambiguity_gate"],
        "pdf_sha256": result["pdf_sha256"],
    }, sort_keys=True))
    return 0 if hash_ok and deterministic and count_ok and ambiguity_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
