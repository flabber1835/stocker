#!/usr/bin/env python3
"""Split a bulk SHARADAR_SEP.zip into durable per-year replay files.

Every year is generated and fsynced in staging first. Promotion is protected by
an fsynced marker and backups, so a killed promotion is deterministically
restored before another generation begins.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import os
import secrets
import shutil
import sys
import zipfile
from pathlib import Path

FIRST_YEAR = 1998
DEFAULT_LAST_YEAR = 2026
MODULUS = 1 << 256
PROMOTION_MARKER = ".sentinel-sep-promotion.json"
PROMOTION_SCHEMA = "sentinel.sep-promotion/1"


class YearWriter:
    """One staged per-year gzip plus its running fingerprint."""

    def __init__(self, path: Path, header: str):
        self.path = path
        self.raw = path.open("wb")
        self.fh = gzip.GzipFile(filename="", mode="wb", fileobj=self.raw, mtime=0)
        self.fh.write(header.encode())
        self.rows = 0
        self.first_date = None
        self.last_date = None
        self.tickers = set()
        self.fingerprint = 0
        self._closed = False

    def write(self, line: str, date: str, ticker: str):
        self.fh.write(line.encode())
        self.rows += 1
        if self.first_date is None or date < self.first_date:
            self.first_date = date
        if self.last_date is None or date > self.last_date:
            self.last_date = date
        self.tickers.add(ticker)
        digest = hashlib.sha256(line.encode()).digest()
        self.fingerprint = (self.fingerprint + int.from_bytes(digest, "big")) % MODULUS

    def close(self) -> dict:
        if not self._closed:
            self.fh.close()
            self.raw.flush()
            os.fsync(self.raw.fileno())
            self.raw.close()
            self._closed = True
        return {
            "file": self.path.name,
            "rows": self.rows,
            "first_date": self.first_date,
            "last_date": self.last_date,
            "distinct_tickers": len(self.tickers),
            "content_fingerprint": f"{self.fingerprint:064x}",
            "sha256_of_gzip": _sha256(self.path),
        }

    def abort(self) -> None:
        if self._closed:
            return
        try:
            self.fh.close()
        finally:
            try:
                self.raw.close()
            finally:
                self._closed = True


def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def _fsync_file(path: Path) -> None:
    with path.open("rb") as fh:
        os.fsync(fh.fileno())


def _fsync_dir(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    fd = os.open(str(path), flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_json_fsynced(path: Path, payload: dict) -> None:
    temp = path.parent / ("." + path.name + ".tmp." + secrets.token_hex(8))
    try:
        with temp.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(str(temp), str(path))
        _fsync_dir(path.parent)
    finally:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass


def _validate_year(path: Path, *, expected_name: str,
                   expected_sha256: str | None = None) -> None:
    if not path.is_file() or path.name != expected_name:
        raise RuntimeError(f"missing staged SEP member {expected_name}")
    with gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        header = fh.readline()
    columns = next(csv.reader([header])) if header else []
    if "date" not in columns or "ticker" not in columns:
        raise RuntimeError(f"invalid SEP header in {path}")
    if expected_sha256 is not None and _sha256(path) != expected_sha256:
        raise RuntimeError(f"SEP member changed after validation: {path}")


def _marker_payload(*, phase: str, token: str, staging: Path,
                    entries: list[dict]) -> dict:
    return {
        "schema": PROMOTION_SCHEMA,
        "phase": phase,
        "token": token,
        "staging": str(staging),
        "entries": entries,
    }


def _load_marker(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
    except Exception as exc:
        raise SystemExit(f"REFUSED: unreadable SEP promotion marker {path}: {exc}")
    if (not isinstance(value, dict)
            or value.get("schema") != PROMOTION_SCHEMA
            or value.get("phase") not in {"PREPARED", "BACKED_UP", "COMMITTED"}
            or not isinstance(value.get("entries"), list)
            or not isinstance(value.get("staging"), str)):
        raise SystemExit(f"REFUSED: malformed SEP promotion marker {path}")
    required = {"final", "staged", "backup", "had_original", "sha256"}
    for entry in value["entries"]:
        if not isinstance(entry, dict) or set(entry) != required:
            raise SystemExit(f"REFUSED: malformed SEP promotion entry in {path}")
        if not isinstance(entry["had_original"], bool):
            raise SystemExit(f"REFUSED: malformed SEP promotion entry in {path}")
    return value


def _cleanup_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    else:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _recover_promotion(out: Path) -> None:
    marker = out / PROMOTION_MARKER
    if not marker.exists():
        return
    value = _load_marker(marker)
    phase = value["phase"]
    entries = value["entries"]
    touched_dirs = {out}

    if phase == "COMMITTED":
        for entry in entries:
            final = Path(entry["final"])
            if not final.is_file() or _sha256(final) != entry["sha256"]:
                raise SystemExit(
                    "REFUSED: committed SEP promotion marker does not match "
                    f"final artifact {final}")
            touched_dirs.add(final.parent)
        for entry in entries:
            _cleanup_path(Path(entry["backup"]))
            _cleanup_path(Path(entry["staged"]))
        _cleanup_path(Path(value["staging"]))
        marker.unlink()
        for directory in touched_dirs:
            _fsync_dir(directory)
        return

    # PREPARED means no new file was promoted. Some originals may already have
    # been moved to backup. BACKED_UP means every original is in backup and a
    # subset of new files may have been promoted. In both states old wins.
    for entry in entries:
        final = Path(entry["final"])
        backup = Path(entry["backup"])
        touched_dirs.add(final.parent)
        if entry["had_original"]:
            if backup.exists():
                os.replace(str(backup), str(final))
            elif phase == "BACKED_UP":
                raise SystemExit(
                    "REFUSED: interrupted SEP promotion lost required backup "
                    f"for {final}")
            elif not final.exists():
                raise SystemExit(
                    "REFUSED: interrupted SEP backup left neither original nor "
                    f"backup for {final}")
        elif phase == "BACKED_UP" and final.exists():
            final.unlink()
        _cleanup_path(Path(entry["staged"]))
    _cleanup_path(Path(value["staging"]))
    marker.unlink()
    for directory in touched_dirs:
        _fsync_dir(directory)
    print("restored prior SEP generation after interrupted promotion",
          file=sys.stderr)


def _promote_generation(*, out: Path, staging: Path, fingerprint_staged: Path,
                        fingerprint_final: Path, years: list[int],
                        report: dict) -> None:
    marker = out / PROMOTION_MARKER
    token = staging.name.rsplit(".", 1)[-1]
    backup_dir = out / (".sentinel-sep-backup." + token)
    backup_dir.mkdir()
    entries: list[dict] = []

    for year in years:
        name = f"SHARADAR_SEP_{year}.csv.gz"
        final = out / name
        staged = staging / name
        entries.append({
            "final": str(final),
            "staged": str(staged),
            "backup": str(backup_dir / name),
            "had_original": final.exists(),
            "sha256": report["years"][str(year)]["sha256_of_gzip"],
        })
    fingerprint_backup = fingerprint_final.parent / (
        "." + fingerprint_final.name + ".sep-backup." + token)
    entries.append({
        "final": str(fingerprint_final),
        "staged": str(fingerprint_staged),
        "backup": str(fingerprint_backup),
        "had_original": fingerprint_final.exists(),
        "sha256": _sha256(fingerprint_staged),
    })

    _write_json_fsynced(
        marker, _marker_payload(
            phase="PREPARED", token=token, staging=staging, entries=entries))

    touched_dirs = {out, fingerprint_final.parent}
    for entry in entries:
        if entry["had_original"]:
            os.replace(entry["final"], entry["backup"])
    for directory in touched_dirs:
        _fsync_dir(directory)

    _write_json_fsynced(
        marker, _marker_payload(
            phase="BACKED_UP", token=token, staging=staging, entries=entries))

    for entry in entries:
        os.replace(entry["staged"], entry["final"])
    for directory in touched_dirs:
        _fsync_dir(directory)

    for entry in entries:
        final = Path(entry["final"])
        if not final.is_file() or _sha256(final) != entry["sha256"]:
            raise RuntimeError(f"promoted SEP artifact failed validation: {final}")

    _write_json_fsynced(
        marker, _marker_payload(
            phase="COMMITTED", token=token, staging=staging, entries=entries))

    for entry in entries:
        _cleanup_path(Path(entry["backup"]))
    _cleanup_path(backup_dir)
    _cleanup_path(staging)
    marker.unlink()
    for directory in touched_dirs:
        _fsync_dir(directory)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--zip", dest="zip_path", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True,
                    help="directory to write SHARADAR_SEP_{YYYY}.csv.gz into")
    ap.add_argument("--fingerprint", type=Path, default=Path("sep-fingerprint.json"))
    ap.add_argument("--last-year", type=int, default=DEFAULT_LAST_YEAR)
    ap.add_argument("--force", action="store_true",
                    help="replace an existing complete per-year generation")
    args = ap.parse_args()

    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)
    args.fingerprint.parent.mkdir(parents=True, exist_ok=True)
    _recover_promotion(out)

    years = list(range(FIRST_YEAR, args.last_year + 1))
    existing = [y for y in years if (out / f"SHARADAR_SEP_{y}.csv.gz").exists()]
    if existing and not args.force:
        raise SystemExit(
            f"{len(existing)} per-year files already exist in {out} "
            f"(first: SHARADAR_SEP_{existing[0]}.csv.gz). Pass --force to "
            "replace the generation after complete staging and validation.")

    token = secrets.token_hex(12)
    staging = out / (".sentinel-sep-staging." + token)
    staging.mkdir()
    fingerprint_staged = args.fingerprint.parent / (
        "." + args.fingerprint.name + ".sep-stage." + token)
    writers: dict[int, YearWriter] = {}
    try:
        with zipfile.ZipFile(args.zip_path) as z:
            names = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if len(names) != 1:
                raise SystemExit(
                    f"expected one CSV inside {args.zip_path}, found {names}")
            inner = names[0]
            print(f"reading {inner} from {args.zip_path}", file=sys.stderr)

            with z.open(inner) as raw:
                text = io.TextIOWrapper(raw, "utf-8", newline="")
                header = text.readline()
                if not header:
                    raise SystemExit("empty CSV")
                cols = next(csv.reader([header]))
                try:
                    i_date = cols.index("date")
                    i_ticker = cols.index("ticker")
                except ValueError:
                    raise SystemExit(f"no date/ticker column in header: {cols}")

                writers = {
                    y: YearWriter(staging / f"SHARADAR_SEP_{y}.csv.gz", header)
                    for y in years
                }
                skipped_years = {}
                malformed = 0
                total = 0

                for line in text:
                    if not line.strip():
                        continue
                    parts = line.rstrip("\n").split(",")
                    if len(parts) <= max(i_date, i_ticker):
                        parts = next(csv.reader([line]))
                        if len(parts) <= max(i_date, i_ticker):
                            malformed += 1
                            continue
                    date = parts[i_date]
                    try:
                        year = int(date[:4])
                    except ValueError:
                        malformed += 1
                        continue
                    writer = writers.get(year)
                    if writer is None:
                        skipped_years[year] = skipped_years.get(year, 0) + 1
                        continue
                    writer.write(
                        line if line.endswith("\n") else line + "\n",
                        date, parts[i_ticker])
                    total += 1
                    if total % 5_000_000 == 0:
                        print(f"  {total:,} rows ...", file=sys.stderr)

        report = {
            "source_zip": str(args.zip_path),
            "source_zip_sha256": _sha256(args.zip_path),
            "inner_csv": inner,
            "columns": cols,
            "rows_written": total,
            "malformed_rows_skipped": malformed,
            "rows_outside_year_range": skipped_years,
            "years": {},
        }
        for year in years:
            report["years"][str(year)] = writers[year].close()
            staged = staging / f"SHARADAR_SEP_{year}.csv.gz"
            _validate_year(
                staged, expected_name=staged.name,
                expected_sha256=report["years"][str(year)]["sha256_of_gzip"])
        _fsync_dir(staging)

        with fingerprint_staged.open("w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        _fsync_dir(fingerprint_staged.parent)

        _promote_generation(
            out=out, staging=staging,
            fingerprint_staged=fingerprint_staged,
            fingerprint_final=args.fingerprint,
            years=years, report=report)
    except BaseException:
        for writer in writers.values():
            writer.abort()
        # Once a marker exists recovery owns cleanup; deleting staging here
        # would destroy evidence needed to restore a backed-up generation.
        if not (out / PROMOTION_MARKER).exists():
            _cleanup_path(staging)
            _cleanup_path(fingerprint_staged)
        raise

    empty = [y for y in years if report["years"][str(y)]["rows"] == 0]
    print(f"\n  rows written        {total:,}")
    print(f"  malformed skipped   {malformed:,}")
    if skipped_years:
        print(f"  outside {FIRST_YEAR}-{args.last_year}: {skipped_years}")
    print(f"  per-year files      {len(years)}  ({FIRST_YEAR}..{args.last_year})")
    if empty:
        print(f"  EMPTY years         {empty}")
    print(f"  fingerprint written {args.fingerprint}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
