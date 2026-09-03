#!/usr/bin/env python3
"""Extract factual company/ticker membership rows from one archived Russell PDF.

Research only. The archived PDF and Poppler representations remain ephemeral.
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
import xml.etree.ElementTree as ET

import pit_russell_archive_probe as archive

TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
EXCLUDED = {
    "RUSSELL", "INDEX", "TICKER", "SYMBOL", "COMPANY", "NAME", "FINAL",
    "MEMBERSHIP", "PAGE", "INC", "CORP", "LLC", "LTD", "NYSE", "NASDAQ",
    "AMEX", "OTC", "US", "USA",
}
HEADER_COMPANY = {"company"}
HEADER_SYMBOL = {"ticker", "symbol"}


@dataclass(frozen=True)
class MembershipRow:
    ticker: str
    company: str
    source_line: int


@dataclass(frozen=True)
class PositionedWord:
    x: float
    y: float
    text: str


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def is_ticker(value: str) -> bool:
    value = normalize(value)
    upper = value.upper()
    return value == upper and TICKER_RE.fullmatch(upper) is not None and upper not in EXCLUDED


def parse_layout_text(text: str) -> list[MembershipRow]:
    """Legacy diagnostic parser retained to quantify why coordinate parsing is needed."""
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


def _tag_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _page_visual_rows(page: ET.Element, y_tolerance: float = 1.5) -> list[list[PositionedWord]]:
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
            x = float(word.attrib.get("xMin", line.attrib.get("xMin", "0")))
            y = float(word.attrib.get("yMin", line.attrib.get("yMin", "0")))
            words.append(PositionedWord(x=x, y=y, text=text))
        if words:
            fragments.append((sum(w.y for w in words) / len(words), words))

    fragments.sort(key=lambda item: item[0])
    groups: list[tuple[float, list[PositionedWord]]] = []
    for y, words in fragments:
        if groups and abs(y - groups[-1][0]) <= y_tolerance:
            old_y, old_words = groups[-1]
            groups[-1] = ((old_y + y) / 2.0, old_words + words)
        else:
            groups.append((y, list(words)))
    return [sorted(words, key=lambda word: (word.x, word.text)) for _, words in groups]


def _header_positions(words: Sequence[PositionedWord]) -> tuple[list[float], list[float]] | None:
    company = [w.x for w in words if w.text.casefold() in HEADER_COMPANY]
    symbol = [w.x for w in words if w.text.casefold() in HEADER_SYMBOL]
    if not company or not symbol:
        return None
    ordered = sorted([(x, "company") for x in company] + [(x, "symbol") for x in symbol])
    if len(ordered) < 2 or ordered[0][1] != "company":
        return None
    pairs = []
    idx = 0
    while idx + 1 < len(ordered):
        if ordered[idx][1] == "company" and ordered[idx + 1][1] == "symbol":
            pairs.append((ordered[idx][0], ordered[idx + 1][0]))
            idx += 2
        else:
            idx += 1
    if not pairs:
        return None
    return ([p[0] for p in pairs], [p[1] for p in pairs])


def _choose_column_positions(page_rows: Sequence[Sequence[PositionedWord]]) -> tuple[list[float], list[float]] | None:
    candidates = [positions for words in page_rows if (positions := _header_positions(words))]
    if not candidates:
        return None
    return max(candidates, key=lambda item: len(item[0]))


def _assign_column(x: float, starts: Sequence[float]) -> int:
    """Assign by actual header starts, not midpoints between headers.

    Company text may extend close to the Symbol header. A word belongs to the newest
    column whose header has actually begun; this prevents long company names from
    leaking into the ticker cell.
    """
    selected = 0
    for idx, start in enumerate(starts):
        if x + 0.25 >= start:
            selected = idx
        else:
            break
    return selected


def parse_bbox_xml(xml_text: str) -> list[MembershipRow]:
    root = ET.fromstring(xml_text)
    pages = [element for element in root.iter() if _tag_name(element.tag) == "page"]
    rows: list[MembershipRow] = []
    seen: set[tuple[str, str]] = set()
    inherited: tuple[list[float], list[float]] | None = None
    source_line = 0

    for page in pages:
        visual_rows = _page_visual_rows(page)
        positions = _choose_column_positions(visual_rows) or inherited
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
        starts = [item[0] for item in ordered]
        kinds = [item[1] for item in ordered]

        for words in visual_rows:
            source_line += 1
            if _header_positions(words):
                continue
            cells: list[list[str]] = [[] for _ in starts]
            for word in words:
                cells[_assign_column(word.x, starts)].append(word.text)
            values = [normalize(" ".join(cell)) for cell in cells]
            for idx in range(1, len(values)):
                if kinds[idx] != "symbol" or kinds[idx - 1] != "company":
                    continue
                ticker = values[idx]
                company = values[idx - 1]
                if not is_ticker(ticker):
                    continue
                if not company or is_ticker(company) or company.upper() in EXCLUDED or len(company) < 3:
                    continue
                key = (ticker.upper(), company)
                if key in seen:
                    continue
                seen.add(key)
                rows.append(MembershipRow(ticker.upper(), company, source_line))
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


def _run_pdftotext(payload: bytes, mode: str) -> str:
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        raise RuntimeError("pdftotext is unavailable on this runner")
    with tempfile.TemporaryDirectory(prefix="russell-pdf-") as tmp:
        pdf_path = Path(tmp) / "source.pdf"
        out_path = Path(tmp) / ("source.xml" if mode == "bbox-layout" else "source.txt")
        pdf_path.write_bytes(payload)
        option = "-bbox-layout" if mode == "bbox-layout" else "-layout"
        proc = subprocess.run(
            [pdftotext, option, str(pdf_path), str(out_path)],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"pdftotext {mode} failed rc={proc.returncode}: {proc.stderr.strip()[:500]}"
            )
        return out_path.read_text(errors="replace")


def write_outputs(output_dir: Path, result: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "membership.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    lines = [
        "# Archived Russell 3000 membership extraction",
        "",
        "Research evidence only. Raw PDF/text/bbox output is not persisted.",
        "",
        f"- Capture: `{result['capture']['timestamp']}`",
        f"- Archived original: `{result['capture']['original']}`",
        f"- PDF SHA-256: `{result['pdf_sha256']}`",
        f"- PDF bytes: **{result['pdf_bytes']:,}**",
        f"- BBox parsed company/ticker rows: **{result['row_count']:,}**",
        f"- Layout diagnostic rows: **{result['layout_diagnostic_rows']:,}**",
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

    layout_text = _run_pdftotext(payload, "layout")
    layout_rows = parse_layout_text(layout_text)
    bbox_xml = _run_pdftotext(payload, "bbox-layout")
    rows = parse_bbox_xml(bbox_xml)

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
        "schema": 2,
        "generated_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "raw_pdf_persisted": False,
        "raw_text_persisted": False,
        "raw_bbox_persisted": False,
        "parser_contract": "poppler_bbox_layout_header_start_anchored_company_symbol_columns",
        "capture": asdict(capture),
        "fetch_final_url": final_url,
        "fetch_content_type": content_type,
        "pdf_sha256": hashlib.sha256(payload).hexdigest(),
        "pdf_bytes": len(payload),
        "layout_diagnostic_rows": len(layout_rows),
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
        "layout_diagnostic_rows": len(layout_rows),
        "unique_tickers": len(by_ticker),
        "ambiguous_tickers": len(ambiguous),
        "count_gate": result["count_gate"],
        "pdf_sha256": result["pdf_sha256"],
    }, sort_keys=True))
    return 0 if count_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
