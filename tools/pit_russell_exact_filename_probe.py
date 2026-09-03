#!/usr/bin/env python3
"""Probe exact historical Russell membership filenames on known official publisher roots.

Research only. This avoids expensive CDX wildcard queries. Raw PDF bytes remain
ephemeral; persisted output records exact capture provenance and integrity evidence.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Sequence

import pit_russell_archive_probe as archive

OFFICIAL_ROOTS = (
    "https://content.ftserussell.com/sites/default/files/{filename}",
    "http://content.ftserussell.com/sites/default/files/{filename}",
    "https://www.ftserussell.com/files/support-document/{filename}",
    "http://www.ftserussell.com/files/support-document/{filename}",
    "https://www.russell.com/indexes/documents/Membership/{filename}",
    "http://www.russell.com/indexes/documents/Membership/{filename}",
)


@dataclass(frozen=True)
class CaptureEvidence:
    query_url: str
    timestamp: str
    original: str
    digest: str
    reported_length: str
    mimetype: str
    fetch_ok: bool
    http_status: int | None
    content_type: str | None
    byte_length: int | None
    sha256: str | None
    pdf_signature: bool | None
    final_url: str | None
    error: str | None


def fetch_capture(cap: archive.Capture, timeout: int, attempts: int) -> CaptureEvidence:
    try:
        payload, status, ctype, final_url = archive._request(
            cap.raw_archive_url, timeout=timeout, attempts=attempts
        )
        return CaptureEvidence(
            query_url=cap.query_url,
            timestamp=cap.timestamp,
            original=cap.original,
            digest=cap.digest,
            reported_length=cap.reported_length,
            mimetype=cap.mimetype,
            fetch_ok=True,
            http_status=status,
            content_type=ctype,
            byte_length=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            pdf_signature=payload.startswith(b"%PDF-"),
            final_url=final_url,
            error=None,
        )
    except Exception as exc:
        return CaptureEvidence(
            query_url=cap.query_url,
            timestamp=cap.timestamp,
            original=cap.original,
            digest=cap.digest,
            reported_length=cap.reported_length,
            mimetype=cap.mimetype,
            fetch_ok=False,
            http_status=getattr(exc, "code", None),
            content_type=None,
            byte_length=None,
            sha256=None,
            pdf_signature=None,
            final_url=None,
            error=f"{type(exc).__name__}: {exc}",
        )


def run(args: argparse.Namespace) -> dict:
    captures: list[archive.Capture] = []
    query_errors: list[dict] = []
    queries = [root.format(filename=args.filename) for root in OFFICIAL_ROOTS]
    for query in queries:
        try:
            payload, status, _, _ = archive._request(
                archive.build_cdx_url(query, args.year, args.year + 2),
                timeout=args.timeout,
                attempts=args.attempts,
            )
            if status != 200:
                raise RuntimeError(f"CDX HTTP {status}")
            captures.extend(archive.parse_cdx_payload(query, payload))
        except Exception as exc:
            query_errors.append({"query": query, "error": f"{type(exc).__name__}: {exc}"})

    deduped = archive.dedupe_captures(captures)
    # Prefer captures close to the named document date and retain distinct digests.
    selected: list[archive.Capture] = []
    seen_digest: set[str] = set()
    for cap in sorted(deduped, key=lambda c: (archive.reconstitution_distance(c.timestamp), c.timestamp, c.original)):
        key = cap.digest or f"{cap.timestamp}|{cap.original}"
        if key in seen_digest:
            continue
        seen_digest.add(key)
        selected.append(cap)
        if len(selected) >= args.max_captures:
            break

    evidence = [fetch_capture(cap, args.timeout, args.attempts) for cap in selected]
    pdfs = [row for row in evidence if row.fetch_ok and row.pdf_signature]
    return {
        "schema": 1,
        "generated_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "year": args.year,
        "filename": args.filename,
        "raw_pdf_persisted": False,
        "queries": queries,
        "query_errors": query_errors,
        "capture_count": len(deduped),
        "selected_capture_count": len(selected),
        "pdf_capture_count": len(pdfs),
        "status": "RECOVERED_OFFICIAL_PDF" if pdfs else ("CAPTURE_FOUND_FETCH_FAILED" if selected else "NO_EXACT_CAPTURE_FOUND"),
        "captures": [asdict(row) for row in evidence],
    }


def write_outputs(output_dir: Path, result: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "exact_filename_probe.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    lines = [
        f"# Russell exact-filename probe — {result['year']}",
        "",
        f"- Filename: `{result['filename']}`",
        f"- Status: **{result['status']}**",
        f"- Exact CDX captures: **{result['capture_count']}**",
        f"- Recoverable PDF captures: **{result['pdf_capture_count']}**",
        "",
    ]
    for row in result["captures"]:
        lines.append(
            f"- `{row['timestamp']}` `{row['original']}` sha256=`{row['sha256']}` pdf={row['pdf_signature']}"
        )
    if result["query_errors"]:
        lines.extend(["", "## Query errors", ""])
        lines.extend(f"- `{row['query']}`: {row['error']}" for row in result["query_errors"])
    (output_dir / "report.md").write_text("\n".join(lines) + "\n")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--filename", required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--timeout", type=int, default=15)
    p.add_argument("--attempts", type=int, default=3)
    p.add_argument("--max-captures", type=int, default=3)
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    result = run(args)
    write_outputs(args.output_dir, result)
    print(json.dumps({
        "year": result["year"],
        "filename": result["filename"],
        "status": result["status"],
        "capture_count": result["capture_count"],
        "pdf_capture_count": result["pdf_capture_count"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
