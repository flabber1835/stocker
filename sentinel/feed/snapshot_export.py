"""Verified local export evidence for historical replay."""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import io
from typing import Iterable, Mapping
import zipfile

from sentinel.feed import acquisition_limits as limits, archive_tables


class SnapshotExportError(archive_tables.RequestError):
    pass


class ExportPending(archive_tables.RetryDeferred):
    def __init__(self, table, status, params):
        super().__init__(30)
        self.table, self.export_status, self.params = table, status, dict(params or {})


@dataclass(frozen=True)
class ExportSnapshot:
    table: str
    params: Mapping[str, str]
    link: str = field(repr=False)
    snapshot: datetime
    refreshed: datetime


def probe_snapshot(table, *, params=None):
    raise archive_tables.CaptureRequired("A new remote export cannot be used as a historical snapshot")


def download_snapshot(snapshot, *, required):
    from sentinel.feed import acquisition_work as work
    blob = work.read_cached(snapshot)
    if blob is None:
        raise archive_tables.CaptureRequired("Verified historical export bytes are unavailable")
    rows = _csv_rows(blob, required=required)
    return rows, {
        "authority": "nasdaq-data-link-table-export/v1", "table": snapshot.table,
        "file_status": "fresh", "data_snapshot_time": snapshot.snapshot.isoformat(),
        "last_refreshed_time": snapshot.refreshed.isoformat(),
        "source_rows": len(rows), "file_sha256": hashlib.sha256(blob).hexdigest(),
        "window": dict(snapshot.params),
    }


def _fetch_complete(table, *, params, required):
    from sentinel.feed import operational_source
    capture = operational_source.current()
    if capture is None:
        raise archive_tables.CaptureRequired("Verified historical export rows are unavailable")
    return capture.export_rows(table, params, required=required)


def require_actions_refresh(*, through, evidence):
    raise archive_tables.CaptureRequired("A historical file cannot corroborate a new source observation")


def _csv_rows(blob: bytes, *, required: set[str]) -> list[dict]:
    try:
        limits.check_zip_directory(blob)
        archive = zipfile.ZipFile(io.BytesIO(blob))
    except (zipfile.BadZipFile, ValueError) as exc:
        raise SnapshotExportError(
            "Archived export body is not a valid ZIP archive") from exc
    with archive:
        limits.check("ZIP_ENTRIES", len(archive.infolist()), limits.ZIP_ENTRIES)
        files = [name for name in archive.namelist()
                 if not name.endswith("/") and name.lower().endswith(".csv")]
        if len(files) != 1:
            raise SnapshotExportError(
                f"Archived export must contain exactly one CSV, found {len(files)}")
        info = archive.getinfo(files[0])
        if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED} or info.flag_bits & 1:
            raise SnapshotExportError("Archived export CSV uses unsupported compression or encryption")
        limits.check("CSV_BYTES", info.file_size, limits.CSV_BYTES)
        with archive.open(files[0]) as raw, io.TextIOWrapper(
                io.BufferedReader(limits.ExpandedReader(raw)), encoding="utf-8-sig", newline="") as text:
            lines = limits.RecordLines(text)
            reader = csv.reader(lines)
            fields = next(reader, [])
            limits.check("COLUMNS", len(fields), limits.COLUMNS)
            if len(fields) != len(set(fields)) or any(not str(x).strip() for x in fields):
                raise SnapshotExportError(
                    "Archived export CSV has invalid/duplicate column names")
            missing = required.difference(fields)
            if missing:
                raise SnapshotExportError(
                    "Archived export CSV lacks required column(s): "
                    + ", ".join(sorted(missing)))
            rows: list[dict] = []
            while True:
                lines.total = 0
                row = next(reader, None)
                if row is None:
                    break
                if not row:
                    continue  # Preserve DictReader's blank-line semantics.
                limits.check("ROWS", len(rows) + 1, limits.ROWS)
                limits.check("CELLS", (len(rows) + 1) * len(fields), limits.CELLS)
                if len(row) > len(fields):
                    raise SnapshotExportError(
                        "Archived export CSV contains a row wider than its header")
                rows.append({key: (None if value == "" else value)
                             for key, value in zip(fields, row + [None] * (len(fields) - len(row)))})
            return rows


def fetch_complete_actions(*, through: str, **kwargs) -> tuple[list[dict], dict]:
    return _fetch_complete(
        archive_tables.ACTIONS,
        params={"date.gte": "1900-01-01", "date.lte": str(through)},
        required={"date", "action", "ticker", "name", "value",
                  "contraticker", "contraname"}, **kwargs)


def fetch_complete_sep(*, start: str, end: str, **kwargs) -> tuple[list[dict], dict]:
    """Complete bounded SEP file used for current decision-history proof."""
    return _fetch_complete(
        archive_tables.SEP,
        params={"date.gte": str(start), "date.lte": str(end)},
        required={"ticker", "date", "open", "close", "closeunadj", "volume",
                  "lastupdated"}, **kwargs)


def fetch_complete_ticker_keys(**kwargs) -> tuple[set[tuple[str, str]], dict]:
    rows, evidence = _fetch_complete(
        archive_tables.TICKERS, params=None,
        required={"table", "permaticker", "ticker"}, **kwargs)
    keys: set[tuple[str, str]] = set()
    for row in rows:
        if str(row.get("table") or "").strip().upper() != "SEP":
            continue
        permaticker = str(row.get("permaticker") or "").strip()
        ticker = str(row.get("ticker") or "").strip().upper()
        if permaticker and ticker:
            keys.add((permaticker, ticker))
    if not keys:
        raise SnapshotExportError(
            "Archived TICKERS export contains no usable table=SEP identity keys")
    evidence = dict(evidence)
    evidence["sep_identity_keys"] = len(keys)
    return keys, evidence


def assert_complete_ticker_keys(paged_rows: Iterable[Mapping], export_keys) -> None:
    paged = {
        (str(row.get("permaticker") or "").strip(),
         str(row.get("ticker") or "").strip().upper())
        for row in paged_rows
        if str(row.get("table") or "").strip().upper() == "SEP"
        and str(row.get("permaticker") or "").strip()
        and str(row.get("ticker") or "").strip()
    }
    exported = set(export_keys)
    if paged == exported:
        return
    missing = sorted(exported - paged)
    extra = sorted(paged - exported)
    raise SnapshotExportError(
        "Source paginated TICKERS key set disagrees with the vendor fresh "
        f"whole-table export: paged={len(paged):,}, export={len(exported):,}, "
        f"missing_from_pages={missing[:8]}, extra_in_pages={extra[:8]}. "
        "Refusing common-mode partial TICKERS/SEP authority.")
