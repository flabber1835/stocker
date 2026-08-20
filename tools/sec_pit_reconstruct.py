#!/usr/bin/env python3
"""Reconstruct SEC point-in-time issuer observations from quarterly Form 3/4/5 data.

The SEC Insider Transactions Data Sets are quarterly ZIP archives whose
SUBMISSION table contains the filing date, issuer CIK, issuer name, issuer trading
symbol and accession number for each as-filed Form 3/4/5 submission.

This tool deliberately produces *evidence*, not guessed historical relationships:
- an issuer/ticker observation becomes usable no earlier than its SEC filing date;
- current Sharadar relatedtickers is never consulted here;
- every row retains archive + row provenance;
- coverage gaps or malformed archives refuse completion.

Outputs:
  observations.csv       one normalized SEC filing observation per accession
  symbol_cik_evidence.csv compressed symbol/CIK evidence spans (not validity claims)
  coverage.json          archive/file/row/date provenance and refusal evidence
  SHA256SUMS.txt         hashes of generated outputs
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
import zipfile
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence

ARCHIVE_RE = re.compile(r"^(?P<year>\d{4})q(?P<quarter>[1-4])_form345\.zip$", re.I)
REQUIRED_FIELDS = {
    "ACCESSION_NUMBER",
    "FILING_DATE",
    "DOCUMENT_TYPE",
    "ISSUERCIK",
    "ISSUERNAME",
    "ISSUERTRADINGSYMBOL",
}


class SecPitError(RuntimeError):
    """The SEC evidence cannot support a deterministic PIT reconstruction."""


@dataclass(frozen=True, order=True)
class Quarter:
    year: int
    quarter: int

    @classmethod
    def parse(cls, value: str) -> "Quarter":
        m = re.fullmatch(r"(\d{4})[Qq]([1-4])", value.strip())
        if not m:
            raise argparse.ArgumentTypeError(f"invalid quarter {value!r}; expected YYYYQn")
        return cls(int(m.group(1)), int(m.group(2)))

    def next(self) -> "Quarter":
        return Quarter(self.year + (1 if self.quarter == 4 else 0), 1 if self.quarter == 4 else self.quarter + 1)

    def label(self) -> str:
        return f"{self.year}Q{self.quarter}"


@dataclass(frozen=True)
class Observation:
    filing_date: str
    issuer_cik: str
    issuer_name: str
    issuer_trading_symbol: str
    accession_number: str
    document_type: str
    period_of_report: str
    archive: str
    submission_member: str
    row_number: int

    def canonical_identity(self) -> tuple[str, str, str, str]:
        return (
            self.filing_date,
            self.issuer_cik,
            self.issuer_trading_symbol,
            self.document_type,
        )


@dataclass
class ArchiveAudit:
    archive: str
    quarter: str
    sha256: str
    size_bytes: int
    submission_member: str
    rows: int = 0
    rows_with_symbol: int = 0
    rows_without_symbol: int = 0
    min_filing_date: str | None = None
    max_filing_date: str | None = None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_header(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", (value or "").strip().upper()).strip("_")


def normalize_cik(value: str) -> str:
    digits = re.sub(r"\D", "", (value or "").strip())
    if not digits:
        raise SecPitError("missing issuer CIK")
    if len(digits) > 10:
        raise SecPitError(f"issuer CIK has more than 10 digits: {value!r}")
    return digits.zfill(10)


def normalize_symbol(value: str) -> str:
    return (value or "").strip().upper()


def normalize_accession(value: str) -> str:
    value = (value or "").strip()
    if not value:
        raise SecPitError("missing accession number")
    return value


def normalize_filing_date(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        raise SecPitError("missing filing date")
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            pass
    raise SecPitError(f"unsupported SEC filing date {raw!r}")


def normalize_optional_date(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return ""
    return normalize_filing_date(raw)


def discover_archives(input_dir: Path) -> list[tuple[Quarter, Path]]:
    found: list[tuple[Quarter, Path]] = []
    for path in input_dir.iterdir():
        if not path.is_file():
            continue
        m = ARCHIVE_RE.fullmatch(path.name)
        if m:
            found.append((Quarter(int(m.group("year")), int(m.group("quarter"))), path))
    found.sort(key=lambda item: item[0])
    if not found:
        raise SecPitError(f"no YYYYqN_form345.zip archives found in {input_dir}")
    return found


def require_contiguous(quarters: Sequence[Quarter], start: Quarter, through: Quarter) -> None:
    present = set(quarters)
    expected: list[Quarter] = []
    q = start
    while q <= through:
        expected.append(q)
        q = q.next()
    missing = [q.label() for q in expected if q not in present]
    if missing:
        raise SecPitError(
            f"SEC quarterly coverage is incomplete from {start.label()} through {through.label()}: "
            f"missing {', '.join(missing)}"
        )


def find_submission_member(zf: zipfile.ZipFile) -> str:
    candidates: list[str] = []
    for name in zf.namelist():
        if name.endswith("/"):
            continue
        base = Path(name).name
        stem = Path(base).stem.upper()
        if stem == "SUBMISSION":
            candidates.append(name)
    if len(candidates) != 1:
        raise SecPitError(
            f"archive must contain exactly one SUBMISSION text table; found {candidates or 'none'}"
        )
    return candidates[0]


def decode_submission(raw: bytes) -> str:
    # SEC documentation specifies tab-delimited UTF-8. utf-8-sig tolerates a BOM
    # without weakening the encoding contract.
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SecPitError(f"SUBMISSION table is not UTF-8: {exc}") from exc


def parse_submission_text(text: str, *, archive: str, member: str) -> Iterator[Observation]:
    reader = csv.DictReader(io.StringIO(text), dialect="excel-tab")
    if reader.fieldnames is None:
        raise SecPitError(f"{archive}:{member} has no header row")
    normalized_names = [normalize_header(x) for x in reader.fieldnames]
    if len(set(normalized_names)) != len(normalized_names):
        raise SecPitError(f"{archive}:{member} has duplicate normalized headers")
    missing = sorted(REQUIRED_FIELDS - set(normalized_names))
    if missing:
        raise SecPitError(f"{archive}:{member} is missing required fields: {', '.join(missing)}")

    original_to_normal = dict(zip(reader.fieldnames, normalized_names))
    for row_number, raw_row in enumerate(reader, start=2):
        row = {original_to_normal[k]: (v or "") for k, v in raw_row.items() if k is not None}
        try:
            yield Observation(
                filing_date=normalize_filing_date(row.get("FILING_DATE", "")),
                issuer_cik=normalize_cik(row.get("ISSUERCIK", "")),
                issuer_name=(row.get("ISSUERNAME", "") or "").strip(),
                issuer_trading_symbol=normalize_symbol(row.get("ISSUERTRADINGSYMBOL", "")),
                accession_number=normalize_accession(row.get("ACCESSION_NUMBER", "")),
                document_type=(row.get("DOCUMENT_TYPE", "") or "").strip().upper(),
                period_of_report=normalize_optional_date(row.get("PERIOD_OF_REPORT", "")),
                archive=archive,
                submission_member=member,
                row_number=row_number,
            )
        except SecPitError as exc:
            raise SecPitError(f"{archive}:{member}:{row_number}: {exc}") from exc


def parse_archive(path: Path, quarter: Quarter) -> tuple[list[Observation], ArchiveAudit]:
    try:
        with zipfile.ZipFile(path, "r") as zf:
            bad = zf.testzip()
            if bad is not None:
                raise SecPitError(f"{path.name} failed ZIP CRC at member {bad}")
            member = find_submission_member(zf)
            observations = list(parse_submission_text(
                decode_submission(zf.read(member)), archive=path.name, member=member))
    except zipfile.BadZipFile as exc:
        raise SecPitError(f"{path.name} is not a valid ZIP archive") from exc

    if not observations:
        raise SecPitError(f"{path.name}:{member} contains no submission rows")

    dates = [o.filing_date for o in observations]
    audit = ArchiveAudit(
        archive=path.name,
        quarter=quarter.label(),
        sha256=sha256_file(path),
        size_bytes=path.stat().st_size,
        submission_member=member,
        rows=len(observations),
        rows_with_symbol=sum(bool(o.issuer_trading_symbol) for o in observations),
        rows_without_symbol=sum(not bool(o.issuer_trading_symbol) for o in observations),
        min_filing_date=min(dates),
        max_filing_date=max(dates),
    )
    return observations, audit


def write_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name, "") for name in fieldnames})


def build_symbol_cik_evidence(observations: Sequence[Observation]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str], list[Observation]] = defaultdict(list)
    for obs in observations:
        if obs.issuer_trading_symbol:
            groups[(obs.issuer_trading_symbol, obs.issuer_cik)].append(obs)

    rows: list[dict[str, object]] = []
    for (symbol, cik), items in sorted(groups.items()):
        ordered = sorted(items, key=lambda o: (o.filing_date, o.accession_number))
        rows.append({
            "issuer_trading_symbol": symbol,
            "issuer_cik": cik,
            "first_public_date": ordered[0].filing_date,
            "last_public_date": ordered[-1].filing_date,
            "filing_count": len(ordered),
            "first_accession": ordered[0].accession_number,
            "last_accession": ordered[-1].accession_number,
            "issuer_name_first": ordered[0].issuer_name,
            "issuer_name_last": ordered[-1].issuer_name,
        })
    return rows


def alphabet_control(observations: Sequence[Observation]) -> dict[str, object]:
    # This is evidence only. Do not fail if one class never appears in Form 3/4/5;
    # the acceptance control is evaluated later against the joined SEC+SEP replay.
    target_cik = "0001652044"  # Alphabet Inc.
    rows = [o for o in observations if o.issuer_cik == target_cik and o.issuer_trading_symbol in {"GOOG", "GOOGL"}]
    by_symbol: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        by_symbol[row.issuer_trading_symbol].append(row.filing_date)
    return {
        "issuer_cik": target_cik,
        "GOOG_observations": len(by_symbol.get("GOOG", [])),
        "GOOGL_observations": len(by_symbol.get("GOOGL", [])),
        "GOOG_first_public_date": min(by_symbol["GOOG"]) if by_symbol.get("GOOG") else None,
        "GOOGL_first_public_date": min(by_symbol["GOOGL"]) if by_symbol.get("GOOGL") else None,
        "both_symbols_observed": bool(by_symbol.get("GOOG") and by_symbol.get("GOOGL")),
    }


def reconstruct(input_dir: Path, output_dir: Path, start: Quarter, through: Quarter) -> dict[str, object]:
    archives = discover_archives(input_dir)
    quarters = [q for q, _ in archives]
    require_contiguous(quarters, start, through)

    selected = [(q, p) for q, p in archives if start <= q <= through]
    observations: list[Observation] = []
    audits: list[ArchiveAudit] = []
    accessions: dict[str, Observation] = {}

    for q, path in selected:
        rows, audit = parse_archive(path, q)
        audits.append(audit)
        for obs in rows:
            previous = accessions.get(obs.accession_number)
            if previous is not None:
                if previous.canonical_identity() != obs.canonical_identity():
                    raise SecPitError(
                        f"accession {obs.accession_number} conflicts across archives: "
                        f"{previous.archive}:{previous.row_number} vs {obs.archive}:{obs.row_number}"
                    )
                raise SecPitError(
                    f"duplicate accession {obs.accession_number} appears in both "
                    f"{previous.archive} and {obs.archive}; quarterly source is not disjoint"
                )
            accessions[obs.accession_number] = obs
            observations.append(obs)

    observations.sort(key=lambda o: (o.filing_date, o.accession_number))
    output_dir.mkdir(parents=True, exist_ok=True)

    obs_path = output_dir / "observations.csv"
    obs_fields = list(Observation.__dataclass_fields__)
    write_csv(obs_path, obs_fields, (asdict(o) for o in observations))

    evidence_path = output_dir / "symbol_cik_evidence.csv"
    evidence_rows = build_symbol_cik_evidence(observations)
    evidence_fields = [
        "issuer_trading_symbol", "issuer_cik", "first_public_date", "last_public_date",
        "filing_count", "first_accession", "last_accession", "issuer_name_first", "issuer_name_last",
    ]
    write_csv(evidence_path, evidence_fields, evidence_rows)

    filing_dates = [o.filing_date for o in observations]
    coverage: dict[str, object] = {
        "schema_version": 1,
        "source": "SEC Insider Transactions Data Sets / Forms 3, 4, 5",
        "pit_rule": "An issuer/ticker observation is usable no earlier than FILING_DATE; no backfill from later observations.",
        "requested_start": start.label(),
        "requested_through": through.label(),
        "archive_count": len(audits),
        "observation_count": len(observations),
        "symbol_cik_pair_count": len(evidence_rows),
        "min_filing_date": min(filing_dates) if filing_dates else None,
        "max_filing_date": max(filing_dates) if filing_dates else None,
        "archives": [asdict(a) for a in audits],
        "alphabet_control": alphabet_control(observations),
    }
    coverage_path = output_dir / "coverage.json"
    coverage_path.write_text(json.dumps(coverage, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    sums_path = output_dir / "SHA256SUMS.txt"
    lines = []
    for path in (obs_path, evidence_path, coverage_path):
        lines.append(f"{sha256_file(path)}  {path.name}")
    sums_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return coverage


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input-dir", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--require-start", type=Quarter.parse, default=Quarter(2006, 1))
    p.add_argument("--require-through", type=Quarter.parse, required=True)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        coverage = reconstruct(args.input_dir, args.output_dir, args.require_start, args.require_through)
    except (SecPitError, OSError) as exc:
        print(f"SEC_PIT_REFUSED: {exc}", file=sys.stderr)
        return 2
    print(
        "SEC_PIT_OK "
        f"archives={coverage['archive_count']} observations={coverage['observation_count']} "
        f"range={coverage['min_filing_date']}..{coverage['max_filing_date']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
