#!/usr/bin/env python3
"""Auditable historical SEC metadata reconstruction, version 2.

The pipeline is deliberately split between authenticated local source parsing and a
bounded web fallback. Raw quarterly SEC Form 3/4/5 archives are the primary
historical identity/security-class source. Web data is used only for unresolved
issuer/SIC/class gaps and is retained byte-for-byte with source-selection inputs.

No current vendor metadata is economic authority. Current SEC company_tickers is
only a discovery hint and never establishes historical identity by itself.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import hashlib
import io
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
import zipfile
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterable, Iterator, Mapping, Sequence

USER_AGENT = "stocker-historical-metadata-certification/2.0 contact=m.bron01@gmail.com"
SEC_SUBMISSIONS = "https://data.sec.gov/submissions"
SEC_ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
SEC_COMPANY_TICKERS = "https://www.sec.gov/files/company_tickers.json"
SCHEMA_PREFIX = "backtester.historical-metadata-reconstruction-v2"
OWNERSHIP_FORMS = {"3", "3/A", "4", "4/A", "5", "5/A"}
PERIODIC_FORMS = {
    "10-K", "10-K/A", "10-Q", "10-Q/A", "20-F", "20-F/A", "40-F", "40-F/A",
    "8-K", "8-K/A", "S-1", "S-1/A", "F-1", "F-1/A", "10", "10/A",
}
SIC_RE = re.compile(
    r"STANDARD\s+INDUSTRIAL\s+CLASSIFICATION\s*:\s*[^\[]*\[(\d{3,4})\]",
    re.I,
)
ISSUER_SYMBOL_RE = re.compile(
    r"<issuerTradingSymbol>\s*(?:<!\[CDATA\[)?\s*([^<\]]+?)\s*(?:\]\]>)?\s*</issuerTradingSymbol>",
    re.I,
)
COMMON_PATTERNS = (
    re.compile(r"\bcommon\s+(?:stock|shares?)\b", re.I),
    re.compile(r"\bclass\s+[a-z0-9-]+\s+common\s+(?:stock|shares?)\b", re.I),
    re.compile(r"\bordinary\s+shares?\b", re.I),
    re.compile(r"\bcommon\s+shares?\s+of\s+beneficial\s+interest\b", re.I),
)
NON_COMMON_PATTERNS = (
    re.compile(r"\bpreferred\b", re.I),
    re.compile(r"\bwarrants?\b", re.I),
    re.compile(r"\brights?\b", re.I),
    re.compile(r"\bunits?\b", re.I),
    re.compile(r"\boptions?\b", re.I),
    re.compile(r"\brestricted\s+stock\s+units?\b", re.I),
    re.compile(r"\brsu\b", re.I),
    re.compile(r"\b(?:notes?|debentures?|bonds?|debt)\b", re.I),
    re.compile(r"\bconvertible\b", re.I),
)
VENDOR_SUFFIX_RE = re.compile(r"^(.*?)(\d+)$")


class ReconstructionError(RuntimeError):
    pass


@dataclass(frozen=True)
class CandidateEpisode:
    security_id: str
    ticker: str
    first_session: str
    last_session: str
    observations: int
    unknown_type_observations: int
    missing_sector_observations: int
    observed_ciks: tuple[str, ...]
    alias_symbol: str = ""
    alias_safe: bool = False


@dataclass(frozen=True)
class HttpResult:
    url: str
    status: int
    path: str
    sha256: str
    bytes: int
    attempts: int
    terminal_absence: bool
    retrieved_at: str


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def directory_content_hash(root: Path) -> str:
    rows = []
    if root.exists():
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            rows.append((path.relative_to(root).as_posix(), sha256_file(path)))
    return sha256_bytes(canonical_json_bytes(rows))


def norm_ticker(value: object) -> str:
    return str(value or "").strip().upper()


def validate_cik(value: object) -> str:
    """Return a canonical ten-digit CIK or empty string.

    Arbitrary non-digits are never stripped. This prevents SEC_UNKNOWN security
    ids from being converted into bogus CIKs.
    """
    text = str(value or "").strip()
    if not text or not text.isdigit() or len(text) > 10:
        return ""
    number = int(text)
    if number <= 0:
        return ""
    return str(number).zfill(10)


def parse_issuer_authority(value: object) -> str:
    text = str(value or "").strip()
    if text.startswith("SEC_UNKNOWN:"):
        return ""
    if not text.startswith("SEC_CIK:"):
        return ""
    return validate_cik(text.split(":", 1)[1])


def normalize_date(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y", "%Y%m%d"):
        try:
            candidate = text[:11] if fmt.startswith("%d-") else text[:10]
            return dt.datetime.strptime(candidate, fmt).date().isoformat()
        except ValueError:
            pass
    try:
        return dt.datetime.strptime(text.upper(), "%d-%b-%Y").date().isoformat()
    except ValueError:
        return ""


def clean_title(value: object) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(value or ""))).strip()


def classify_one_title(value: object) -> str:
    title = clean_title(value)
    if not title:
        return "unknown"
    non_common = any(p.search(title) for p in NON_COMMON_PATTERNS)
    common = any(p.search(title) for p in COMMON_PATTERNS)
    if non_common:
        return "non_common"
    if common:
        return "common"
    return "unknown"


def classify_titles(titles: Iterable[object]) -> tuple[str, str]:
    cleaned = sorted({clean_title(x) for x in titles if clean_title(x)})
    if not cleaned:
        return "unknown", ""
    classes = {classify_one_title(x) for x in cleaned}
    if classes == {"common"}:
        return "common", " | ".join(cleaned)
    if classes == {"non_common"}:
        return "non_common", " | ".join(cleaned)
    return "unknown", " | ".join(cleaned)


def expected_archive_names(first_year: int = 2006, through_year: int = 2026, through_quarter: int = 2) -> list[str]:
    names: list[str] = []
    for year in range(first_year, through_year + 1):
        last_q = through_quarter if year == through_year else 4
        for quarter in range(1, last_q + 1):
            names.append(f"{year}q{quarter}_form345.zip")
    return names


def git_tree(path: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", f"HEAD:{path.as_posix()}"],
            text=True,
            stderr=subprocess.STDOUT,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        raise ReconstructionError(f"cannot resolve committed Git tree for {path}: {exc}") from exc


def verify_source_lock(lock_path: Path, sec_dir: Path, generated_dir: Path, canonical_pointer: Path) -> dict:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if lock.get("schema") != f"{SCHEMA_PREFIX}.source-lock/1":
        raise ReconstructionError("unexpected source-lock schema")
    actual_sec_tree = git_tree(sec_dir)
    expected_sec_tree = str(lock["sec_bulk"]["git_tree_sha1"])
    if actual_sec_tree != expected_sec_tree:
        raise ReconstructionError(f"SEC archive tree mismatch: {actual_sec_tree} != {expected_sec_tree}")
    actual_generated_tree = git_tree(generated_dir)
    expected_generated_tree = str(lock["retained_sec_evidence"]["git_tree_sha1"])
    if actual_generated_tree != expected_generated_tree:
        raise ReconstructionError(
            f"retained SEC evidence tree mismatch: {actual_generated_tree} != {expected_generated_tree}"
        )
    expected_names = expected_archive_names(
        int(lock["sec_bulk"]["first_year"]),
        int(lock["sec_bulk"]["through_year"]),
        int(lock["sec_bulk"]["through_quarter"]),
    )
    actual_names = sorted(p.name for p in sec_dir.glob("*_form345.zip"))
    if actual_names != expected_names:
        missing = sorted(set(expected_names) - set(actual_names))
        extra = sorted(set(actual_names) - set(expected_names))
        raise ReconstructionError(f"SEC archive inventory mismatch: missing={missing} extra={extra}")
    if len(actual_names) != int(lock["sec_bulk"]["archive_count"]):
        raise ReconstructionError("SEC archive count does not match source lock")
    pointer = json.loads(canonical_pointer.read_text(encoding="utf-8"))
    dataset_hash = str(pointer.get("dataset_hash") or pointer.get("dataset_sha256") or "")
    if dataset_hash != str(lock["canonical_pit"]["dataset_sha256"]):
        raise ReconstructionError(f"canonical PIT hash mismatch: {dataset_hash}")
    return {
        "schema": f"{SCHEMA_PREFIX}.source-lock-verification/1",
        "status": "PASS",
        "sec_tree": actual_sec_tree,
        "retained_sec_tree": actual_generated_tree,
        "archive_count": len(actual_names),
        "canonical_dataset_sha256": dataset_hash,
    }


def observation_files(dataset: Path) -> list[Path]:
    required = {"session", "security_id", "ticker", "issuer_id", "security_type", "sic", "ff12"}
    result: list[Path] = []
    for path in sorted(dataset.rglob("*.csv.gz")):
        try:
            with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
                header = next(csv.reader(fh), [])
        except (OSError, UnicodeDecodeError):
            continue
        if required.issubset(set(header)):
            result.append(path)
    if not result:
        raise ReconstructionError("could not locate canonical observation partitions")
    return result


def alias_candidate(ticker: str) -> str:
    match = VENDOR_SUFFIX_RE.match(ticker)
    if not match:
        return ""
    base = norm_ticker(match.group(1))
    return base if base and base != ticker else ""


def intervals_overlap(a_start: str, a_end: str, b_start: str, b_end: str) -> bool:
    return not (a_end < b_start or b_end < a_start)


def mark_safe_aliases(episodes: Sequence[CandidateEpisode]) -> list[CandidateEpisode]:
    by_alias: dict[str, list[CandidateEpisode]] = defaultdict(list)
    for episode in episodes:
        alias = alias_candidate(episode.ticker)
        if alias:
            by_alias[alias].append(episode)
    unsafe: set[tuple[str, str]] = set()
    exact_tickers = {e.ticker for e in episodes}
    for alias, rows in by_alias.items():
        if alias in exact_tickers or len({r.ticker for r in rows}) != 1:
            unsafe.update((r.security_id, r.ticker) for r in rows)
            continue
        ordered = sorted(rows, key=lambda r: (r.first_session, r.last_session, r.security_id))
        for i, left in enumerate(ordered):
            for right in ordered[i + 1:]:
                if intervals_overlap(left.first_session, left.last_session, right.first_session, right.last_session):
                    unsafe.add((left.security_id, left.ticker))
                    unsafe.add((right.security_id, right.ticker))
    result: list[CandidateEpisode] = []
    for row in episodes:
        alias = alias_candidate(row.ticker)
        safe = bool(alias) and (row.security_id, row.ticker) not in unsafe
        result.append(CandidateEpisode(**(asdict(row) | {"alias_symbol": alias, "alias_safe": safe})))
    return result


def write_gzip_csv(path: Path, fieldnames: Sequence[str], rows: Iterable[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=list(fieldnames), lineterminator="\n", extrasaction="ignore")
                writer.writeheader()
                for row in rows:
                    writer.writerow({k: row.get(k, "") for k in fieldnames})


def read_gzip_csv(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def load_candidates(path: Path) -> list[CandidateEpisode]:
    result: list[CandidateEpisode] = []
    for row in read_gzip_csv(path):
        ciks = tuple(sorted({x for x in (row.get("observed_ciks") or "").split(";") if validate_cik(x)}))
        result.append(
            CandidateEpisode(
                security_id=row["security_id"],
                ticker=norm_ticker(row["ticker"]),
                first_session=row["first_session"],
                last_session=row["last_session"],
                observations=int(row.get("observations") or 0),
                unknown_type_observations=int(row.get("unknown_type_observations") or 0),
                missing_sector_observations=int(row.get("missing_sector_observations") or 0),
                observed_ciks=ciks,
                alias_symbol=norm_ticker(row.get("alias_symbol") or ""),
                alias_safe=str(row.get("alias_safe") or "").lower() == "true",
            )
        )
    return result


def prepare_candidates(dataset: Path, output: Path, from_year: int = 2006, through_year: int = 2026) -> dict:
    state: dict[tuple[str, str], dict[str, object]] = {}
    total_rows = 0
    sessions: set[str] = set()
    files = observation_files(dataset)
    for index, path in enumerate(files, 1):
        with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                session = str(row.get("session") or "")[:10]
                if len(session) < 4:
                    continue
                try:
                    year = int(session[:4])
                except ValueError:
                    continue
                if year < from_year or year > through_year:
                    continue
                total_rows += 1
                sessions.add(session)
                ticker = norm_ticker(row.get("ticker"))
                sid = str(row.get("security_id") or "").strip()
                if not ticker or not sid:
                    continue
                key = (sid, ticker)
                rec = state.setdefault(
                    key,
                    {"first": session, "last": session, "obs": 0, "unknown": 0, "sector": 0, "ciks": set()},
                )
                rec["first"] = min(str(rec["first"]), session)
                rec["last"] = max(str(rec["last"]), session)
                rec["obs"] = int(rec["obs"]) + 1
                stype = str(row.get("security_type") or "").strip().lower()
                if not stype or stype == "unknown":
                    rec["unknown"] = int(rec["unknown"]) + 1
                if not str(row.get("sic") or "").strip() or not str(row.get("ff12") or "").strip():
                    rec["sector"] = int(rec["sector"]) + 1
                cik = parse_issuer_authority(row.get("issuer_id"))
                if cik:
                    ciks = rec["ciks"]
                    assert isinstance(ciks, set)
                    ciks.add(cik)
        print(f"[CANDIDATES] partition={index}/{len(files)} {path.name}", flush=True)

    episodes = [
        CandidateEpisode(
            security_id=sid,
            ticker=ticker,
            first_session=str(rec["first"]),
            last_session=str(rec["last"]),
            observations=int(rec["obs"]),
            unknown_type_observations=int(rec["unknown"]),
            missing_sector_observations=int(rec["sector"]),
            observed_ciks=tuple(sorted(rec["ciks"])),
        )
        for (sid, ticker), rec in sorted(state.items())
        if int(rec["unknown"]) or int(rec["sector"])
    ]
    episodes = mark_safe_aliases(episodes)
    output.mkdir(parents=True, exist_ok=True)
    fields = [
        "security_id", "ticker", "first_session", "last_session", "observations",
        "unknown_type_observations", "missing_sector_observations", "observed_ciks",
        "alias_symbol", "alias_safe",
    ]
    rows = []
    for episode in episodes:
        row = asdict(episode)
        row["observed_ciks"] = ";".join(episode.observed_ciks)
        row["alias_safe"] = str(episode.alias_safe).lower()
        rows.append(row)
    candidate_path = output / "candidate_episodes.csv.gz"
    write_gzip_csv(candidate_path, fields, rows)
    security_ids = {e.security_id for e in episodes}
    sid_cik_collisions = sum(1 for e in episodes for cik in e.observed_ciks if cik in security_ids or cik == e.security_id)
    if sid_cik_collisions:
        raise ReconstructionError(f"security ids leaked into CIK fields: {sid_cik_collisions}")
    summary = {
        "schema": f"{SCHEMA_PREFIX}.candidates/1",
        "from_year": from_year,
        "through_year": through_year,
        "canonical_rows_scanned": total_rows,
        "sessions": len(sessions),
        "episodes_needing_enrichment": len(episodes),
        "candidate_tickers": len({e.ticker for e in episodes}),
        "unknown_type_observations": sum(e.unknown_type_observations for e in episodes),
        "missing_sector_observations": sum(e.missing_sector_observations for e in episodes),
        "episodes_with_valid_observed_cik": sum(bool(e.observed_ciks) for e in episodes),
        "safe_vendor_alias_episodes": sum(e.alias_safe for e in episodes),
        "candidate_sha256": sha256_file(candidate_path),
        "security_id_in_cik_fields": sid_cik_collisions,
    }
    (output / "candidate_coverage.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return summary


def _find_zip_member(zf: zipfile.ZipFile, target: str) -> str:
    target = target.upper()
    matches = [name for name in zf.namelist() if Path(name).name.upper() == target]
    if len(matches) != 1:
        raise ReconstructionError(f"expected exactly one {target} member, got {matches}")
    return matches[0]


def _dict_reader_from_bytes(data: bytes) -> Iterator[dict[str, str]]:
    text = io.TextIOWrapper(io.BytesIO(data), encoding="utf-8-sig", errors="replace", newline="")
    reader = csv.DictReader(text, delimiter="\t")
    if not reader.fieldnames:
        return
    field_map = {name: str(name or "").strip().upper() for name in reader.fieldnames}
    for row in reader:
        yield {field_map[k]: str(v or "").strip() for k, v in row.items() if k is not None}


def _candidate_symbol_index(candidates: Sequence[CandidateEpisode]) -> tuple[set[str], set[str]]:
    exact = {c.ticker for c in candidates}
    aliases = {c.alias_symbol for c in candidates if c.alias_safe and c.alias_symbol}
    return exact, aliases


def parse_bulk_archives(sec_dir: Path, candidates_path: Path, output: Path) -> dict:
    candidates = load_candidates(candidates_path)
    exact_symbols, safe_aliases = _candidate_symbol_index(candidates)
    relevant_symbols = exact_symbols | safe_aliases
    candidate_ciks = {cik for c in candidates for cik in c.observed_ciks}
    output.mkdir(parents=True, exist_ok=True)

    archive_rows: list[dict[str, object]] = []
    identity_rows: list[dict[str, object]] = []
    type_rows: list[dict[str, object]] = []
    title_source_rows: list[dict[str, object]] = []

    archive_paths = [sec_dir / name for name in expected_archive_names()]
    for index, archive in enumerate(archive_paths, 1):
        if not archive.exists():
            raise ReconstructionError(f"missing SEC bulk archive: {archive}")
        archive_digest = sha256_file(archive)
        with zipfile.ZipFile(archive) as zf:
            bad = zf.testzip()
            if bad:
                raise ReconstructionError(f"corrupt ZIP member {bad} in {archive.name}")
            sub_name = _find_zip_member(zf, "SUBMISSION.tsv")
            trans_name = _find_zip_member(zf, "NONDERIV_TRANS.tsv")
            holding_name = _find_zip_member(zf, "NONDERIV_HOLDING.tsv")
            member_data = {
                "SUBMISSION.tsv": zf.read(sub_name),
                "NONDERIV_TRANS.tsv": zf.read(trans_name),
                "NONDERIV_HOLDING.tsv": zf.read(holding_name),
            }
            relevant_accessions: set[str] = set()
            submission_by_accession: dict[str, dict[str, str]] = {}
            for row in _dict_reader_from_bytes(member_data["SUBMISSION.tsv"]):
                accession = row.get("ACCESSION_NUMBER", "")
                filed = normalize_date(row.get("FILING_DATE", ""))
                cik = validate_cik(row.get("ISSUERCIK", ""))
                symbol = norm_ticker(row.get("ISSUERTRADINGSYMBOL", ""))
                if not accession or not filed or not cik or not symbol:
                    continue
                if symbol not in relevant_symbols and cik not in candidate_ciks:
                    continue
                relevant_accessions.add(accession)
                submission_by_accession[accession] = {
                    "accession": accession,
                    "filed": filed,
                    "cik": cik,
                    "sec_symbol": symbol,
                    "document_type": str(row.get("DOCUMENT_TYPE", "")).upper(),
                }

            titles: dict[str, set[str]] = defaultdict(set)
            for member_key, source_table in (
                ("NONDERIV_TRANS.tsv", "NONDERIV_TRANS"),
                ("NONDERIV_HOLDING.tsv", "NONDERIV_HOLDING"),
            ):
                for row in _dict_reader_from_bytes(member_data[member_key]):
                    accession = row.get("ACCESSION_NUMBER", "")
                    if accession not in relevant_accessions:
                        continue
                    title = clean_title(row.get("SECURITY_TITLE", ""))
                    if title:
                        titles[accession].add(title)
                        title_source_rows.append({
                            "accession": accession,
                            "security_title": title,
                            "source_table": source_table,
                            "archive": archive.name,
                            "archive_sha256": archive_digest,
                            "member_sha256": sha256_bytes(member_data[member_key]),
                        })

            for accession, submission in sorted(submission_by_accession.items()):
                identity_rows.append({
                    **submission,
                    "source_kind": "SEC_FORM345_BULK_SUBMISSION",
                    "archive": archive.name,
                    "archive_sha256": archive_digest,
                    "member": "SUBMISSION.tsv",
                    "member_sha256": sha256_bytes(member_data["SUBMISSION.tsv"]),
                })
                classification, evidence = classify_titles(titles.get(accession, ()))
                if evidence:
                    type_rows.append({
                        **submission,
                        "classification": classification,
                        "security_title_evidence": evidence,
                        "authority": "SEC Form 3/4/5 non-derivative Table I titles joined to SUBMISSION",
                        "archive": archive.name,
                        "archive_sha256": archive_digest,
                    })

            for label, data in member_data.items():
                archive_rows.append({
                    "archive": archive.name,
                    "archive_sha256": archive_digest,
                    "archive_bytes": archive.stat().st_size,
                    "member": label,
                    "member_sha256": sha256_bytes(data),
                    "member_bytes": len(data),
                })
        print(
            f"[BULK] archive={index}/{len(archive_paths)} {archive.name} "
            f"identities={len(identity_rows)} types={len(type_rows)}",
            flush=True,
        )

    def dedup(rows: Sequence[Mapping[str, object]], keys: Sequence[str]) -> list[dict[str, object]]:
        chosen: dict[tuple[str, ...], dict[str, object]] = {}
        for row in rows:
            key = tuple(str(row.get(k, "")) for k in keys)
            chosen.setdefault(key, dict(row))
        return [chosen[k] for k in sorted(chosen)]

    archive_rows = dedup(archive_rows, ("archive", "member", "member_sha256"))
    identity_rows = dedup(identity_rows, ("accession", "filed", "cik", "sec_symbol", "archive_sha256"))
    type_rows = dedup(type_rows, ("accession", "filed", "cik", "sec_symbol", "classification", "archive_sha256"))
    title_source_rows = dedup(title_source_rows, ("accession", "security_title", "source_table", "archive_sha256"))

    write_gzip_csv(output / "source_archives.csv.gz", [
        "archive", "archive_sha256", "archive_bytes", "member", "member_sha256", "member_bytes"
    ], archive_rows)
    write_gzip_csv(output / "bulk_identity_sources.csv.gz", [
        "accession", "filed", "cik", "sec_symbol", "document_type", "source_kind",
        "archive", "archive_sha256", "member", "member_sha256",
    ], identity_rows)
    write_gzip_csv(output / "bulk_security_type_sources.csv.gz", [
        "accession", "filed", "cik", "sec_symbol", "document_type", "classification",
        "security_title_evidence", "authority", "archive", "archive_sha256",
    ], type_rows)
    write_gzip_csv(output / "bulk_security_title_sources.csv.gz", [
        "accession", "security_title", "source_table", "archive", "archive_sha256", "member_sha256",
    ], title_source_rows)
    summary = {
        "schema": f"{SCHEMA_PREFIX}.bulk-corpus/1",
        "status": "PASS",
        "archives": len(archive_paths),
        "archive_member_manifest_rows": len(archive_rows),
        "identity_sources": len(identity_rows),
        "security_type_sources": len(type_rows),
        "security_title_sources": len(title_source_rows),
        "source": "retained SEC Insider Transactions Data Sets Form 3/4/5 quarterly ZIPs",
        "derivative_tables_used_for_type": False,
    }
    (output / "bulk_coverage.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_checksums(output)
    return summary


def _event_candidate_matches(candidate: CandidateEpisode, sec_symbol: str, cik: str) -> bool:
    symbol_match = candidate.ticker == sec_symbol or (
        candidate.alias_safe and candidate.alias_symbol and candidate.alias_symbol == sec_symbol
    )
    if not symbol_match:
        return False
    if candidate.observed_ciks and cik not in candidate.observed_ciks:
        return False
    return True


def allocate_identity_events(
    candidates: Sequence[CandidateEpisode], identity_rows: Sequence[Mapping[str, str]]
) -> tuple[list[dict], list[dict]]:
    by_symbol: dict[str, list[CandidateEpisode]] = defaultdict(list)
    for candidate in candidates:
        by_symbol[candidate.ticker].append(candidate)
        if candidate.alias_safe and candidate.alias_symbol:
            by_symbol[candidate.alias_symbol].append(candidate)
    allocated: list[dict] = []
    ambiguous: list[dict] = []
    for row in identity_rows:
        symbol = norm_ticker(row.get("sec_symbol"))
        cik = validate_cik(row.get("cik"))
        filed = normalize_date(row.get("filed"))
        possible = [
            candidate for candidate in by_symbol.get(symbol, ())
            if _event_candidate_matches(candidate, symbol, cik)
        ]
        in_interval = [candidate for candidate in possible if candidate.first_session <= filed <= candidate.last_session]
        if in_interval:
            possible = in_interval
        if len(possible) == 1:
            candidate = possible[0]
            allocated.append(dict(row) | {
                "security_id": candidate.security_id,
                "ticker": candidate.ticker,
                "alias_used": str(candidate.ticker != symbol).lower(),
                "usable_after": filed,
            })
        elif possible:
            ambiguous.append({
                "filed": filed,
                "sec_symbol": symbol,
                "cik": cik,
                "accession": row.get("accession", ""),
                "candidate_security_ids": ";".join(sorted(candidate.security_id for candidate in possible)),
                "reason": "identity_event_maps_to_multiple_security_episodes",
            })
    return allocated, ambiguous


def _read_existing_sic(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        fields = {str(x).lower(): str(x) for x in (reader.fieldnames or [])}
        filed_col = next((fields[x] for x in ("filed", "filing_date", "date") if x in fields), None)
        cik_col = next((fields[x] for x in ("cik", "issuer_cik") if x in fields), None)
        sic_col = next((fields[x] for x in ("sic", "sic_code") if x in fields), None)
        if not filed_col or not cik_col or not sic_col:
            raise ReconstructionError(f"cannot identify SIC columns in {path}")
        for row in reader:
            filed = normalize_date(row.get(filed_col, ""))
            cik = validate_cik(row.get(cik_col, ""))
            sic_digits = re.sub(r"\D", "", str(row.get(sic_col, "")))
            if filed and cik and 3 <= len(sic_digits) <= 4:
                rows.append({
                    "filed": filed,
                    "cik": cik,
                    "sic": sic_digits.zfill(4),
                    "source_kind": "RETAINED_SEC_SIC_DATASET",
                })
    return rows


def _load_web_rows(web_root: Path | None, name: str) -> list[dict[str, str]]:
    if not web_root:
        return []
    path = web_root / name
    if not path.exists():
        return []
    return read_gzip_csv(path)


def derive_timeline(
    candidates_path: Path,
    bulk_dir: Path,
    existing_sic_path: Path,
    output: Path,
    web_root: Path | None = None,
) -> dict:
    candidates = load_candidates(candidates_path)
    identity_raw = read_gzip_csv(bulk_dir / "bulk_identity_sources.csv.gz") + _load_web_rows(
        web_root, "web_identity_sources.csv.gz"
    )
    type_raw = read_gzip_csv(bulk_dir / "bulk_security_type_sources.csv.gz") + _load_web_rows(
        web_root, "web_security_type_sources.csv.gz"
    )
    allocated_identity, ambiguous_identity = allocate_identity_events(candidates, identity_raw)

    identity_by_accession_episode = {
        (row.get("accession", ""), row.get("security_id", ""), row.get("cik", ""))
        for row in allocated_identity
    }
    type_allocated: list[dict] = []
    by_symbol: dict[str, list[CandidateEpisode]] = defaultdict(list)
    for candidate in candidates:
        by_symbol[candidate.ticker].append(candidate)
        if candidate.alias_safe and candidate.alias_symbol:
            by_symbol[candidate.alias_symbol].append(candidate)
    for row in type_raw:
        symbol = norm_ticker(row.get("sec_symbol"))
        cik = validate_cik(row.get("cik"))
        accession = row.get("accession", "")
        matches = [
            candidate for candidate in by_symbol.get(symbol, ())
            if (accession, candidate.security_id, cik) in identity_by_accession_episode
        ]
        if len(matches) != 1:
            continue
        candidate = matches[0]
        classification = str(row.get("classification") or "unknown")
        if classification not in {"common", "non_common"}:
            continue
        filed = normalize_date(row.get("filed"))
        type_allocated.append(dict(row) | {
            "security_id": candidate.security_id,
            "ticker": candidate.ticker,
            "usable_after": filed,
            "alias_used": str(candidate.ticker != symbol).lower(),
        })

    sic_raw = _read_existing_sic(existing_sic_path) + _load_web_rows(web_root, "web_sic_sources.csv.gz")
    first_identity: dict[tuple[str, str], str] = {}
    candidate_by_sid = {candidate.security_id: candidate for candidate in candidates}
    for row in allocated_identity:
        key = (row["security_id"], row["cik"])
        filed = normalize_date(row["filed"])
        first_identity[key] = min(first_identity.get(key, filed), filed)
    sic_allocated: list[dict] = []
    sic_by_cik: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in sic_raw:
        cik = validate_cik(row.get("cik"))
        if cik:
            sic_by_cik[cik].append(row)
    for (sid, cik), identity_filed in sorted(first_identity.items()):
        candidate = candidate_by_sid[sid]
        for row in sic_by_cik.get(cik, ()):
            filed = normalize_date(row.get("filed"))
            if not filed:
                continue
            usable_after = max(filed, identity_filed)
            sic_allocated.append(dict(row) | {
                "security_id": sid,
                "ticker": candidate.ticker,
                "usable_after": usable_after,
                "identity_proof_filed": identity_filed,
            })

    def dedup(rows: Sequence[Mapping[str, object]], keys: Sequence[str]) -> list[dict[str, object]]:
        chosen: dict[tuple[str, ...], dict[str, object]] = {}
        for row in rows:
            key = tuple(str(row.get(k, "")) for k in keys)
            chosen.setdefault(key, dict(row))
        return [chosen[k] for k in sorted(chosen)]

    allocated_identity = dedup(
        allocated_identity, ("security_id", "filed", "cik", "accession", "sec_symbol")
    )
    type_allocated = dedup(
        type_allocated, ("security_id", "filed", "cik", "accession", "classification")
    )
    sic_allocated = dedup(
        sic_allocated, ("security_id", "filed", "cik", "sic", "usable_after")
    )
    ambiguous_identity = dedup(
        ambiguous_identity, ("filed", "sec_symbol", "cik", "accession", "candidate_security_ids")
    )

    grouped_types: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in type_allocated:
        grouped_types[(str(row["security_id"]), str(row["usable_after"]))].append(row)
    type_conflicts: list[dict[str, object]] = []
    admitted_types: list[dict[str, object]] = []
    for key, rows in sorted(grouped_types.items()):
        classes = {str(row["classification"]) for row in rows}
        if len(classes) > 1:
            type_conflicts.append({
                "security_id": key[0],
                "usable_after": key[1],
                "classifications": ";".join(sorted(classes)),
                "reason": "conflicting_security_type_evidence_same_usable_date",
            })
        else:
            admitted_types.extend(rows)
    type_allocated = admitted_types

    output.mkdir(parents=True, exist_ok=True)
    write_gzip_csv(output / "identity_events.csv.gz", [
        "security_id", "ticker", "filed", "usable_after", "cik", "sec_symbol", "accession",
        "document_type", "source_kind", "alias_used", "archive", "archive_sha256", "source_url", "source_sha256",
    ], allocated_identity)
    write_gzip_csv(output / "security_type_events.csv.gz", [
        "security_id", "ticker", "filed", "usable_after", "cik", "sec_symbol", "accession",
        "classification", "security_title_evidence", "authority", "alias_used", "archive", "archive_sha256",
        "source_url", "source_sha256",
    ], type_allocated)
    write_gzip_csv(output / "sic_events.csv.gz", [
        "security_id", "ticker", "filed", "usable_after", "identity_proof_filed", "cik", "sic", "source_kind",
        "accession", "source_url", "source_sha256",
    ], sic_allocated)
    write_gzip_csv(output / "ambiguous_identity_events.csv.gz", [
        "filed", "sec_symbol", "cik", "accession", "candidate_security_ids", "reason",
    ], ambiguous_identity)
    write_gzip_csv(output / "security_type_conflicts.csv.gz", [
        "security_id", "usable_after", "classifications", "reason",
    ], type_conflicts)

    type_sids = {str(row["security_id"]) for row in type_allocated}
    sic_sids = {str(row["security_id"]) for row in sic_allocated}
    identity_sids = {str(row["security_id"]) for row in allocated_identity}
    ambiguous_sids = {
        sid for row in ambiguous_identity
        for sid in str(row.get("candidate_security_ids", "")).split(";") if sid
    }
    conflict_sids = {str(row["security_id"]) for row in type_conflicts}
    unresolved_rows: list[dict[str, object]] = []
    for candidate in candidates:
        reasons: list[str] = []
        if candidate.security_id not in identity_sids:
            reasons.append("no_unambiguous_historical_identity_proof")
        if candidate.unknown_type_observations and candidate.security_id not in type_sids:
            reasons.append("no_admitted_security_type_evidence")
        if candidate.missing_sector_observations and candidate.security_id not in sic_sids:
            reasons.append("no_admitted_sic_evidence")
        if candidate.security_id in ambiguous_sids:
            reasons.append("ambiguous_identity_evidence")
        if candidate.security_id in conflict_sids:
            reasons.append("security_type_conflict")
        if reasons:
            unresolved_rows.append({
                "security_id": candidate.security_id,
                "ticker": candidate.ticker,
                "first_session": candidate.first_session,
                "last_session": candidate.last_session,
                "observations": candidate.observations,
                "unknown_type_observations": candidate.unknown_type_observations,
                "missing_sector_observations": candidate.missing_sector_observations,
                "observed_ciks": ";".join(candidate.observed_ciks),
                "reasons": ";".join(reasons),
            })
    write_gzip_csv(output / "unresolved_episodes.csv.gz", [
        "security_id", "ticker", "first_session", "last_session", "observations",
        "unknown_type_observations", "missing_sector_observations", "observed_ciks", "reasons",
    ], unresolved_rows)

    summary = {
        "schema": f"{SCHEMA_PREFIX}.timeline/1",
        "status": "PASS" if not type_conflicts and not ambiguous_identity else "PARTIAL",
        "admission_status": "READY" if not unresolved_rows else "REVIEW_REQUIRED",
        "causal_rule": "filed < decision_session",
        "continuity_rule": "latest admitted evidence may carry forward only within the same security episode and CIK identity",
        "identity_events": len(allocated_identity),
        "security_type_events": len(type_allocated),
        "sic_events": len(sic_allocated),
        "ambiguous_identity_events": len(ambiguous_identity),
        "security_type_conflicts": len(type_conflicts),
        "unresolved_episode_records": len(unresolved_rows),
    }
    (output / "timeline_coverage.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_checksums(output)
    return summary


def load_discovery_map(path: Path) -> dict[str, set[str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    values = payload.values() if isinstance(payload, dict) else payload
    result: dict[str, set[str]] = defaultdict(set)
    for row in values:
        if not isinstance(row, dict):
            continue
        ticker = norm_ticker(row.get("ticker"))
        cik = validate_cik(row.get("cik_str"))
        if ticker and cik:
            result[ticker].add(cik)
    return result


class SecHttpTransport:
    """Single-process global SEC governor with explicit status-specific retries."""

    def __init__(self, cache: Path, min_interval: float = 0.5, max_attempts: int = 5):
        self.cache = cache
        self.cache.mkdir(parents=True, exist_ok=True)
        self.min_interval = max(0.0, min_interval)
        self.max_attempts = max(1, max_attempts)
        self.last_request_at = 0.0
        self.counters = Counter()
        self.failures: list[dict[str, object]] = []

    def _cache_path(self, url: str) -> Path:
        return self.cache / sha256_bytes(url.encode("utf-8"))

    def _pace(self) -> None:
        wait = self.min_interval - (time.monotonic() - self.last_request_at)
        if wait > 0:
            time.sleep(wait)

    @staticmethod
    def _retry_after(headers: Mapping[str, str]) -> float:
        value = headers.get("Retry-After") or headers.get("retry-after")
        if not value:
            return 0.0
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                when = parsedate_to_datetime(value)
                now = dt.datetime.now(tz=when.tzinfo)
                return max(0.0, (when - now).total_seconds())
            except Exception:
                return 0.0

    def get(self, url: str) -> tuple[bytes | None, HttpResult]:
        path = self._cache_path(url)
        if path.exists():
            data = path.read_bytes()
            self.counters["cache_hits"] += 1
            return data, HttpResult(
                url, 200, path.name, sha256_bytes(data), len(data), 0, False, _utc_now()
            )
        last_error = ""
        for attempt in range(1, self.max_attempts + 1):
            self._pace()
            self.counters["attempts"] += 1
            request = urllib.request.Request(
                url,
                headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity", "Connection": "close"},
            )
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    self.last_request_at = time.monotonic()
                    status = int(getattr(response, "status", 200))
                    data = response.read()
                self.counters["successes"] += 1
                self.counters[f"status_{status}"] += 1
                tmp = path.with_suffix(f".tmp-{os.getpid()}")
                tmp.write_bytes(data)
                tmp.replace(path)
                return data, HttpResult(
                    url, status, path.name, sha256_bytes(data), len(data), attempt, False, _utc_now()
                )
            except urllib.error.HTTPError as exc:
                self.last_request_at = time.monotonic()
                status = int(exc.code)
                self.counters[f"status_{status}"] += 1
                last_error = f"HTTP {status}"
                if status in {404, 410}:
                    self.counters["terminal_absences"] += 1
                    return None, HttpResult(url, status, "", "", 0, attempt, True, _utc_now())
                retryable = status in {403, 429} or 500 <= status <= 599
                if not retryable or attempt == self.max_attempts:
                    break
                self.counters["retries"] += 1
                if status in {403, 429}:
                    self.counters["throttle_retries"] += 1
                    wait = max(5.0, self._retry_after(dict(exc.headers.items())))
                else:
                    wait = min(30.0, 1.0 * (2 ** (attempt - 1)))
                time.sleep(wait)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                self.last_request_at = time.monotonic()
                last_error = repr(exc)
                self.counters["transport_errors"] += 1
                if attempt == self.max_attempts:
                    break
                self.counters["retries"] += 1
                time.sleep(min(30.0, 1.0 * (2 ** (attempt - 1))))
        self.counters["failures"] += 1
        self.failures.append({"url": url, "error": last_error, "attempts": self.max_attempts})
        raise ReconstructionError(f"SEC request failed: {url}: {last_error}")


def fetch_discovery_index(output: Path, min_interval: float = 0.5) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    client = SecHttpTransport(output / ".http-cache", min_interval=min_interval)
    data, result = client.get(SEC_COMPANY_TICKERS)
    if data is None:
        raise ReconstructionError("SEC company_tickers discovery index is absent")
    target = output / "sec_company_tickers.json"
    target.write_bytes(data)
    summary = {
        "schema": f"{SCHEMA_PREFIX}.discovery-source/1",
        "status": "PASS",
        "role": "discovery-only; never causal authority",
        "source": asdict(result),
        "sha256": sha256_bytes(data),
    }
    (output / "discovery_manifest.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_checksums(output, exclude={".http-cache"})
    return summary


def build_web_plan(
    candidates_path: Path,
    timeline_dir: Path,
    output: Path,
    discovery_path: Path | None = None,
) -> dict:
    candidates = load_candidates(candidates_path)
    unresolved = {
        row["security_id"]: row for row in read_gzip_csv(timeline_dir / "unresolved_episodes.csv.gz")
    }
    identity = read_gzip_csv(timeline_dir / "identity_events.csv.gz")
    known_by_sid: dict[str, set[str]] = defaultdict(set)
    for row in identity:
        cik = validate_cik(row.get("cik"))
        if cik:
            known_by_sid[row["security_id"]].add(cik)
    discovery = load_discovery_map(discovery_path) if discovery_path and discovery_path.exists() else {}
    plan_rows: list[dict[str, object]] = []
    no_cik: list[dict[str, object]] = []
    for candidate in candidates:
        if candidate.security_id not in unresolved:
            continue
        reasons = set((unresolved[candidate.security_id].get("reasons") or "").split(";"))
        ciks = set(candidate.observed_ciks) | known_by_sid.get(candidate.security_id, set())
        discovery_only: set[str] = set()
        if not ciks and discovery:
            ciks.update(discovery.get(candidate.ticker, set()))
            if candidate.alias_safe and candidate.alias_symbol:
                ciks.update(discovery.get(candidate.alias_symbol, set()))
            discovery_only = set(ciks)
        if not ciks:
            no_cik.append({
                "security_id": candidate.security_id,
                "ticker": candidate.ticker,
                "reasons": ";".join(sorted(reasons)),
                "reason": "no_valid_cik_for_web_fallback",
            })
            continue
        for cik in sorted(ciks):
            if not validate_cik(cik):
                continue
            plan_rows.append({
                "security_id": candidate.security_id,
                "ticker": candidate.ticker,
                "alias_symbol": candidate.alias_symbol if candidate.alias_safe else "",
                "cik": cik,
                "need_identity": str("no_unambiguous_historical_identity_proof" in reasons).lower(),
                "need_type": str("no_admitted_security_type_evidence" in reasons).lower(),
                "need_sic": str("no_admitted_sic_evidence" in reasons).lower(),
                "discovery_only_cik_hint": str(cik in discovery_only).lower(),
                "first_session": candidate.first_session,
                "last_session": candidate.last_session,
            })
    chosen: dict[tuple[str, str], dict[str, object]] = {}
    for row in plan_rows:
        chosen[(str(row["security_id"]), str(row["cik"]))] = row
    plan_rows = [chosen[key] for key in sorted(chosen)]
    output.mkdir(parents=True, exist_ok=True)
    write_gzip_csv(output / "web_plan.csv.gz", [
        "security_id", "ticker", "alias_symbol", "cik", "need_identity", "need_type", "need_sic",
        "discovery_only_cik_hint", "first_session", "last_session",
    ], plan_rows)
    write_gzip_csv(output / "web_plan_no_cik.csv.gz", [
        "security_id", "ticker", "reasons", "reason"
    ], no_cik)
    summary = {
        "schema": f"{SCHEMA_PREFIX}.web-plan/1",
        "status": "PASS",
        "episode_cik_rows": len(plan_rows),
        "unique_ciks": len({str(row["cik"]) for row in plan_rows}),
        "episodes_without_cik": len(no_cik),
        "discovery_index_role": "discovery-only; never causal authority" if discovery_path else "not supplied",
    }
    (output / "web_plan_coverage.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_checksums(output)
    return summary


def filing_rows(payload: dict) -> Iterator[dict[str, str]]:
    recent = payload.get("filings", {}).get("recent") if isinstance(payload.get("filings"), dict) else None
    table = recent if isinstance(recent, dict) else payload
    if not isinstance(table, dict) or "accessionNumber" not in table:
        return
    keys = ["accessionNumber", "filingDate", "form", "primaryDocument"]
    columns = {key: table.get(key, []) for key in keys}
    for index in range(len(columns["accessionNumber"])):
        yield {
            key: str(columns[key][index] if index < len(columns[key]) else "")
            for key in keys
        }


def filing_url(cik: str, accession: str) -> str:
    return f"{SEC_ARCHIVES}/{int(cik)}/{accession.replace('-', '')}/{accession}.txt"


def select_web_filings(
    rows: Sequence[dict[str, str]], first_session: str, last_session: str
) -> list[dict[str, str]]:
    start_year = int(first_session[:4])
    end_year = int(last_session[:4])
    low = f"{max(1994, start_year - 3)}-01-01"
    high = f"{end_year}-12-31"
    eligible = [row for row in rows if low <= str(row.get("filingDate", "")) <= high]
    periodic = [row for row in eligible if str(row.get("form", "")).upper() in PERIODIC_FORMS]
    ownership = [row for row in eligible if str(row.get("form", "")).upper() in OWNERSHIP_FORMS]
    selected: dict[str, dict[str, str]] = {}
    pre = [row for row in periodic if row["filingDate"] < first_session]
    if pre:
        selected[pre[-1]["accessionNumber"]] = pre[-1]
    for year in range(start_year, end_year + 1):
        in_year = [row for row in periodic if row["filingDate"].startswith(f"{year}-")]
        if in_year:
            annual = [
                row for row in in_year
                if row["form"].upper() in {"10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}
            ]
            chosen = annual[-1] if annual else in_year[-1]
            selected[chosen["accessionNumber"]] = chosen
    pre_ownership = [row for row in ownership if row["filingDate"] < first_session]
    if pre_ownership:
        selected[pre_ownership[-1]["accessionNumber"]] = pre_ownership[-1]
    during_ownership = [row for row in ownership if row["filingDate"] >= first_session]
    if during_ownership:
        selected[during_ownership[0]["accessionNumber"]] = during_ownership[0]
        selected[during_ownership[-1]["accessionNumber"]] = during_ownership[-1]
    return [
        selected[key]
        for key in sorted(selected, key=lambda accession: (selected[accession]["filingDate"], accession))
    ]


def _save_source(root: Path, category: str, url: str, data: bytes) -> tuple[str, str]:
    digest = sha256_bytes(data)
    path = root / "sources" / category / f"{digest}.bin"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() != data:
        raise ReconstructionError(f"content-address collision: {path}")
    if not path.exists():
        path.write_bytes(data)
    return path.relative_to(root).as_posix(), digest


def _load_submission_history_retained(
    client: SecHttpTransport,
    root: Path,
    cik: str,
    filing_from: str = "",
    filing_to: str = "",
) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    records: list[dict[str, object]] = []
    url = f"{SEC_SUBMISSIONS}/CIK{cik}.json"
    data, result = client.get(url)
    if data is None:
        return [], [asdict(result)]
    member, digest = _save_source(root, "submissions", url, data)
    records.append(asdict(result) | {"artifact_member": member, "sha256": digest})
    payload = json.loads(data.decode("utf-8"))
    rows = list(filing_rows(payload))
    files = payload.get("filings", {}).get("files", []) if isinstance(payload.get("filings"), dict) else []
    for metadata in files:
        if not isinstance(metadata, dict):
            continue
        name = str(metadata.get("name") or "")
        if not name:
            continue
        meta_from = normalize_date(metadata.get("filingFrom", ""))
        meta_to = normalize_date(metadata.get("filingTo", ""))
        if filing_from and meta_to and meta_to < filing_from:
            continue
        if filing_to and meta_from and meta_from > filing_to:
            continue
        sub_url = f"{SEC_SUBMISSIONS}/{name}"
        sub_data, sub_result = client.get(sub_url)
        if sub_data is None:
            records.append(asdict(sub_result))
            continue
        member, digest = _save_source(root, "submissions", sub_url, sub_data)
        records.append(asdict(sub_result) | {"artifact_member": member, "sha256": digest})
        try:
            rows.extend(filing_rows(json.loads(sub_data.decode("utf-8"))))
        except json.JSONDecodeError as exc:
            raise ReconstructionError(f"invalid SEC submissions JSON {sub_url}: {exc}") from exc
    unique = {
        (row["accessionNumber"], row["filingDate"], row["form"], row["primaryDocument"]): row
        for row in rows
    }
    return (
        sorted(unique.values(), key=lambda row: (row["filingDate"], row["accessionNumber"])),
        records,
    )


def _cover_ticker_evidence(text: str, ticker: str) -> str:
    if not ticker:
        return ""
    normalized = re.sub(r"\s+", " ", text)
    ticker_re = re.compile(rf"\b{re.escape(ticker)}\b", re.I)
    for match in ticker_re.finditer(normalized):
        window = normalized[max(0, match.start() - 180): min(len(normalized), match.end() + 180)]
        if re.search(r"trading\s+symbols?", window, re.I):
            return clean_title(window)[:500]
    return ""


def _web_cover_type(text: str, ticker: str) -> tuple[str, str]:
    normalized = re.sub(r"\s+", " ", text)
    ticker_re = re.compile(rf"\b{re.escape(ticker)}\b", re.I)
    findings: list[str] = []
    for match in ticker_re.finditer(normalized):
        start = max(0, match.start() - 220)
        end = min(len(normalized), match.end() + 220)
        window = normalized[start:end]
        if any(pattern.search(window) for pattern in COMMON_PATTERNS + NON_COMMON_PATTERNS):
            findings.append(window)
    classifications: set[str] = set()
    for window in findings:
        has_common = any(pattern.search(window) for pattern in COMMON_PATTERNS)
        has_non_common = any(pattern.search(window) for pattern in NON_COMMON_PATTERNS)
        if has_common and not has_non_common:
            classifications.add("common")
        elif has_non_common and not has_common:
            classifications.add("non_common")
        else:
            classifications.add("unknown")
    if classifications == {"common"}:
        return "common", clean_title(findings[0])[:500]
    if classifications == {"non_common"}:
        return "non_common", clean_title(findings[0])[:500]
    return "unknown", ""


def checkpoint_identity(
    source_sha: str, canonical_hash: str, candidates_sha: str, plan_sha: str, parser_sha: str
) -> dict[str, str]:
    return {
        "source_sha": source_sha,
        "canonical_dataset_sha256": canonical_hash,
        "candidates_sha256": candidates_sha,
        "plan_sha256": plan_sha,
        "parser_sha256": parser_sha,
    }


def _write_web_outputs(
    output: Path,
    source_manifest: Sequence[Mapping[str, object]],
    identity: Sequence[Mapping[str, object]],
    types: Sequence[Mapping[str, object]],
    sics: Sequence[Mapping[str, object]],
) -> None:
    def dedup(rows: Sequence[Mapping[str, object]], keys: Sequence[str]) -> list[dict[str, object]]:
        chosen: dict[tuple[str, ...], dict[str, object]] = {}
        for row in rows:
            key = tuple(str(row.get(k, "")) for k in keys)
            chosen.setdefault(key, dict(row))
        return [chosen[key] for key in sorted(chosen)]

    source_manifest = dedup(source_manifest, ("url", "status", "sha256", "artifact_member"))
    identity = dedup(
        identity, ("security_id_hint", "filed", "cik", "accession", "sec_symbol", "source_sha256")
    )
    types = dedup(
        types, ("security_id_hint", "filed", "cik", "accession", "classification", "source_sha256")
    )
    sics = dedup(sics, ("filed", "cik", "sic", "accession", "source_sha256"))
    write_gzip_csv(output / "web_source_manifest.csv.gz", [
        "url", "status", "path", "sha256", "bytes", "attempts", "terminal_absence",
        "retrieved_at", "artifact_member",
    ], source_manifest)
    write_gzip_csv(output / "web_identity_sources.csv.gz", [
        "security_id_hint", "accession", "filed", "cik", "sec_symbol", "document_type", "source_kind",
        "source_url", "source_sha256",
    ], identity)
    write_gzip_csv(output / "web_security_type_sources.csv.gz", [
        "security_id_hint", "accession", "filed", "cik", "sec_symbol", "document_type", "classification",
        "security_title_evidence", "authority", "source_url", "source_sha256",
    ], types)
    write_gzip_csv(output / "web_sic_sources.csv.gz", [
        "filed", "cik", "sic", "source_kind", "accession", "source_url", "source_sha256",
    ], sics)


def normalized_web_evidence_hash(
    identity: Sequence[Mapping[str, object]],
    types: Sequence[Mapping[str, object]],
    sics: Sequence[Mapping[str, object]],
) -> str:
    payload = {
        "identity": sorted({tuple(sorted((str(k), str(v)) for k, v in row.items())) for row in identity}),
        "types": sorted({tuple(sorted((str(k), str(v)) for k, v in row.items())) for row in types}),
        "sics": sorted({tuple(sorted((str(k), str(v)) for k, v in row.items())) for row in sics}),
    }
    return sha256_bytes(canonical_json_bytes(payload))


def fetch_web_fallback(
    plan_path: Path,
    output: Path,
    source_sha: str,
    canonical_hash: str,
    candidates_sha: str,
    parser_sha: str,
    min_interval: float = 0.5,
    max_runtime: float = 18000,
    resume: bool = True,
    probe_limit: int = 0,
) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    plan_sha = sha256_file(plan_path)
    identity = checkpoint_identity(source_sha, canonical_hash, candidates_sha, plan_sha, parser_sha)
    checkpoint_path = output / "checkpoint.json"
    completed_ciks: set[str] = set()
    if resume and checkpoint_path.exists():
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint.get("identity") != identity:
            raise ReconstructionError("resume checkpoint identity mismatch")
        expected_cache_hash = str(checkpoint.get("cache_manifest_sha256") or "")
        actual_cache_hash = directory_content_hash(output / ".http-cache")
        if expected_cache_hash and expected_cache_hash != actual_cache_hash:
            raise ReconstructionError("resume HTTP cache hash mismatch")
        completed_ciks = set(checkpoint.get("completed_ciks", []))

    plan = read_gzip_csv(plan_path)
    by_cik: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in plan:
        cik = validate_cik(row.get("cik"))
        if cik:
            by_cik[cik].append(row)
    ciks = sorted(by_cik)
    if probe_limit:
        ciks = ciks[:probe_limit]
    client = SecHttpTransport(output / ".http-cache", min_interval=min_interval)
    source_manifest: list[dict[str, object]] = []
    identity_rows: list[dict[str, object]] = []
    type_rows: list[dict[str, object]] = []
    sic_rows: list[dict[str, object]] = []

    for filename, target in (
        ("web_source_manifest.csv.gz", source_manifest),
        ("web_identity_sources.csv.gz", identity_rows),
        ("web_security_type_sources.csv.gz", type_rows),
        ("web_sic_sources.csv.gz", sic_rows),
    ):
        path = output / filename
        if path.exists():
            target.extend(read_gzip_csv(path))

    started = time.monotonic()
    technical_failure = False
    for index, cik in enumerate(ciks, 1):
        if cik in completed_ciks:
            continue
        if time.monotonic() - started >= max_runtime:
            break
        try:
            cik_rows = by_cik[cik]
            start_year = min(int(row["first_session"][:4]) for row in cik_rows)
            filing_from = f"{max(1994, start_year - 3)}-01-01"
            filing_to = max(row["last_session"] for row in cik_rows)
            history, manifest = _load_submission_history_retained(
                client, output, cik, filing_from, filing_to
            )
            source_manifest.extend(manifest)
            selected_by_accession: dict[str, tuple[dict[str, str], list[dict[str, str]]]] = {}
            for plan_row in by_cik[cik]:
                for filing in select_web_filings(
                    history, plan_row["first_session"], plan_row["last_session"]
                ):
                    selected_by_accession.setdefault(
                        filing["accessionNumber"], (filing, [])
                    )[1].append(plan_row)
            for accession, (filing, plan_rows_for_filing) in sorted(selected_by_accession.items()):
                if not accession:
                    continue
                url = filing_url(cik, accession)
                raw, result = client.get(url)
                if raw is None:
                    source_manifest.append(asdict(result))
                    continue
                member, digest = _save_source(output, "filings", url, raw)
                source_manifest.append(asdict(result) | {"artifact_member": member, "sha256": digest})
                text = raw.decode("utf-8", errors="replace")
                filed = normalize_date(filing.get("filingDate"))
                sic_match = SIC_RE.search(text)
                symbols = {norm_ticker(value) for value in ISSUER_SYMBOL_RE.findall(text) if norm_ticker(value)}
                for plan_row in plan_rows_for_filing:
                    ticker = norm_ticker(plan_row["ticker"])
                    alias = norm_ticker(plan_row.get("alias_symbol") or "")
                    historical_symbol_match = ticker in symbols or (alias and alias in symbols)
                    cover_ticker = (
                        ticker if _cover_ticker_evidence(text, ticker)
                        else alias if alias and _cover_ticker_evidence(text, alias)
                        else ""
                    )
                    historical_ticker_proof = historical_symbol_match or bool(cover_ticker)
                    discovery_only = plan_row.get("discovery_only_cik_hint") == "true"
                    if historical_ticker_proof:
                        sec_symbol = ticker if ticker in symbols else alias if alias in symbols else cover_ticker
                        identity_rows.append({
                            "security_id_hint": plan_row["security_id"],
                            "accession": accession,
                            "filed": filed,
                            "cik": cik,
                            "sec_symbol": sec_symbol,
                            "document_type": filing.get("form", ""),
                            "source_kind": "SEC_WEB_COMPLETE_SUBMISSION_HISTORICAL_TICKER_OR_COVER",
                            "source_url": url,
                            "source_sha256": digest,
                        })
                    ticker_for_cover = (
                        ticker if ticker in text.upper()
                        else alias if alias and alias in text.upper()
                        else ""
                    )
                    classification, evidence = (
                        _web_cover_type(text, ticker_for_cover) if ticker_for_cover else ("unknown", "")
                    )
                    if classification != "unknown" and (historical_ticker_proof or not discovery_only):
                        type_rows.append({
                            "security_id_hint": plan_row["security_id"],
                            "accession": accession,
                            "filed": filed,
                            "cik": cik,
                            "sec_symbol": ticker_for_cover,
                            "document_type": filing.get("form", ""),
                            "classification": classification,
                            "security_title_evidence": evidence,
                            "authority": "SEC complete-submission cover-page ticker/class co-occurrence",
                            "source_url": url,
                            "source_sha256": digest,
                        })
                    if sic_match and (historical_ticker_proof or not discovery_only):
                        sic_rows.append({
                            "filed": filed,
                            "cik": cik,
                            "sic": sic_match.group(1).zfill(4),
                            "source_kind": "SEC_WEB_COMPLETE_SUBMISSION_HEADER_SIC",
                            "accession": accession,
                            "source_url": url,
                            "source_sha256": digest,
                        })
            completed_ciks.add(cik)
        except (ReconstructionError, json.JSONDecodeError) as exc:
            technical_failure = True
            client.failures.append({"cik": cik, "error": repr(exc)})
            break
        finally:
            _write_web_outputs(output, source_manifest, identity_rows, type_rows, sic_rows)
            checkpoint = {
                "schema": f"{SCHEMA_PREFIX}.checkpoint/1",
                "identity": identity,
                "completed_ciks": sorted(completed_ciks),
                "total_ciks": len(ciks),
                "transport": dict(client.counters),
                "failures": client.failures,
                "cache_manifest_sha256": directory_content_hash(output / ".http-cache"),
                "normalized_evidence_sha256": normalized_web_evidence_hash(
                    identity_rows, type_rows, sic_rows
                ),
            }
            checkpoint_path.write_text(
                json.dumps(checkpoint, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
        print(
            f"[WEB] ciks={len(completed_ciks)}/{len(ciks)} attempts={client.counters['attempts']} "
            f"successes={client.counters['successes']} retries={client.counters['retries']} "
            f"failures={len(client.failures)}",
            flush=True,
        )

    complete = len(completed_ciks) == len(ciks) and not technical_failure
    status = (
        "PASS"
        if complete and not client.failures and client.counters["terminal_absences"] == 0
        else "PARTIAL"
    )
    if not checkpoint_path.exists():
        _write_web_outputs(output, source_manifest, identity_rows, type_rows, sic_rows)
        checkpoint = {
            "schema": f"{SCHEMA_PREFIX}.checkpoint/1",
            "identity": identity,
            "completed_ciks": sorted(completed_ciks),
            "total_ciks": len(ciks),
            "transport": dict(client.counters),
            "failures": client.failures,
            "cache_manifest_sha256": directory_content_hash(output / ".http-cache"),
            "normalized_evidence_sha256": normalized_web_evidence_hash(identity_rows, type_rows, sic_rows),
        }
        checkpoint_path.write_text(
            json.dumps(checkpoint, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    summary = {
        "schema": f"{SCHEMA_PREFIX}.web-fallback/1",
        "status": status,
        "complete": complete,
        "planned_unique_ciks": len(ciks),
        "completed_unique_ciks": len(completed_ciks),
        "transport": dict(client.counters),
        "failures": client.failures,
        "checkpoint_sha256": sha256_file(checkpoint_path),
        "normalized_evidence_sha256": normalized_web_evidence_hash(identity_rows, type_rows, sic_rows),
    }
    (output / "web_coverage.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    write_checksums(output, exclude={".http-cache"})
    return summary


def audit_canonical_coverage(
    dataset: Path,
    timeline_dir: Path,
    output: Path,
    from_year: int = 2006,
    through_year: int = 2026,
) -> dict:
    import bisect

    types = read_gzip_csv(timeline_dir / "security_type_events.csv.gz")
    sics = read_gzip_csv(timeline_dir / "sic_events.csv.gz")
    type_by_sid: dict[str, list[str]] = defaultdict(list)
    sic_by_sid: dict[str, list[str]] = defaultdict(list)
    for row in types:
        type_by_sid[row["security_id"]].append(row["usable_after"])
    for row in sics:
        sic_by_sid[row["security_id"]].append(row["usable_after"])
    for values in type_by_sid.values():
        values.sort()
    for values in sic_by_sid.values():
        values.sort()

    counts = Counter()
    yearly: dict[str, Counter] = defaultdict(Counter)
    for path in observation_files(dataset):
        with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                session = str(row.get("session") or "")[:10]
                if len(session) < 4:
                    continue
                try:
                    year = int(session[:4])
                except ValueError:
                    continue
                if not (from_year <= year <= through_year):
                    continue
                sid = str(row.get("security_id") or "").strip()
                if not sid:
                    continue
                year_key = str(year)
                security_type = str(row.get("security_type") or "").strip().lower()
                need_type = not security_type or security_type == "unknown"
                need_sic = not str(row.get("sic") or "").strip() or not str(row.get("ff12") or "").strip()
                if need_type:
                    counts["unknown_type_observations"] += 1
                    yearly[year_key]["unknown_type_observations"] += 1
                    if bisect.bisect_left(type_by_sid.get(sid, ()), session) > 0:
                        counts["unknown_type_observations_resolved"] += 1
                        yearly[year_key]["unknown_type_observations_resolved"] += 1
                if need_sic:
                    counts["missing_sector_observations"] += 1
                    yearly[year_key]["missing_sector_observations"] += 1
                    if bisect.bisect_left(sic_by_sid.get(sid, ()), session) > 0:
                        counts["missing_sector_observations_resolved"] += 1
                        yearly[year_key]["missing_sector_observations_resolved"] += 1

    def rate(num: int, den: int) -> float:
        return 1.0 if den == 0 else num / den

    summary = {
        "schema": f"{SCHEMA_PREFIX}.canonical-coverage-audit/1",
        "status": "PASS",
        "causal_rule": "usable_after < decision_session",
        "totals": dict(counts),
        "resolution_rates": {
            "security_type": rate(
                counts["unknown_type_observations_resolved"], counts["unknown_type_observations"]
            ),
            "sector": rate(
                counts["missing_sector_observations_resolved"], counts["missing_sector_observations"]
            ),
        },
        "years": {year: dict(counter) for year, counter in sorted(yearly.items())},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def write_checksums(root: Path, exclude: set[str] | None = None) -> Path:
    exclude = exclude or set()
    lines: list[str] = []
    for path in sorted(
        p for p in root.rglob("*") if p.is_file() and p.name != "SHA256SUMS.txt"
    ):
        relative = path.relative_to(root)
        if any(part in exclude for part in relative.parts):
            continue
        lines.append(f"{sha256_file(path)}  {relative.as_posix()}")
    target = root / "SHA256SUMS.txt"
    target.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return target


def verify_checksums(root: Path) -> dict:
    checksum = root / "SHA256SUMS.txt"
    if not checksum.exists():
        raise ReconstructionError(f"missing checksum manifest: {checksum}")
    rows = [
        line.strip() for line in checksum.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    verified = 0
    for line in rows:
        digest, relative = line.split(None, 1)
        path = root / relative.strip()
        if not path.is_file():
            raise ReconstructionError(f"checksum member missing: {relative}")
        if sha256_file(path) != digest:
            raise ReconstructionError(f"checksum mismatch: {relative}")
        verified += 1
    return {"status": "PASS", "verified_files": verified}


def build_final_manifest(
    lock_path: Path,
    candidates_dir: Path,
    bulk_dir: Path,
    web_dir: Path,
    timeline_dir: Path,
    coverage_path: Path,
    source_sha: str,
    output: Path,
) -> dict:
    components = {
        "source_lock_sha256": sha256_file(lock_path),
        "candidates_manifest_sha256": sha256_file(candidates_dir / "SHA256SUMS.txt"),
        "bulk_manifest_sha256": sha256_file(bulk_dir / "SHA256SUMS.txt"),
        "web_manifest_sha256": sha256_file(web_dir / "SHA256SUMS.txt"),
        "timeline_manifest_sha256": sha256_file(timeline_dir / "SHA256SUMS.txt"),
        "canonical_coverage_sha256": sha256_file(coverage_path),
    }
    web = json.loads((web_dir / "web_coverage.json").read_text(encoding="utf-8"))
    timeline = json.loads((timeline_dir / "timeline_coverage.json").read_text(encoding="utf-8"))
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    if web.get("status") != "PASS":
        status = "FAIL"
    elif timeline.get("status") == "PASS":
        status = "PASS"
    else:
        status = "PARTIAL"
    manifest = {
        "schema": f"{SCHEMA_PREFIX}.evidence-package/1",
        "status": status,
        "source_sha": source_sha,
        "causal_rule": "filed/usable_after < decision_session",
        "current_sec_company_tickers_role": "discovery-only; never causal authority",
        "components": components,
        "web": web,
        "timeline": timeline,
        "canonical_coverage": coverage,
        "next_gate": "metadata admission/materiality review before canonical PIT rebuild",
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("verify-source-lock")
    p.add_argument("--lock", type=Path, required=True)
    p.add_argument("--sec-dir", type=Path, required=True)
    p.add_argument("--generated-dir", type=Path, required=True)
    p.add_argument("--canonical-pointer", type=Path, required=True)

    p = sub.add_parser("prepare-candidates")
    p.add_argument("--canonical-dataset", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--from-year", type=int, default=2006)
    p.add_argument("--through-year", type=int, default=2026)

    p = sub.add_parser("parse-bulk")
    p.add_argument("--sec-dir", type=Path, required=True)
    p.add_argument("--candidates", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)

    p = sub.add_parser("derive")
    p.add_argument("--candidates", type=Path, required=True)
    p.add_argument("--bulk", type=Path, required=True)
    p.add_argument("--existing-sic", type=Path, required=True)
    p.add_argument("--web", type=Path)
    p.add_argument("--output", type=Path, required=True)

    p = sub.add_parser("fetch-discovery")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--min-interval", type=float, default=0.5)

    p = sub.add_parser("build-web-plan")
    p.add_argument("--candidates", type=Path, required=True)
    p.add_argument("--timeline", type=Path, required=True)
    p.add_argument("--discovery", type=Path)
    p.add_argument("--output", type=Path, required=True)

    p = sub.add_parser("fetch-web")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--source-sha", required=True)
    p.add_argument("--canonical-hash", required=True)
    p.add_argument("--candidates-sha", required=True)
    p.add_argument("--parser-sha", required=True)
    p.add_argument("--min-interval", type=float, default=0.5)
    p.add_argument("--max-runtime", type=float, default=18000)
    p.add_argument("--probe-limit", type=int, default=0)
    p.add_argument("--no-resume", action="store_true")

    p = sub.add_parser("audit-coverage")
    p.add_argument("--canonical-dataset", type=Path, required=True)
    p.add_argument("--timeline", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)

    p = sub.add_parser("verify")
    p.add_argument("--root", type=Path, required=True)

    p = sub.add_parser("final-manifest")
    p.add_argument("--lock", type=Path, required=True)
    p.add_argument("--candidates-dir", type=Path, required=True)
    p.add_argument("--bulk-dir", type=Path, required=True)
    p.add_argument("--web-dir", type=Path, required=True)
    p.add_argument("--timeline-dir", type=Path, required=True)
    p.add_argument("--coverage", type=Path, required=True)
    p.add_argument("--source-sha", required=True)
    p.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    if args.cmd == "verify-source-lock":
        result = verify_source_lock(
            args.lock, args.sec_dir, args.generated_dir, args.canonical_pointer
        )
    elif args.cmd == "prepare-candidates":
        result = prepare_candidates(
            args.canonical_dataset, args.output, args.from_year, args.through_year
        )
        write_checksums(args.output)
    elif args.cmd == "parse-bulk":
        result = parse_bulk_archives(args.sec_dir, args.candidates, args.output)
    elif args.cmd == "derive":
        result = derive_timeline(
            args.candidates, args.bulk, args.existing_sic, args.output, args.web
        )
    elif args.cmd == "fetch-discovery":
        result = fetch_discovery_index(args.output, args.min_interval)
    elif args.cmd == "build-web-plan":
        result = build_web_plan(args.candidates, args.timeline, args.output, args.discovery)
    elif args.cmd == "fetch-web":
        result = fetch_web_fallback(
            args.plan,
            args.output,
            args.source_sha,
            args.canonical_hash,
            args.candidates_sha,
            args.parser_sha,
            args.min_interval,
            args.max_runtime,
            not args.no_resume,
            args.probe_limit,
        )
        if result["status"] != "PASS":
            print(json.dumps(result, indent=2, sort_keys=True), flush=True)
            return 2
    elif args.cmd == "audit-coverage":
        result = audit_canonical_coverage(args.canonical_dataset, args.timeline, args.output)
    elif args.cmd == "verify":
        result = verify_checksums(args.root)
    elif args.cmd == "final-manifest":
        result = build_final_manifest(
            args.lock,
            args.candidates_dir,
            args.bulk_dir,
            args.web_dir,
            args.timeline_dir,
            args.coverage,
            args.source_sha,
            args.output,
        )
    else:
        raise AssertionError(args.cmd)
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
