#!/usr/bin/env python3
"""Disk-backed parser for retained SEC Form 3/4/5 bulk archives.

The parser deliberately uses SQLite as a bounded-memory staging store. It keeps
only one quarterly archive's title aggregation in memory and emits deterministic
sorted gzip CSVs after all 82 authenticated archives have been parsed.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Iterator

from backtester import historical_metadata_reconstruction_v2 as base

SCHEMA = "backtester.historical-metadata-reconstruction-v2.bulk-corpus/3"


def _member(zf: zipfile.ZipFile, target: str) -> str:
    matches = [name for name in zf.namelist() if Path(name).name.upper() == target.upper()]
    if len(matches) != 1:
        raise base.ReconstructionError(f"expected exactly one {target}; got {matches}")
    return matches[0]


def _schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=NORMAL;
        CREATE TABLE archive_manifest(
          archive TEXT NOT NULL, archive_sha256 TEXT NOT NULL, archive_bytes INTEGER NOT NULL,
          member TEXT NOT NULL, member_sha256 TEXT NOT NULL, member_bytes INTEGER NOT NULL,
          PRIMARY KEY(archive, member, member_sha256)
        ) WITHOUT ROWID;
        CREATE TABLE identity_source(
          accession TEXT NOT NULL, filed TEXT NOT NULL, cik TEXT NOT NULL, sec_symbol TEXT NOT NULL,
          document_type TEXT NOT NULL, source_kind TEXT NOT NULL, archive TEXT NOT NULL,
          archive_sha256 TEXT NOT NULL, member TEXT NOT NULL, member_sha256 TEXT NOT NULL,
          PRIMARY KEY(accession, filed, cik, sec_symbol, archive_sha256)
        ) WITHOUT ROWID;
        CREATE TABLE type_source(
          accession TEXT NOT NULL, filed TEXT NOT NULL, cik TEXT NOT NULL, sec_symbol TEXT NOT NULL,
          document_type TEXT NOT NULL, classification TEXT NOT NULL,
          security_title_evidence TEXT NOT NULL, authority TEXT NOT NULL,
          archive TEXT NOT NULL, archive_sha256 TEXT NOT NULL,
          PRIMARY KEY(accession, filed, cik, sec_symbol, classification, archive_sha256)
        ) WITHOUT ROWID;
        CREATE TABLE title_source(
          accession TEXT NOT NULL, security_title TEXT NOT NULL, source_table TEXT NOT NULL,
          archive TEXT NOT NULL, archive_sha256 TEXT NOT NULL, member_sha256 TEXT NOT NULL,
          PRIMARY KEY(accession, security_title, source_table, archive_sha256)
        ) WITHOUT ROWID;
        """
    )


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def _dict_rows(conn: sqlite3.Connection, sql: str, fields: list[str]) -> Iterator[dict[str, object]]:
    cursor = conn.execute(sql)
    for values in cursor:
        yield dict(zip(fields, values))


def parse_bulk(sec_dir: Path, candidates_path: Path, output: Path) -> dict:
    candidates = base.load_candidates(candidates_path)
    if any(candidate.alias_safe or candidate.alias_symbol for candidate in candidates):
        raise base.ReconstructionError("authoritative bulk parse refuses inferred vendor aliases")
    exact_symbols = {candidate.ticker for candidate in candidates}
    candidate_ciks = {cik for candidate in candidates for cik in candidate.observed_ciks}
    output.mkdir(parents=True, exist_ok=True)
    db = output / ".bulk-work.sqlite"
    for stale in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm")):
        stale.unlink(missing_ok=True)
    conn = sqlite3.connect(db)
    try:
        _schema(conn)
        archives = [sec_dir / name for name in base.expected_archive_names()]
        for index, archive in enumerate(archives, 1):
            if not archive.is_file():
                raise base.ReconstructionError(f"missing SEC archive: {archive}")
            archive_sha = base.sha256_file(archive)
            with zipfile.ZipFile(archive) as zf:
                bad = zf.testzip()
                if bad:
                    raise base.ReconstructionError(f"corrupt ZIP member {bad} in {archive.name}")
                names = {
                    "SUBMISSION.tsv": _member(zf, "SUBMISSION.tsv"),
                    "NONDERIV_TRANS.tsv": _member(zf, "NONDERIV_TRANS.tsv"),
                    "NONDERIV_HOLDING.tsv": _member(zf, "NONDERIV_HOLDING.tsv"),
                }
                data = {label: zf.read(name) for label, name in names.items()}
                hashes = {label: base.sha256_bytes(value) for label, value in data.items()}
                conn.executemany(
                    "INSERT OR IGNORE INTO archive_manifest VALUES (?,?,?,?,?,?)",
                    [
                        (archive.name, archive_sha, archive.stat().st_size, label, hashes[label], len(value))
                        for label, value in data.items()
                    ],
                )

                relevant: dict[str, tuple[str, str, str, str]] = {}
                identity_batch = []
                for row in base._dict_reader_from_bytes(data["SUBMISSION.tsv"]):
                    accession = row.get("ACCESSION_NUMBER", "")
                    filed = base.normalize_date(row.get("FILING_DATE", ""))
                    cik = base.validate_cik(row.get("ISSUERCIK", ""))
                    symbol = base.norm_ticker(row.get("ISSUERTRADINGSYMBOL", ""))
                    form = str(row.get("DOCUMENT_TYPE", "")).upper()
                    if not accession or not filed or not cik or not symbol:
                        continue
                    if symbol not in exact_symbols and cik not in candidate_ciks:
                        continue
                    relevant[accession] = (filed, cik, symbol, form)
                    identity_batch.append((
                        accession, filed, cik, symbol, form, "SEC_FORM345_BULK_SUBMISSION",
                        archive.name, archive_sha, "SUBMISSION.tsv", hashes["SUBMISSION.tsv"],
                    ))
                    if len(identity_batch) >= 5000:
                        conn.executemany("INSERT OR IGNORE INTO identity_source VALUES (?,?,?,?,?,?,?,?,?,?)", identity_batch)
                        identity_batch.clear()
                if identity_batch:
                    conn.executemany("INSERT OR IGNORE INTO identity_source VALUES (?,?,?,?,?,?,?,?,?,?)", identity_batch)

                titles: dict[str, set[str]] = defaultdict(set)
                for member_label, source_table in (
                    ("NONDERIV_TRANS.tsv", "NONDERIV_TRANS"),
                    ("NONDERIV_HOLDING.tsv", "NONDERIV_HOLDING"),
                ):
                    title_batch = []
                    for row in base._dict_reader_from_bytes(data[member_label]):
                        accession = row.get("ACCESSION_NUMBER", "")
                        if accession not in relevant:
                            continue
                        title = base.clean_title(row.get("SECURITY_TITLE", ""))
                        if not title:
                            continue
                        titles[accession].add(title)
                        title_batch.append((
                            accession, title, source_table, archive.name, archive_sha, hashes[member_label]
                        ))
                        if len(title_batch) >= 5000:
                            conn.executemany("INSERT OR IGNORE INTO title_source VALUES (?,?,?,?,?,?)", title_batch)
                            title_batch.clear()
                    if title_batch:
                        conn.executemany("INSERT OR IGNORE INTO title_source VALUES (?,?,?,?,?,?)", title_batch)

                type_batch = []
                for accession, values in sorted(relevant.items()):
                    evidence_titles = titles.get(accession)
                    if not evidence_titles:
                        continue
                    classification, evidence = base.classify_titles(evidence_titles)
                    if not evidence:
                        continue
                    filed, cik, symbol, form = values
                    type_batch.append((
                        accession, filed, cik, symbol, form, classification, evidence,
                        "SEC Form 3/4/5 non-derivative Table I titles joined to SUBMISSION",
                        archive.name, archive_sha,
                    ))
                    if len(type_batch) >= 5000:
                        conn.executemany("INSERT OR IGNORE INTO type_source VALUES (?,?,?,?,?,?,?,?,?,?)", type_batch)
                        type_batch.clear()
                if type_batch:
                    conn.executemany("INSERT OR IGNORE INTO type_source VALUES (?,?,?,?,?,?,?,?,?,?)", type_batch)
                conn.commit()

            print(
                f"[BULK SQLITE] archive={index}/{len(archives)} {archive.name} "
                f"identities={_count(conn,'identity_source')} types={_count(conn,'type_source')} "
                f"titles={_count(conn,'title_source')}",
                flush=True,
            )

        archive_fields = ["archive", "archive_sha256", "archive_bytes", "member", "member_sha256", "member_bytes"]
        identity_fields = [
            "accession", "filed", "cik", "sec_symbol", "document_type", "source_kind",
            "archive", "archive_sha256", "member", "member_sha256",
        ]
        type_fields = [
            "accession", "filed", "cik", "sec_symbol", "document_type", "classification",
            "security_title_evidence", "authority", "archive", "archive_sha256",
        ]
        title_fields = [
            "accession", "security_title", "source_table", "archive", "archive_sha256", "member_sha256",
        ]
        base.write_gzip_csv(
            output / "source_archives.csv.gz", archive_fields,
            _dict_rows(conn, "SELECT * FROM archive_manifest ORDER BY archive,member,member_sha256", archive_fields),
        )
        base.write_gzip_csv(
            output / "bulk_identity_sources.csv.gz", identity_fields,
            _dict_rows(conn, "SELECT * FROM identity_source ORDER BY accession,filed,cik,sec_symbol,archive_sha256", identity_fields),
        )
        base.write_gzip_csv(
            output / "bulk_security_type_sources.csv.gz", type_fields,
            _dict_rows(conn, "SELECT * FROM type_source ORDER BY accession,filed,cik,sec_symbol,classification,archive_sha256", type_fields),
        )
        base.write_gzip_csv(
            output / "bulk_security_title_sources.csv.gz", title_fields,
            _dict_rows(conn, "SELECT * FROM title_source ORDER BY accession,security_title,source_table,archive_sha256", title_fields),
        )
        summary = {
            "schema": SCHEMA,
            "status": "PASS",
            "archives": len(archives),
            "archive_member_manifest_rows": _count(conn, "archive_manifest"),
            "identity_sources": _count(conn, "identity_source"),
            "security_type_sources": _count(conn, "type_source"),
            "security_title_sources": _count(conn, "title_source"),
            "source": "retained SEC Insider Transactions Data Sets Form 3/4/5 quarterly ZIPs",
            "staging": "sqlite_disk_backed_bounded_memory",
            "derivative_tables_used_for_type": False,
        }
        (output / "bulk_coverage.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    finally:
        conn.close()
        for stale in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm")):
            stale.unlink(missing_ok=True)
    base.write_checksums(output)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sec-dir", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = parse_bulk(args.sec_dir, args.candidates, args.output)
    print(json.dumps(result, indent=2, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
