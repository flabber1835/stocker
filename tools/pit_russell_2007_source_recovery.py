#!/usr/bin/env python3
"""Recover and validate exact 2007 Russell 3000 membership captures.

Research only. Queries only known exact legacy Russell R3000.pdf endpoints. Raw archive
PDFs and Poppler output remain ephemeral. The output records capture provenance,
source hashes, deterministic geometry extraction, and candidate qualification.
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

import pit_russell_archive_probe as archive
from pit_russell_pdf_legacy_membership_extract import (
    _tag_name,
    parse_bbox_records,
    pdf_to_bbox,
    rows_sha256,
)

YEAR = 2007
EXACT_URLS = (
    "http://www.russell.com/us/indexes/us/reconstitution/R3000.pdf",
    "http://www.russell.com/us/Indexes/US/Reconstitution/R3000.pdf",
    "http://www.russell.com:80/us/indexes/us/reconstitution/R3000.pdf",
    "http://www.russell.com:80/us/Indexes/US/Reconstitution/R3000.pdf",
    "https://www.russell.com/us/indexes/us/reconstitution/R3000.pdf",
    "https://www.russell.com/us/Indexes/US/Reconstitution/R3000.pdf",
)


def first_page_text(payload: bytes) -> str:
    pdftotext = shutil.which("pdftotext")
    if not pdftotext:
        raise RuntimeError("pdftotext is unavailable")
    with tempfile.TemporaryDirectory(prefix="r3000-2007-text-") as tmp:
        pdf = Path(tmp) / "source.pdf"
        txt = Path(tmp) / "first.txt"
        pdf.write_bytes(payload)
        proc = subprocess.run(
            [pdftotext, "-layout", "-f", "1", "-l", "1", str(pdf), str(txt)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"pdftotext failed rc={proc.returncode}: {proc.stderr[:300]}")
        return txt.read_text(errors="replace")


def candidate_record(cap: archive.Capture, timeout: int, attempts: int) -> dict:
    record = {
        "capture": asdict(cap),
        "raw_archive_url": cap.raw_archive_url,
        "fetch_ok": False,
        "pdf_signature": False,
        "pdf_sha256": None,
        "pdf_bytes": None,
        "page_count": None,
        "row_count": None,
        "unique_tickers": None,
        "ambiguous_tickers": {},
        "unexplained_rows": [],
        "rows_sha256": None,
        "determinism_gate": "FAIL",
        "count_gate": "FAIL",
        "ambiguity_gate": "FAIL",
        "russell_3000_marker": False,
        "first_page_excerpt": None,
        "qualifies_as_full_membership_candidate": False,
        "error": None,
    }
    try:
        payload, status, content_type, final_url = archive._request(
            cap.raw_archive_url, timeout=timeout, attempts=attempts
        )
        if status != 200 or not payload.startswith(b"%PDF-"):
            raise RuntimeError(
                f"archive payload is not PDF: status={status} type={content_type!r} bytes={len(payload)}"
            )
        record["fetch_ok"] = True
        record["pdf_signature"] = True
        record["fetch_final_url"] = final_url
        record["fetch_content_type"] = content_type
        record["pdf_sha256"] = hashlib.sha256(payload).hexdigest()
        record["pdf_bytes"] = len(payload)

        text = first_page_text(payload)
        compact = " ".join(text.split())
        record["first_page_excerpt"] = compact[:1200]
        record["russell_3000_marker"] = "RUSSELL 3000" in compact.upper()

        bbox = pdf_to_bbox(payload)
        first_rows, first_issues = parse_bbox_records(bbox)
        second_rows, second_issues = parse_bbox_records(bbox)
        deterministic = first_rows == second_rows and first_issues == second_issues
        by_ticker: dict[str, set[str]] = {}
        for row in first_rows:
            by_ticker.setdefault(row.ticker, set()).add(row.company)
        ambiguous = {
            ticker: sorted(labels)
            for ticker, labels in sorted(by_ticker.items())
            if len(labels) > 1
        }
        import xml.etree.ElementTree as ET
        page_count = sum(1 for node in ET.fromstring(bbox).iter() if _tag_name(node.tag) == "page")
        count_ok = 2900 <= len(first_rows) <= 3100
        ambiguity_ok = not ambiguous and not first_issues

        record.update(
            {
                "page_count": page_count,
                "row_count": len(first_rows),
                "unique_tickers": len(by_ticker),
                "ambiguous_tickers": ambiguous,
                "unexplained_rows": [asdict(issue) for issue in first_issues],
                "rows_sha256": rows_sha256(first_rows),
                "determinism_gate": "PASS" if deterministic else "FAIL",
                "count_gate": "PASS" if count_ok else "FAIL",
                "ambiguity_gate": "PASS" if ambiguity_ok else "FAIL",
                "qualifies_as_full_membership_candidate": bool(
                    deterministic and count_ok and ambiguity_ok and record["russell_3000_marker"]
                ),
                "rows": [asdict(row) for row in first_rows] if deterministic and count_ok and ambiguity_ok else [],
            }
        )
    except Exception as exc:
        record["error"] = f"{type(exc).__name__}: {exc}"
    return record


def main() -> int:
    out = Path("/tmp/r3000-2007-recovery")
    out.mkdir(parents=True, exist_ok=True)
    captures: list[archive.Capture] = []
    query_errors: list[dict] = []
    for query in EXACT_URLS:
        try:
            payload, status, _, _ = archive._request(
                archive.build_cdx_url(query, YEAR, YEAR), timeout=20, attempts=4
            )
            if status != 200:
                raise RuntimeError(f"CDX HTTP {status}")
            rows = archive.parse_cdx_payload(query, payload)
            print(f"CDX {query}: {len(rows)} rows", flush=True)
            captures.extend(rows)
        except Exception as exc:
            query_errors.append({"query": query, "error": f"{type(exc).__name__}: {exc}"})
            print(f"CDX ERROR {query}: {type(exc).__name__}: {exc}", flush=True)

    deduped = archive.dedupe_captures(captures)
    # Distinct content digests are the important transitions when Russell overwrote R3000.pdf.
    selected: list[archive.Capture] = []
    seen: set[str] = set()
    for cap in sorted(deduped, key=lambda c: (c.timestamp, c.original)):
        key = cap.digest or f"{cap.timestamp}|{cap.original}"
        if key in seen:
            continue
        seen.add(key)
        selected.append(cap)

    print(f"Distinct 2007 captures: {len(selected)}", flush=True)
    candidates = []
    for cap in selected:
        print(f"TEST {cap.timestamp} {cap.original} digest={cap.digest}", flush=True)
        row = candidate_record(cap, timeout=25, attempts=5)
        candidates.append(row)
        print(json.dumps({
            "timestamp": cap.timestamp,
            "original": cap.original,
            "pdf_sha256": row.get("pdf_sha256"),
            "pages": row.get("page_count"),
            "rows": row.get("row_count"),
            "unique": row.get("unique_tickers"),
            "marker": row.get("russell_3000_marker"),
            "determinism": row.get("determinism_gate"),
            "count": row.get("count_gate"),
            "ambiguity": row.get("ambiguity_gate"),
            "qualifies": row.get("qualifies_as_full_membership_candidate"),
            "error": row.get("error"),
        }, sort_keys=True), flush=True)

    qualified = [row for row in candidates if row["qualifies_as_full_membership_candidate"]]
    result = {
        "schema": 1,
        "generated_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "year": YEAR,
        "query_policy": "exact known legacy Russell R3000.pdf endpoints only; no wildcard CDX",
        "queries": list(EXACT_URLS),
        "query_errors": query_errors,
        "distinct_capture_count": len(selected),
        "qualified_candidate_count": len(qualified),
        "candidates": candidates,
    }
    (out / "recovery.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")

    print("=== QUALIFIED 2007 CANDIDATES ===")
    for row in qualified:
        cap = row["capture"]
        print(
            f"{cap['timestamp']} {cap['original']} pdf={row['pdf_sha256']} "
            f"rows={row['row_count']} rows_sha={row['rows_sha256']}"
        )
        print(f"first_page={row['first_page_excerpt']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
