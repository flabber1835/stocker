#!/usr/bin/env python3
"""Build the phase-1 Orion PIT-only input set from supplied Sharadar files.

This builder is deliberately fail-closed:
- raw Sharadar files are read only from the source area;
- source bytes must match the SHA-256 values pinned in MANIFEST.csv;
- only explicitly whitelisted PIT columns are emitted;
- TICKERS is never read;
- output row counts and headers must match MANIFEST.csv exactly;
- every gzip output is fully decompressed after writing to verify integrity.

MANIFEST.csv also retains the compressed byte count and SHA-256 produced by the
original local build as a reference fingerprint. Those compressed bytes are not
a cross-platform gate because zlib/Python versions can produce different gzip
representations of identical CSV payloads. Source hashes, the extraction
whitelist, exact row counts/headers, and successful gzip round-trip are the
fail-closed authority for this phase.

The GitHub workflow builds into a temporary directory first and copies only the
validated manifest-listed outputs into ``PIT input data``.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import pathlib
import re
import zipfile
from collections.abc import Iterable, Iterator


SEP_HEADER = ["ticker", "date", "volume", "closeunadj"]
ACTIONS_HEADER = ["date", "action", "ticker", "value"]
SFP_HEADER = ["ticker", "date", "volume", "closeunadj"]


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_gzip_payload(path: pathlib.Path) -> tuple[str, int]:
    """Hash the exact decompressed CSV payload and force a full gzip CRC check."""
    digest = hashlib.sha256()
    total = 0
    with gzip.open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            total += len(chunk)
    return digest.hexdigest(), total


def load_manifest(path: pathlib.Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise SystemExit(f"empty manifest: {path}")
    required = {
        "file",
        "rows",
        "bytes",
        "columns",
        "sha256",
        "source_file",
        "source_sha256",
    }
    if set(rows[0]) != required:
        raise SystemExit(
            f"unexpected manifest schema: {sorted(rows[0])}; expected {sorted(required)}"
        )
    result = {row["file"]: row for row in rows}
    if len(result) != len(rows):
        raise SystemExit("duplicate output filename in MANIFEST.csv")
    return result


def candidate_sources(
    repo_root: pathlib.Path,
    source_dir: pathlib.Path,
    logical_name: str,
) -> list[pathlib.Path]:
    roots = [source_dir, repo_root]
    candidates: list[pathlib.Path] = []

    sep_match = re.fullmatch(r"SHARADAR_SEP_(\d{4})\.csv(?:\(\d+\))?\.gz", logical_name)
    if sep_match:
        year = sep_match.group(1)
        patterns = [
            f"SHARADAR_SEP_{year}.csv.gz",
            f"SHARADAR_SEP_{year}.csv*.gz",
        ]
    else:
        patterns = [logical_name]

    for root in roots:
        for pattern in patterns:
            candidates.extend(sorted(root.glob(pattern)))

    # Preserve deterministic preference: source_dir exact/normalized names first,
    # then any same-byte duplicate. De-duplicate paths without hiding conflicts.
    unique: list[pathlib.Path] = []
    seen: set[pathlib.Path] = set()
    for path in candidates:
        resolved = path.resolve()
        if path.is_file() and resolved not in seen:
            seen.add(resolved)
            unique.append(path)
    return unique


def resolve_source(
    repo_root: pathlib.Path,
    source_dir: pathlib.Path,
    logical_name: str,
    expected_sha256: str,
) -> pathlib.Path:
    candidates = candidate_sources(repo_root, source_dir, logical_name)
    if not candidates:
        raise SystemExit(f"missing source: {logical_name}")

    observed = [(path, sha256_file(path)) for path in candidates]
    matching = [path for path, digest in observed if digest == expected_sha256]
    if not matching:
        observed_text = ", ".join(f"{path}={digest}" for path, digest in observed)
        raise SystemExit(
            f"source hash mismatch for {logical_name}; expected {expected_sha256}; "
            f"observed {observed_text}"
        )

    chosen = matching[0]
    if len(matching) > 1:
        print(
            f"source duplicate: {logical_name}: using {chosen}; "
            f"{len(matching)} byte-identical candidates match the pinned hash"
        )
    else:
        print(f"source verified: {logical_name}: {chosen}")
    return chosen


def require_columns(reader: csv.DictReader, required: Iterable[str], source: str) -> None:
    fieldnames = reader.fieldnames or []
    missing = [column for column in required if column not in fieldnames]
    if missing:
        raise SystemExit(f"{source} missing required columns: {missing}")


def write_gz(path: pathlib.Path, header: list[str], rows: Iterable[list[str]]) -> int:
    count = 0
    with path.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=1, mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer = csv.writer(text, lineterminator="\n")
                writer.writerow(header)
                for row in rows:
                    writer.writerow(row)
                    count += 1
    return count


def single_csv_member(archive: zipfile.ZipFile, source: pathlib.Path) -> str:
    members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
    if len(members) != 1:
        raise SystemExit(f"{source} must contain exactly one CSV member; found {members}")
    return members[0]


def verify_output(
    path: pathlib.Path,
    row_count: int,
    header: list[str],
    manifest_row: dict[str, str],
) -> None:
    expected_header = manifest_row["columns"].split("|")
    if header != expected_header:
        raise SystemExit(
            f"internal whitelist mismatch for {path.name}: {header} != {expected_header}"
        )

    expected_rows = int(manifest_row["rows"])
    if row_count != expected_rows:
        raise SystemExit(f"row-count mismatch for {path.name}: {row_count} != {expected_rows}")

    # Compressed representation is diagnostic only. Different zlib versions can
    # encode the same CSV payload differently. Never weaken source/content checks
    # just to force equality with these reference gzip bytes.
    reference_bytes = int(manifest_row["bytes"])
    reference_hash = manifest_row["sha256"]
    actual_bytes = path.stat().st_size
    actual_hash = sha256_file(path)
    if actual_bytes != reference_bytes or actual_hash != reference_hash:
        print(
            f"gzip reference differs for {path.name}: "
            f"reference_bytes={reference_bytes} actual_bytes={actual_bytes} "
            f"reference_sha256={reference_hash} actual_sha256={actual_hash}"
        )

    # Read the entire gzip stream. This verifies the CRC/trailer and gives a
    # representation-independent fingerprint of the emitted CSV payload.
    payload_hash, payload_bytes = sha256_gzip_payload(path)

    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        actual_header = next(csv.reader(handle))
    if actual_header != expected_header:
        raise SystemExit(
            f"output header mismatch for {path.name}: {actual_header} != {expected_header}"
        )

    print(
        f"output verified: {path.name}: rows={row_count} "
        f"payload_bytes={payload_bytes} payload_sha256={payload_hash} "
        f"gzip_sha256={actual_hash}"
    )


def build(args: argparse.Namespace) -> None:
    repo_root = args.repo_root.resolve()
    source_dir = (repo_root / args.source_dir).resolve()
    output_dir = args.output_dir.resolve()
    manifest_path = (repo_root / args.manifest).resolve()
    manifest = load_manifest(manifest_path)

    expected_outputs = {
        *(f"SEP_{year}_PIT_ONLY.csv.gz" for year in range(1998, 2027)),
        "ACTIONS_PIT_ONLY.csv.gz",
        "SFP_SPY_BIL_PIT_ONLY.csv.gz",
    }
    if set(manifest) != expected_outputs:
        missing = sorted(expected_outputs - set(manifest))
        extra = sorted(set(manifest) - expected_outputs)
        raise SystemExit(f"manifest output set mismatch; missing={missing}; extra={extra}")

    output_dir.mkdir(parents=True, exist_ok=True)
    for existing in output_dir.iterdir():
        if existing.is_file():
            existing.unlink()
        else:
            raise SystemExit(f"unexpected directory in temporary output: {existing}")

    for year in range(1998, 2027):
        output_name = f"SEP_{year}_PIT_ONLY.csv.gz"
        pin = manifest[output_name]
        source = resolve_source(repo_root, source_dir, pin["source_file"], pin["source_sha256"])

        def sep_rows(source: pathlib.Path = source) -> Iterator[list[str]]:
            with gzip.open(source, "rt", encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                require_columns(reader, SEP_HEADER, str(source))
                for row in reader:
                    yield [row[column] for column in SEP_HEADER]

        output = output_dir / output_name
        count = write_gz(output, SEP_HEADER, sep_rows())
        verify_output(output, count, SEP_HEADER, pin)

    actions_pin = manifest["ACTIONS_PIT_ONLY.csv.gz"]
    actions_source = resolve_source(
        repo_root,
        source_dir,
        actions_pin["source_file"],
        actions_pin["source_sha256"],
    )
    with zipfile.ZipFile(actions_source) as archive:
        member = single_csv_member(archive, actions_source)

        def action_rows() -> Iterator[list[str]]:
            with archive.open(member) as raw, io.TextIOWrapper(
                raw, encoding="utf-8", newline=""
            ) as handle:
                reader = csv.DictReader(handle)
                require_columns(reader, ACTIONS_HEADER, f"{actions_source}::{member}")
                for row in reader:
                    yield [row[column] for column in ACTIONS_HEADER]

        output = output_dir / "ACTIONS_PIT_ONLY.csv.gz"
        count = write_gz(output, ACTIONS_HEADER, action_rows())
        verify_output(output, count, ACTIONS_HEADER, actions_pin)

    sfp_pin = manifest["SFP_SPY_BIL_PIT_ONLY.csv.gz"]
    sfp_source = resolve_source(
        repo_root,
        source_dir,
        sfp_pin["source_file"],
        sfp_pin["source_sha256"],
    )
    with zipfile.ZipFile(sfp_source) as archive:
        member = single_csv_member(archive, sfp_source)

        def sfp_rows() -> Iterator[list[str]]:
            with archive.open(member) as raw, io.TextIOWrapper(
                raw, encoding="utf-8", newline=""
            ) as handle:
                reader = csv.DictReader(handle)
                require_columns(reader, SFP_HEADER, f"{sfp_source}::{member}")
                for row in reader:
                    if row["ticker"] in {"SPY", "BIL"}:
                        yield [row[column] for column in SFP_HEADER]

        output = output_dir / "SFP_SPY_BIL_PIT_ONLY.csv.gz"
        count = write_gz(output, SFP_HEADER, sfp_rows())
        verify_output(output, count, SFP_HEADER, sfp_pin)

    actual_outputs = {path.name for path in output_dir.iterdir() if path.is_file()}
    if actual_outputs != expected_outputs:
        missing = sorted(expected_outputs - actual_outputs)
        extra = sorted(actual_outputs - expected_outputs)
        raise SystemExit(f"temporary output set mismatch; missing={missing}; extra={extra}")

    print(
        f"PIT-only build PASS: {len(actual_outputs)} files; "
        "no TICKERS or non-whitelisted fields emitted"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=pathlib.Path, default=pathlib.Path("."))
    parser.add_argument("--source-dir", type=pathlib.Path, default=pathlib.Path("sharadar"))
    parser.add_argument("--output-dir", type=pathlib.Path, required=True)
    parser.add_argument(
        "--manifest",
        type=pathlib.Path,
        default=pathlib.Path("PIT input data/MANIFEST.csv"),
    )
    return parser.parse_args()


if __name__ == "__main__":
    build(parse_args())
