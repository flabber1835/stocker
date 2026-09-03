#!/usr/bin/env python3
"""Recover archived Russell navigation pages and retain only relevant link evidence.

Research only. Archived HTML payloads are downloaded ephemerally. Persisted output contains
capture provenance and link targets/text needed to discover historical membership artifacts.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import time
import urllib.parse
from typing import Sequence

import pit_russell_archive_probe as archive

KEYWORDS = (
    "3000",
    "membership",
    "reconstitution",
    "addition",
    "deletion",
    "final",
    "constituent",
)


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.casefold() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self._href = href
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "a" and self._href is not None:
            text = re.sub(r"\s+", " ", " ".join(self._text)).strip()
            self.links.append((self._href, text[:240]))
            self._href = None
            self._text = []


@dataclass(frozen=True)
class LinkEvidence:
    seed_url: str
    capture_timestamp: str
    archived_original: str
    archive_digest: str
    href: str
    resolved_url: str
    link_text: str
    matched_keywords: tuple[str, ...]


def relevant_link(base_original: str, href: str, text: str) -> LinkEvidence | None:
    resolved = urllib.parse.urljoin(base_original, href)
    haystack = f"{href} {text}".casefold()
    matches = tuple(word for word in KEYWORDS if word in haystack)
    if not matches:
        return None
    return resolved, matches


def extract_relevant_links(
    seed_url: str,
    capture: archive.Capture,
    payload: bytes,
) -> list[LinkEvidence]:
    text = archive.decode_text(payload) if hasattr(archive, "decode_text") else None
    if text is None:
        for encoding in ("utf-8", "latin-1"):
            try:
                text = payload.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
    if text is None:
        raise ValueError("unable to decode archived HTML")

    parser = LinkParser()
    parser.feed(text)
    out: list[LinkEvidence] = []
    seen: set[tuple[str, str]] = set()
    for href, link_text in parser.links:
        found = relevant_link(capture.original, href, link_text)
        if found is None:
            continue
        resolved, matches = found
        key = (resolved, link_text)
        if key in seen:
            continue
        seen.add(key)
        out.append(
            LinkEvidence(
                seed_url=seed_url,
                capture_timestamp=capture.timestamp,
                archived_original=capture.original,
                archive_digest=capture.digest,
                href=href,
                resolved_url=resolved,
                link_text=link_text,
                matched_keywords=matches,
            )
        )
    return out


def fetch_seed_captures(seed: str, from_year: int, to_year: int, timeout: int, attempts: int):
    cdx_url = archive.build_cdx_url(seed, from_year, to_year)
    payload, _, _, _ = archive.request_bytes(cdx_url, timeout, attempts)
    return archive.parse_cdx_payload(seed, payload)


def run(args: argparse.Namespace) -> dict:
    captures: list[archive.Capture] = []
    errors: list[dict] = []
    links: list[LinkEvidence] = []
    page_fetches: list[dict] = []

    for seed in args.seed:
        try:
            found = fetch_seed_captures(seed, args.from_year, args.to_year, args.timeout, args.attempts)
            captures.extend(found)
        except Exception as exc:
            errors.append({"seed_url": seed, "stage": "cdx", "error": f"{type(exc).__name__}: {exc}"})
            continue

        selected = archive.choose_downloads(found, args.from_year, args.to_year, args.max_pages_per_year)
        for capture in selected:
            time.sleep(args.delay)
            try:
                payload, status, content_type, final_url = archive.request_bytes(
                    capture.raw_archive_url, args.timeout, args.attempts
                )
                page_fetches.append(
                    {
                        "seed_url": seed,
                        "timestamp": capture.timestamp,
                        "original": capture.original,
                        "digest": capture.digest,
                        "http_status": status,
                        "content_type": content_type,
                        "byte_length": len(payload),
                        "final_url": final_url,
                    }
                )
                links.extend(extract_relevant_links(seed, capture, payload))
            except Exception as exc:
                errors.append(
                    {
                        "seed_url": seed,
                        "stage": "archive_fetch",
                        "timestamp": capture.timestamp,
                        "archive_url": capture.raw_archive_url,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

    deduped_links: dict[tuple[str, str], LinkEvidence] = {}
    for row in links:
        deduped_links[(row.resolved_url, row.capture_timestamp)] = row

    return {
        "schema": 1,
        "generated_utc": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "from_year": args.from_year,
        "to_year": args.to_year,
        "seeds": args.seed,
        "raw_html_persisted": False,
        "capture_count": len(captures),
        "page_fetches": page_fetches,
        "links": [asdict(row) for row in sorted(deduped_links.values(), key=lambda x: (x.capture_timestamp, x.resolved_url))],
        "errors": errors,
    }


def write_outputs(output_dir: Path, result: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    lines = [
        "# Pre-2009 Russell navigation archive probe",
        "",
        f"- CDX captures: **{result['capture_count']}**",
        f"- Archived pages fetched: **{len(result['page_fetches'])}**",
        f"- Relevant links retained: **{len(result['links'])}**",
        f"- Errors: **{len(result['errors'])}**",
        "",
    ]
    if result["links"]:
        lines.extend(["| Capture | Link text | Resolved target |", "|---|---|---|"])
        for row in result["links"][:100]:
            text = row["link_text"].replace("|", "\\|") or "-"
            url = row["resolved_url"].replace("|", "%7C")
            lines.append(f"| {row['capture_timestamp']} | {text} | `{url}` |")
    else:
        lines.append("No keyword-relevant links were recovered from the selected archived pages.")
    lines.append("")
    (output_dir / "report.md").write_text("\n".join(lines))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", action="append", required=True)
    parser.add_argument("--from-year", type=int, required=True)
    parser.add_argument("--to-year", type=int, required=True)
    parser.add_argument("--max-pages-per-year", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--delay", type=float, default=0.4)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.to_year < args.from_year:
        parser.error("--to-year must be >= --from-year")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    result = run(args)
    write_outputs(args.output_dir, result)
    print(json.dumps({
        "captures": result["capture_count"],
        "pages": len(result["page_fetches"]),
        "links": len(result["links"]),
        "errors": len(result["errors"]),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
