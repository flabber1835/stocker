#!/usr/bin/env python3
"""Recover factual evidence from archived pre-2009 Russell membership/delta pages.

Research only. Raw archived HTML is processed ephemerally. Persisted output contains
capture provenance, hashes, factual candidate rows, and discovered artifact links.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
import urllib.parse
from typing import Sequence

import pit_russell_archive_probe as archive

ARTIFACT_EXTENSIONS = (".pdf", ".xls", ".xlsx", ".csv", ".txt", ".zip")
RELEVANT_WORDS = (
    "3000", "membership", "constituent", "addition", "deletion",
    "reconstitution", "final", "preliminary",
)
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,8}$")
NON_TICKER_TOKENS = {
    "RUSSELL", "INDEX", "TICKER", "SYMBOL", "COMPANY", "NAME", "FINAL", "ADD", "DELETE",
    "NYSE", "NASDAQ", "AMEX", "OTC", "MARKET", "EXCHANGE",
}


@dataclass(frozen=True)
class ArtifactLink:
    capture_timestamp: str
    source_original: str
    href: str
    resolved_url: str
    link_text: str


@dataclass(frozen=True)
class CandidateRow:
    capture_timestamp: str
    source_original: str
    endpoint_kind: str
    ticker: str
    label: str
    cells: tuple[str, ...]


class EvidenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.rows: list[list[str]] = []
        self._href: str | None = None
        self._link_text: list[str] = []
        self._in_cell = False
        self._cell_text: list[str] = []
        self._row: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.casefold()
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self._href = href
                self._link_text = []
        elif tag == "tr":
            self._row = []
        elif tag in {"td", "th"} and self._row is not None:
            self._in_cell = True
            self._cell_text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._link_text.append(data)
        if self._in_cell:
            self._cell_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag == "a" and self._href is not None:
            self.links.append((self._href, normalize_text(" ".join(self._link_text))[:240]))
            self._href = None
            self._link_text = []
        elif tag in {"td", "th"} and self._in_cell:
            if self._row is not None:
                self._row.append(normalize_text(" ".join(self._cell_text)))
            self._in_cell = False
            self._cell_text = []
        elif tag == "tr" and self._row is not None:
            if any(self._row):
                self.rows.append(self._row)
            self._row = None


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def decode_html(payload: bytes) -> str:
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            pass
    raise ValueError("unable to decode archived HTML")


def endpoint_kind(url: str) -> str:
    path = urllib.parse.urlparse(url).path.casefold()
    if "recon_add" in path or "addition" in path:
        return "additions"
    if "recon_delet" in path or "deletion" in path:
        return "deletions"
    if "membership" in path:
        return "membership"
    return "other"


def relevant_artifact_link(base_url: str, href: str, text: str) -> ArtifactLink | None:
    resolved = urllib.parse.urljoin(base_url, href)
    # Relevance must come from the child link itself. The parent page may itself be
    # a reconstitution endpoint, which must not make every navigation child relevant.
    haystack = f"{href} {text}".casefold()
    path = urllib.parse.urlparse(resolved).path.casefold()
    if not any(word in haystack for word in RELEVANT_WORDS) and not path.endswith(ARTIFACT_EXTENSIONS):
        return None
    return ArtifactLink("", base_url, href, resolved, text[:240])


def is_ticker_cell(value: str) -> bool:
    upper = value.upper()
    return value == upper and TICKER_RE.fullmatch(upper) is not None and upper not in NON_TICKER_TOKENS


def candidates_from_cells(
    cells: Sequence[str], timestamp: str, original: str, kind: str
) -> list[CandidateRow]:
    """Extract every adjacent company/ticker pair from a Russell table row.

    Historical Russell pages commonly place two independent pairs in one HTML row:
    Company | Symbol | Company | Symbol. Pairing a ticker with the longest text in
    the whole row can silently attach it to the other company, so adjacency is part
    of the evidence contract.
    """
    cleaned = tuple(normalize_text(cell)[:240] for cell in cells if normalize_text(cell))
    if len(cleaned) < 2:
        return []
    rows: list[CandidateRow] = []
    for idx in range(1, len(cleaned)):
        ticker_cell = cleaned[idx]
        label = cleaned[idx - 1]
        if not is_ticker_cell(ticker_cell):
            continue
        if is_ticker_cell(label) or label.upper() in NON_TICKER_TOKENS or len(label) <= 2:
            continue
        rows.append(
            CandidateRow(
                timestamp,
                original,
                kind,
                ticker_cell.upper(),
                label[:240],
                cleaned[:8],
            )
        )
    return rows


def candidate_from_cells(
    cells: Sequence[str], timestamp: str, original: str, kind: str
) -> CandidateRow | None:
    """Compatibility helper returning the first adjacent pair, if any."""
    rows = candidates_from_cells(cells, timestamp, original, kind)
    return rows[0] if rows else None


def extract_evidence(capture: archive.Capture, payload: bytes) -> tuple[list[ArtifactLink], list[CandidateRow]]:
    parser = EvidenceParser()
    parser.feed(decode_html(payload))

    links: list[ArtifactLink] = []
    seen_links: set[str] = set()
    for href, text in parser.links:
        row = relevant_artifact_link(capture.original, href, text)
        if row is None or row.resolved_url in seen_links:
            continue
        seen_links.add(row.resolved_url)
        links.append(ArtifactLink(capture.timestamp, capture.original, href, row.resolved_url, text))

    kind = endpoint_kind(capture.original)
    candidates: list[CandidateRow] = []
    seen_candidates: set[tuple[str, str]] = set()
    for cells in parser.rows:
        for row in candidates_from_cells(cells, capture.timestamp, capture.original, kind):
            if (row.ticker, row.label) in seen_candidates:
                continue
            seen_candidates.add((row.ticker, row.label))
            candidates.append(row)
    return links, candidates


def query_captures(url: str, from_year: int, to_year: int, timeout: int, attempts: int) -> list[archive.Capture]:
    payload, status, _, _ = archive._request(
        archive.build_cdx_url(url, from_year, to_year), timeout=timeout, attempts=attempts
    )
    if status != 200:
        raise RuntimeError(f"CDX HTTP {status}")
    return archive.parse_cdx_payload(url, payload)


def run(args: argparse.Namespace) -> dict:
    all_captures: list[archive.Capture] = []
    fetches: list[dict] = []
    links: list[ArtifactLink] = []
    candidates: list[CandidateRow] = []
    errors: list[dict] = []

    for url in args.url:
        try:
            captures = query_captures(url, args.from_year, args.to_year, args.timeout, args.attempts)
            all_captures.extend(captures)
        except Exception as exc:
            errors.append({"url": url, "stage": "cdx", "error": f"{type(exc).__name__}: {exc}"})
            continue

        for capture in archive.choose_downloads(captures, args.from_year, args.to_year, args.max_pages_per_year):
            time.sleep(args.delay)
            try:
                payload, status, content_type, final_url = archive._request(
                    capture.raw_archive_url, timeout=args.timeout, attempts=args.attempts
                )
                page_links, page_candidates = extract_evidence(capture, payload)
                links.extend(page_links)
                candidates.extend(page_candidates)
                fetches.append({
                    "timestamp": capture.timestamp,
                    "year": capture.year,
                    "kind": endpoint_kind(capture.original),
                    "original": capture.original,
                    "archive_digest": capture.digest,
                    "http_status": status,
                    "content_type": content_type,
                    "byte_length": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "final_url": final_url,
                    "artifact_links": len(page_links),
                    "candidate_rows": len(page_candidates),
                })
            except Exception as exc:
                errors.append({
                    "url": url, "stage": "archive_fetch", "timestamp": capture.timestamp,
                    "original": capture.original, "error": f"{type(exc).__name__}: {exc}",
                })

    deduped_captures = archive.dedupe_captures(all_captures)
    dedup_links = {(row.capture_timestamp, row.resolved_url): row for row in links}
    dedup_candidates = {
        (row.capture_timestamp, row.endpoint_kind, row.ticker, row.label): row for row in candidates
    }
    captures_by_year: dict[int, int] = defaultdict(int)
    fetched_by_year: dict[int, int] = defaultdict(int)
    candidates_by_year: dict[int, int] = defaultdict(int)
    links_by_year: dict[int, int] = defaultdict(int)
    for row in deduped_captures:
        captures_by_year[row.year] += 1
    for row in fetches:
        fetched_by_year[int(row["year"])] += 1
    for row in dedup_candidates.values():
        candidates_by_year[int(row.capture_timestamp[:4])] += 1
    for row in dedup_links.values():
        links_by_year[int(row.capture_timestamp[:4])] += 1

    years = [{
        "year": year,
        "captures": captures_by_year.get(year, 0),
        "pages_fetched": fetched_by_year.get(year, 0),
        "candidate_rows": candidates_by_year.get(year, 0),
        "artifact_links": links_by_year.get(year, 0),
    } for year in range(args.from_year, args.to_year + 1)]

    return {
        "schema": 2,
        "generated_utc": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "from_year": args.from_year,
        "to_year": args.to_year,
        "urls": list(args.url),
        "raw_html_persisted": False,
        "row_pairing_contract": "adjacent_company_then_ticker",
        "capture_count": len(deduped_captures),
        "fetches": fetches,
        "artifact_links": [asdict(row) for row in sorted(
            dedup_links.values(), key=lambda x: (x.capture_timestamp, x.resolved_url)
        )],
        "candidate_rows": [asdict(row) for row in sorted(
            dedup_candidates.values(), key=lambda x: (x.capture_timestamp, x.endpoint_kind, x.ticker, x.label)
        )],
        "years": years,
        "errors": errors,
    }


def write_outputs(output_dir: Path, result: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    lines = [
        "# Legacy Russell membership/delta content probe", "",
        "Research evidence only. Raw archived pages are not persisted.", "",
        f"Row pairing: `{result['row_pairing_contract']}`", "",
        "| Year | Captures | Pages fetched | Candidate rows | Artifact links |",
        "|---:|---:|---:|---:|---:|",
    ]
    for row in result["years"]:
        lines.append(
            f"| {row['year']} | {row['captures']} | {row['pages_fetched']} | "
            f"{row['candidate_rows']} | {row['artifact_links']} |"
        )
    if result["artifact_links"]:
        lines.extend(["", "## Discovered artifact targets", ""])
        for row in result["artifact_links"][:100]:
            label = row["link_text"].replace("|", "\\|") or "-"
            lines.append(f"- {row['capture_timestamp']} — {label}: `{row['resolved_url']}`")
    if result["candidate_rows"]:
        lines.extend(["", "## Candidate factual rows", ""])
        for row in result["candidate_rows"][:100]:
            lines.append(f"- {row['capture_timestamp']} {row['endpoint_kind']}: `{row['ticker']}` — {row['label']}")
    if result["errors"]:
        lines.extend(["", "## Errors", ""])
        for row in result["errors"]:
            lines.append(f"- `{row.get('url', '-')}` / `{row.get('stage', '-')}`: {row.get('error', '-')}")
    lines.append("")
    (output_dir / "report.md").write_text("\n".join(lines))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", action="append", required=True)
    parser.add_argument("--from-year", type=int, default=2005)
    parser.add_argument("--to-year", type=int, default=2009)
    parser.add_argument("--max-pages-per-year", type=int, default=6)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--delay", type=float, default=0.4)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.to_year < args.from_year:
        parser.error("--to-year must be >= --from-year")
    if args.max_pages_per_year < 1:
        parser.error("--max-pages-per-year must be >= 1")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    result = run(args)
    write_outputs(args.output_dir, result)
    print(json.dumps({
        "captures": result["capture_count"],
        "pages": len(result["fetches"]),
        "artifact_links": len(result["artifact_links"]),
        "candidate_rows": len(result["candidate_rows"]),
        "errors": len(result["errors"]),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
