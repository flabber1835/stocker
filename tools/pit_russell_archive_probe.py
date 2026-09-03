#!/usr/bin/env python3
"""Probe Internet Archive for historical Russell 3000 membership artifacts.

Research-only utility. It does not mutate any production/backtest state and does not
persist downloaded constituent PDFs. Persisted outputs contain provenance and hashes.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence

CDX_ENDPOINT = "https://web.archive.org/cdx/search/cdx"
WAYBACK_PREFIX = "https://web.archive.org/web"
USER_AGENT = "stocker-pit-russell-research/1.0 (+https://github.com/flabber1835/stocker)"

# Historical public references establish the first path as a real Russell endpoint.
# The others are deliberately treated only as discovery candidates.
DEFAULT_URL_QUERIES = (
    "http://www.russell.com/indexes/documents/Membership/Russell3000_Membership_List.pdf",
    "https://www.russell.com/indexes/documents/Membership/Russell3000_Membership_List.pdf",
    "http://www.russell.com/indexes/data/membership/Russell3000_Membership_List.pdf",
    "http://www.russell.com/indexes/membership/USIndexes/Russell3000_Membership_List.pdf",
    "http://www.russell.com/indexes/*Russell3000*Membership*",
)

CDX_FIELDS = ("timestamp", "original", "statuscode", "mimetype", "digest", "length")


@dataclass(frozen=True)
class Capture:
    query_url: str
    timestamp: str
    original: str
    statuscode: str
    mimetype: str
    digest: str
    reported_length: str

    @property
    def year(self) -> int:
        return int(self.timestamp[:4])

    @property
    def raw_archive_url(self) -> str:
        return f"{WAYBACK_PREFIX}/{self.timestamp}id_/{self.original}"


@dataclass
class DownloadEvidence:
    query_url: str
    timestamp: str
    original: str
    raw_archive_url: str
    cdx_statuscode: str
    cdx_mimetype: str
    cdx_digest: str
    cdx_reported_length: str
    fetch_ok: bool
    http_status: int | None
    response_content_type: str | None
    byte_length: int | None
    sha256: str | None
    pdf_signature: bool | None
    error: str | None


def _request(url: str, timeout: int, attempts: int) -> tuple[bytes, int, str | None, str]:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json,application/pdf,*/*;q=0.5",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                payload = response.read()
                status = int(getattr(response, "status", 200))
                ctype = response.headers.get("Content-Type")
                final_url = response.geturl()
                return payload, status, ctype, final_url
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt == attempts:
                break
            time.sleep(min(2 ** (attempt - 1), 8))
    assert last_error is not None
    raise last_error


def build_cdx_url(query_url: str, from_year: int, to_year: int) -> str:
    params = [
        ("url", query_url),
        ("output", "json"),
        ("fl", ",".join(CDX_FIELDS)),
        ("filter", "statuscode:200"),
        ("from", str(from_year)),
        ("to", str(to_year)),
        ("collapse", "digest"),
    ]
    return f"{CDX_ENDPOINT}?{urllib.parse.urlencode(params)}"


def parse_cdx_payload(query_url: str, payload: bytes) -> list[Capture]:
    parsed = json.loads(payload.decode("utf-8"))
    if not parsed:
        return []
    if not isinstance(parsed, list) or not isinstance(parsed[0], list):
        raise ValueError("unexpected CDX response shape")
    header = parsed[0]
    if header != list(CDX_FIELDS):
        raise ValueError(f"unexpected CDX fields: {header!r}")

    captures: list[Capture] = []
    for row in parsed[1:]:
        if not isinstance(row, list) or len(row) != len(CDX_FIELDS):
            continue
        values = dict(zip(CDX_FIELDS, (str(x) for x in row)))
        timestamp = values["timestamp"]
        if len(timestamp) < 8 or not timestamp[:8].isdigit():
            continue
        captures.append(
            Capture(
                query_url=query_url,
                timestamp=timestamp,
                original=values["original"],
                statuscode=values["statuscode"],
                mimetype=values["mimetype"],
                digest=values["digest"],
                reported_length=values["length"],
            )
        )
    return captures


def dedupe_captures(captures: Iterable[Capture]) -> list[Capture]:
    # Same archived object can be returned by overlapping HTTP/HTTPS/wildcard queries.
    seen: set[tuple[str, str, str]] = set()
    out: list[Capture] = []
    for capture in sorted(captures, key=lambda c: (c.timestamp, c.original, c.digest, c.query_url)):
        key = (capture.timestamp, capture.original, capture.digest)
        if key in seen:
            continue
        seen.add(key)
        out.append(capture)
    return out


def reconstitution_distance(timestamp: str) -> tuple[int, int]:
    """Sort key favoring captures close to June 30 of their capture year.

    The first item prefers the June 20-August 15 evidence window. The second is
    absolute calendar-day distance from June 30.
    """
    dt = datetime.strptime(timestamp[:8], "%Y%m%d")
    target = datetime(dt.year, 6, 30)
    in_window = datetime(dt.year, 6, 20) <= dt <= datetime(dt.year, 8, 15)
    return (0 if in_window else 1, abs((dt - target).days))


def choose_downloads(
    captures: Sequence[Capture],
    from_year: int,
    to_year: int,
    max_per_year: int,
) -> list[Capture]:
    by_year: dict[int, list[Capture]] = defaultdict(list)
    for capture in captures:
        if from_year <= capture.year <= to_year:
            by_year[capture.year].append(capture)

    selected: list[Capture] = []
    for year in range(from_year, to_year + 1):
        year_rows = sorted(
            by_year.get(year, []),
            key=lambda c: (reconstitution_distance(c.timestamp), c.timestamp, c.original, c.digest),
        )
        seen_digest: set[str] = set()
        for capture in year_rows:
            digest_key = capture.digest or f"{capture.original}|{capture.timestamp}"
            if digest_key in seen_digest:
                continue
            seen_digest.add(digest_key)
            selected.append(capture)
            if len(seen_digest) >= max_per_year:
                break
    return selected


def fetch_capture(capture: Capture, timeout: int, attempts: int) -> DownloadEvidence:
    try:
        payload, status, content_type, final_url = _request(
            capture.raw_archive_url, timeout=timeout, attempts=attempts
        )
        return DownloadEvidence(
            query_url=capture.query_url,
            timestamp=capture.timestamp,
            original=capture.original,
            raw_archive_url=final_url,
            cdx_statuscode=capture.statuscode,
            cdx_mimetype=capture.mimetype,
            cdx_digest=capture.digest,
            cdx_reported_length=capture.reported_length,
            fetch_ok=True,
            http_status=status,
            response_content_type=content_type,
            byte_length=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            pdf_signature=payload.startswith(b"%PDF-"),
            error=None,
        )
    except Exception as exc:  # Network evidence should be retained, not hidden by fail-fast.
        return DownloadEvidence(
            query_url=capture.query_url,
            timestamp=capture.timestamp,
            original=capture.original,
            raw_archive_url=capture.raw_archive_url,
            cdx_statuscode=capture.statuscode,
            cdx_mimetype=capture.mimetype,
            cdx_digest=capture.digest,
            cdx_reported_length=capture.reported_length,
            fetch_ok=False,
            http_status=getattr(exc, "code", None),
            response_content_type=None,
            byte_length=None,
            sha256=None,
            pdf_signature=None,
            error=f"{type(exc).__name__}: {exc}",
        )


def summarize(
    captures: Sequence[Capture], downloads: Sequence[DownloadEvidence], from_year: int, to_year: int
) -> dict:
    capture_counts: dict[int, int] = defaultdict(int)
    unique_capture_digests: dict[int, set[str]] = defaultdict(set)
    for capture in captures:
        capture_counts[capture.year] += 1
        if capture.digest:
            unique_capture_digests[capture.year].add(capture.digest)

    downloaded: dict[int, list[DownloadEvidence]] = defaultdict(list)
    for item in downloads:
        downloaded[int(item.timestamp[:4])].append(item)

    years = []
    for year in range(from_year, to_year + 1):
        rows = downloaded.get(year, [])
        ok = [row for row in rows if row.fetch_ok]
        pdf = [row for row in ok if row.pdf_signature]
        years.append(
            {
                "year": year,
                "cdx_captures": capture_counts.get(year, 0),
                "unique_cdx_digests": len(unique_capture_digests.get(year, set())),
                "download_attempts": len(rows),
                "successful_downloads": len(ok),
                "pdf_payloads": len(pdf),
                "unique_download_sha256": len({row.sha256 for row in ok if row.sha256}),
                "status": "RECOVERABLE_PDF" if pdf else ("CAPTURES_ONLY" if capture_counts.get(year, 0) else "NO_CAPTURE_FOUND"),
            }
        )

    return {
        "schema": 1,
        "generated_utc": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "from_year": from_year,
        "to_year": to_year,
        "years": years,
        "totals": {
            "cdx_captures": len(captures),
            "download_attempts": len(downloads),
            "successful_downloads": sum(1 for row in downloads if row.fetch_ok),
            "pdf_payloads": sum(1 for row in downloads if row.fetch_ok and row.pdf_signature),
        },
    }


def write_outputs(
    output_dir: Path,
    queries: Sequence[str],
    captures: Sequence[Capture],
    downloads: Sequence[DownloadEvidence],
    query_errors: Sequence[dict],
    summary: dict,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "schema": 1,
        "policy": {
            "raw_constituent_documents_persisted": False,
            "description": "Research evidence only; downloaded third-party files remain ephemeral.",
        },
        "queries": list(queries),
        "query_errors": list(query_errors),
        "captures": [asdict(row) for row in captures],
        "downloads": [asdict(row) for row in downloads],
        "summary": summary,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    with (output_dir / "captures.csv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(DownloadEvidence.__annotations__.keys()))
        writer.writeheader()
        for row in downloads:
            writer.writerow(asdict(row))

    lines = [
        "# Russell 3000 Wayback probe",
        "",
        f"Generated: {summary['generated_utc']}",
        "",
        "This report is research evidence only. It is not a PIT certificate.",
        "",
        "| Year | CDX captures | Unique CDX digests | Downloads OK | PDF payloads | Status |",
        "|---:|---:|---:|---:|---:|---|",
    ]
    for row in summary["years"]:
        lines.append(
            f"| {row['year']} | {row['cdx_captures']} | {row['unique_cdx_digests']} | "
            f"{row['successful_downloads']} | {row['pdf_payloads']} | {row['status']} |"
        )
    if query_errors:
        lines.extend(["", "## CDX query errors", ""])
        for error in query_errors:
            lines.append(f"- `{error['query_url']}`: {error['error']}")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "`RECOVERABLE_PDF` means a candidate archived payload was fetched and had a PDF signature. It does not prove that the document is the correct final annual membership list, establish its original publication time, parse its constituents, or establish PIT admissibility.",
            "",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(lines))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-year", type=int, default=2005)
    parser.add_argument("--to-year", type=int, default=2014)
    parser.add_argument("--max-downloads-per-year", type=int, default=4)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--attempts", type=int, default=4)
    parser.add_argument("--delay", type=float, default=0.75, help="Delay between archive downloads")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--url",
        action="append",
        dest="urls",
        help="Override/add an exact or wildcard CDX URL query. Repeatable.",
    )
    args = parser.parse_args(argv)
    if args.from_year > args.to_year:
        parser.error("--from-year must be <= --to-year")
    if args.max_downloads_per_year < 1:
        parser.error("--max-downloads-per-year must be >= 1")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    queries = tuple(args.urls) if args.urls else DEFAULT_URL_QUERIES

    all_captures: list[Capture] = []
    query_errors: list[dict] = []
    for query_url in queries:
        cdx_url = build_cdx_url(query_url, args.from_year, args.to_year)
        print(f"CDX {query_url}", flush=True)
        try:
            payload, status, content_type, final_url = _request(
                cdx_url, timeout=args.timeout, attempts=args.attempts
            )
            if status != 200:
                raise RuntimeError(f"CDX HTTP {status}")
            rows = parse_cdx_payload(query_url, payload)
            print(f"  {len(rows)} capture rows via {final_url} ({content_type})", flush=True)
            all_captures.extend(rows)
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            print(f"  ERROR {message}", file=sys.stderr, flush=True)
            query_errors.append({"query_url": query_url, "cdx_url": cdx_url, "error": message})

    captures = dedupe_captures(all_captures)
    selected = choose_downloads(
        captures,
        from_year=args.from_year,
        to_year=args.to_year,
        max_per_year=args.max_downloads_per_year,
    )
    print(f"Unique captures: {len(captures)}; selected downloads: {len(selected)}", flush=True)

    downloads: list[DownloadEvidence] = []
    for index, capture in enumerate(selected, start=1):
        print(
            f"DOWNLOAD {index}/{len(selected)} {capture.timestamp} {capture.original}",
            flush=True,
        )
        evidence = fetch_capture(capture, timeout=args.timeout, attempts=args.attempts)
        downloads.append(evidence)
        if evidence.fetch_ok:
            print(
                f"  OK bytes={evidence.byte_length} pdf={evidence.pdf_signature} sha256={evidence.sha256}",
                flush=True,
            )
        else:
            print(f"  ERROR {evidence.error}", file=sys.stderr, flush=True)
        if index != len(selected) and args.delay:
            time.sleep(args.delay)

    summary = summarize(captures, downloads, args.from_year, args.to_year)
    write_outputs(args.output_dir, queries, captures, downloads, query_errors, summary)
    print(json.dumps(summary["totals"], indent=2, sort_keys=True))

    # Absence of captures is an experimental result, not a process failure. The workflow
    # fails only if the probe itself crashes or its deterministic tests fail.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
