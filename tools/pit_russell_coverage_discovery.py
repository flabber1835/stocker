#!/usr/bin/env python3
"""Discover and verify annual Russell 3000 membership artifacts for 2005-2026.

Research-only. Raw third-party documents are fetched ephemerally. Persisted output
contains capture provenance, selected-candidate diagnostics, integrity hashes, and
year-level coverage status.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Sequence
import urllib.parse

import pit_russell_archive_probe as archive

DEFAULT_QUERIES = (
    "http://www.russell.com/us/indexes/us/reconstitution/R3000.pdf",
    "http://www.russell.com/US/Indexes/US/reconstitution/R3000.pdf",
    "http://www.russell.com/indexes/documents/Membership/Russell3000_Membership_List.pdf",
    "https://www.russell.com/indexes/documents/Membership/Russell3000_Membership_List.pdf",
    "http://www.russell.com/indexes/*Russell3000*Membership*",
    "https://content.ftserussell.com/sites/default/files/*ru3000*membership*.pdf",
    "http://content.ftserussell.com/sites/default/files/*ru3000*membership*.pdf",
)

DATE_IN_NAME_RE = re.compile(r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])([0-3]\d)(?!\d)")


@dataclass(frozen=True)
class Candidate:
    document_year: int
    source_family: str
    source_rank: int
    timestamp: str
    original: str
    digest: str
    mimetype: str
    reported_length: str
    inferred_document_date: str | None
    inference: str

    @property
    def capture_date(self) -> str:
        return self.timestamp[:8]


@dataclass
class FetchEvidence:
    document_year: int
    timestamp: str
    original: str
    source_family: str
    fetch_ok: bool
    http_status: int | None
    response_content_type: str | None
    byte_length: int | None
    sha256: str | None
    pdf_signature: bool | None
    final_url: str | None
    error: str | None


def source_family(url: str) -> tuple[str, int]:
    folded = url.casefold()
    if "content.ftserussell.com" in folded and "membership" in folded:
        return "ftse-russell-dated-content", 0
    if "/reconstitution/r3000.pdf" in folded:
        return "russell-legacy-r3000", 1
    if "russell3000_membership" in folded:
        return "russell-stable-membership", 1
    return "russell-other-official", 2


def embedded_document_date(url: str) -> str | None:
    name = Path(urllib.parse.urlparse(url).path).name
    matches = list(DATE_IN_NAME_RE.finditer(name))
    if not matches:
        return None
    year, month, day = matches[-1].groups()
    try:
        parsed = datetime(int(year), int(month), int(day), tzinfo=UTC)
    except ValueError:
        return None
    return parsed.strftime("%Y%m%d")


def infer_document_year(capture: archive.Capture) -> tuple[int, str | None, str]:
    embedded = embedded_document_date(capture.original)
    if embedded:
        return int(embedded[:4]), embedded, "dated-filename"

    capture_dt = datetime.strptime(capture.timestamp[:8], "%Y%m%d")
    # Stable annual URLs normally switch to the new universe around late June.
    if (capture_dt.month, capture_dt.day) >= (6, 20):
        return capture_dt.year, None, "stable-url-post-reconstitution-capture"
    return capture_dt.year - 1, None, "stable-url-pre-reconstitution-carry"


def candidate_from_capture(capture: archive.Capture) -> Candidate:
    family, rank = source_family(capture.original)
    year, doc_date, inference = infer_document_year(capture)
    return Candidate(
        document_year=year,
        source_family=family,
        source_rank=rank,
        timestamp=capture.timestamp,
        original=capture.original,
        digest=capture.digest,
        mimetype=capture.mimetype,
        reported_length=capture.reported_length,
        inferred_document_date=doc_date,
        inference=inference,
    )


def _candidate_score(candidate: Candidate) -> tuple[int, int, int, str]:
    capture_dt = datetime.strptime(candidate.timestamp[:8], "%Y%m%d")
    if candidate.inferred_document_date:
        target = datetime.strptime(candidate.inferred_document_date, "%Y%m%d")
        # Prefer captures on/after the dated artifact, then earliest such capture.
        before = 1 if capture_dt < target else 0
        distance = abs((capture_dt - target).days)
        return (candidate.source_rank, before, distance, candidate.timestamp)

    target = datetime(candidate.document_year, 6, 30)
    # For stable URLs, post-June-20 captures are the strong annual snapshot evidence.
    pre_reconstitution = 1 if capture_dt < datetime(candidate.document_year, 6, 20) else 0
    distance = abs((capture_dt - target).days)
    return (candidate.source_rank, pre_reconstitution, distance, candidate.timestamp)


def choose_year_candidate(candidates: Sequence[Candidate], year: int) -> Candidate | None:
    rows = [row for row in candidates if row.document_year == year]
    if not rows:
        return None
    return min(rows, key=_candidate_score)


def fetch_candidate(candidate: Candidate, timeout: int, attempts: int) -> FetchEvidence:
    raw_url = f"{archive.WAYBACK_PREFIX}/{candidate.timestamp}id_/{candidate.original}"
    try:
        payload, status, ctype, final_url = archive._request(
            raw_url, timeout=timeout, attempts=attempts
        )
        return FetchEvidence(
            document_year=candidate.document_year,
            timestamp=candidate.timestamp,
            original=candidate.original,
            source_family=candidate.source_family,
            fetch_ok=True,
            http_status=status,
            response_content_type=ctype,
            byte_length=len(payload),
            sha256=hashlib.sha256(payload).hexdigest(),
            pdf_signature=payload.startswith(b"%PDF-"),
            final_url=final_url,
            error=None,
        )
    except Exception as exc:
        return FetchEvidence(
            document_year=candidate.document_year,
            timestamp=candidate.timestamp,
            original=candidate.original,
            source_family=candidate.source_family,
            fetch_ok=False,
            http_status=getattr(exc, "code", None),
            response_content_type=None,
            byte_length=None,
            sha256=None,
            pdf_signature=None,
            final_url=None,
            error=f"{type(exc).__name__}: {exc}",
        )


def run(args: argparse.Namespace) -> dict:
    captures: list[archive.Capture] = []
    query_errors: list[dict] = []

    for query in args.url:
        try:
            payload, status, ctype, final_url = archive._request(
                archive.build_cdx_url(query, args.from_year, args.to_year + 1),
                timeout=args.timeout,
                attempts=args.attempts,
            )
            if status != 200:
                raise RuntimeError(f"CDX HTTP {status}")
            rows = archive.parse_cdx_payload(query, payload)
            captures.extend(rows)
            print(
                f"CDX {query}: {len(rows)} rows via {final_url} ({ctype})",
                flush=True,
            )
        except Exception as exc:
            query_errors.append(
                {"query": query, "error": f"{type(exc).__name__}: {exc}"}
            )

    deduped = archive.dedupe_captures(captures)
    candidates = [
        candidate_from_capture(row)
        for row in deduped
        if args.from_year <= infer_document_year(row)[0] <= args.to_year
    ]

    selected: list[Candidate] = []
    for year in range(args.from_year, args.to_year + 1):
        row = choose_year_candidate(candidates, year)
        if row is not None:
            selected.append(row)

    fetches: list[FetchEvidence] = []
    for row in selected:
        time.sleep(args.delay)
        fetches.append(fetch_candidate(row, args.timeout, args.attempts))

    fetch_by_year = {row.document_year: row for row in fetches}
    candidate_counts = {
        year: sum(1 for row in candidates if row.document_year == year)
        for year in range(args.from_year, args.to_year + 1)
    }

    years = []
    for year in range(args.from_year, args.to_year + 1):
        chosen = choose_year_candidate(candidates, year)
        fetched = fetch_by_year.get(year)
        if chosen is None:
            status = "NO_OFFICIAL_CAPTURE_FOUND"
        elif fetched and fetched.fetch_ok and fetched.pdf_signature:
            status = "RECOVERABLE_OFFICIAL_PDF"
        elif fetched and fetched.fetch_ok:
            status = "FETCHED_NON_PDF"
        else:
            status = "CAPTURE_FOUND_FETCH_FAILED"
        years.append(
            {
                "year": year,
                "candidate_count": candidate_counts[year],
                "status": status,
                "selected": asdict(chosen) if chosen else None,
                "fetch": asdict(fetched) if fetched else None,
            }
        )

    return {
        "schema": 1,
        "generated_utc": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "from_year": args.from_year,
        "to_year": args.to_year,
        "raw_documents_persisted": False,
        "queries": list(args.url),
        "query_errors": query_errors,
        "capture_count": len(deduped),
        "candidate_count": len(candidates),
        "candidates": [asdict(row) for row in sorted(
            candidates, key=lambda x: (x.document_year, x.timestamp, x.original)
        )],
        "years": years,
        "totals": {
            "recoverable_official_pdf_years": sum(
                1 for row in years if row["status"] == "RECOVERABLE_OFFICIAL_PDF"
            ),
            "missing_years": [
                row["year"] for row in years if row["status"] == "NO_OFFICIAL_CAPTURE_FOUND"
            ],
            "fetch_failed_years": [
                row["year"] for row in years if row["status"] == "CAPTURE_FOUND_FETCH_FAILED"
            ],
        },
    }


def write_outputs(output_dir: Path, result: dict) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "coverage.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n"
    )
    lines = [
        "# Russell 3000 annual archive coverage",
        "",
        "Research evidence only. Raw third-party membership documents are not persisted.",
        "",
        "| Year | Candidate captures | Status | Selected source | Capture |",
        "|---:|---:|---|---|---|",
    ]
    for row in result["years"]:
        selected = row["selected"]
        source = selected["source_family"] if selected else "-"
        timestamp = selected["timestamp"] if selected else "-"
        lines.append(
            f"| {row['year']} | {row['candidate_count']} | {row['status']} | "
            f"{source} | {timestamp} |"
        )
    lines.extend(
        [
            "",
            f"- Recoverable official PDF years: **{result['totals']['recoverable_official_pdf_years']}**",
            f"- Missing years: **{result['totals']['missing_years']}**",
            f"- Fetch-failed years: **{result['totals']['fetch_failed_years']}**",
            "",
        ]
    )
    if result["query_errors"]:
        lines.extend(["## Query errors", ""])
        for row in result["query_errors"]:
            lines.append(f"- `{row['query']}`: {row['error']}")
        lines.append("")
    (output_dir / "report.md").write_text("\n".join(lines))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--from-year", type=int, default=2005)
    p.add_argument("--to-year", type=int, default=2026)
    p.add_argument("--url", action="append", default=None)
    p.add_argument("--timeout", type=int, default=20)
    p.add_argument("--attempts", type=int, default=3)
    p.add_argument("--delay", type=float, default=0.35)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args(argv)
    if args.to_year < args.from_year:
        p.error("--to-year must be >= --from-year")
    args.url = tuple(args.url) if args.url else DEFAULT_QUERIES
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    result = run(args)
    write_outputs(args.output_dir, result)
    print(json.dumps(result["totals"], sort_keys=True))
    # Discovery is informational: gaps are surfaced explicitly and do not masquerade
    # as a successful complete corpus.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
