"""Vendor-backed complete-table snapshots for negative-space authority.

Nasdaq Data Link's ordinary Tables API is cursor-paginated and exposes no
immutable generation token for a traversal.  Repeating a traversal proves that
the observed content stopped changing; it cannot prove a stable partial result
contains every row.

The official Tables *Exporter* has a stronger contract for the narrow cases
where absence/removal is itself economic authority: ``qopts.export=true``
generates the entire requested table as one zipped CSV and reports both
``file.data_snapshot_time`` and ``datatable.last_refreshed_time``.  Sentinel
accepts only a ``fresh`` file whose snapshot creation began at or after the
vendor's latest table refresh.

This module is deliberately separate from the normal Sharadar transport.  A
large export is too expensive for every ordinary data read; it is used for
periodic complete ACTIONS reconciliation, where one omitted split/dividend/
terminal row is more dangerous than the extra I/O.
"""
from __future__ import annotations

import csv
import io
import math
import os
import time
import zipfile
from datetime import datetime, timezone
from typing import Callable, Mapping
from urllib.parse import urlparse

from sentinel.feed import sharadar

EXPORT_MAX_POLLS = int(os.getenv("SHARADAR_EXPORT_MAX_POLLS", "20"))
EXPORT_POLL_SECONDS = float(os.getenv("SHARADAR_EXPORT_POLL_SECONDS", "30"))


class SharadarSnapshotExportError(sharadar.SharadarRequestError):
    """The provider could not prove a complete, current export snapshot."""


def _aware_iso(value, *, field: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise SharadarSnapshotExportError(
            f"Sharadar export omitted required {field}")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SharadarSnapshotExportError(
            f"Sharadar export returned invalid {field}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _decode_export_status(payload) -> tuple[str, str | None, datetime, datetime]:
    if not isinstance(payload, dict):
        raise SharadarSnapshotExportError(
            "Sharadar export status root is not an object")
    root = payload.get("datatable_bulk_download")
    if not isinstance(root, dict):
        raise SharadarSnapshotExportError(
            "Sharadar export status lacks datatable_bulk_download")
    file_info = root.get("file")
    table_info = root.get("datatable")
    if not isinstance(file_info, dict) or not isinstance(table_info, dict):
        raise SharadarSnapshotExportError(
            "Sharadar export status lacks file/datatable evidence")
    status = str(file_info.get("status") or "").strip().lower()
    if status not in {"fresh", "creating", "regenerating"}:
        raise SharadarSnapshotExportError(
            f"Sharadar export returned unknown file status {status!r}")
    link = file_info.get("link")
    if link is not None:
        link = str(link).strip() or None
    snapshot = _aware_iso(
        file_info.get("data_snapshot_time"), field="data_snapshot_time")
    refreshed = _aware_iso(
        table_info.get("last_refreshed_time"), field="last_refreshed_time")
    return status, link, snapshot, refreshed


def _safe_download(client, link: str, *, http, sleep, now) -> bytes:
    """Download an export without ever rendering its credential-bearing URL."""
    parsed = urlparse(str(link))
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise SharadarSnapshotExportError(
            "Sharadar export supplied a non-HTTPS download link")
    last_kind = "transport failure"
    for attempt in range(sharadar.FETCH_MAX_RETRIES):
        status = None
        retry_after = None
        try:
            with sharadar._quiet_http_client_diagnostics():
                response = client.get(link)
            status = int(response.status_code)
            if status in sharadar.RETRYABLE_STATUS:
                retry_after = response.headers.get("Retry-After")
                raise RuntimeError("retryable download status")
            response.raise_for_status()
            return bytes(response.content)
        except sharadar.SharadarRetryDeferred:
            raise
        except Exception as exc:  # noqa: BLE001 -- classified without URL
            if status is not None and status not in sharadar.RETRYABLE_STATUS:
                raise SharadarSnapshotExportError(
                    f"Sharadar snapshot download failed with HTTP {status}") from None
            if not sharadar._is_transport_error(exc, http) and status is None:
                raise SharadarSnapshotExportError(
                    f"Sharadar snapshot download failed ({type(exc).__name__})") from None
            last_kind = f"HTTP {status}" if status is not None else type(exc).__name__
        if attempt < sharadar.FETCH_MAX_RETRIES - 1:
            delay = sharadar.retry_delay(
                attempt, status, retry_after,
                now=now or (lambda: datetime.now(timezone.utc)))
            sleep(delay)
    raise SharadarSnapshotExportError(
        f"Sharadar snapshot download failed after "
        f"{sharadar.FETCH_MAX_RETRIES} attempt(s) ({last_kind})")


def _csv_rows(blob: bytes, *, required: set[str]) -> list[dict]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(blob))
    except (zipfile.BadZipFile, ValueError) as exc:
        raise SharadarSnapshotExportError(
            "Sharadar export body is not a valid ZIP archive") from exc
    with archive:
        files = [name for name in archive.namelist()
                 if not name.endswith("/") and name.lower().endswith(".csv")]
        if len(files) != 1:
            raise SharadarSnapshotExportError(
                f"Sharadar export must contain exactly one CSV, found {len(files)}")
        with archive.open(files[0]) as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
            reader = csv.DictReader(text)
            fields = list(reader.fieldnames or [])
            if len(fields) != len(set(fields)) or any(not str(x).strip() for x in fields):
                raise SharadarSnapshotExportError(
                    "Sharadar export CSV has invalid/duplicate column names")
            missing = required.difference(fields)
            if missing:
                raise SharadarSnapshotExportError(
                    "Sharadar export CSV lacks required column(s): "
                    + ", ".join(sorted(missing)))
            rows: list[dict] = []
            for row in reader:
                if None in row:
                    raise SharadarSnapshotExportError(
                        "Sharadar export CSV contains a row wider than its header")
                rows.append({key: (None if value == "" else value)
                             for key, value in row.items()})
            return rows


def fetch_complete_actions(
        *, through: str, http=None, sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] | None = None,
        poll_seconds: float | None = None,
        max_polls: int | None = None) -> tuple[list[dict], dict]:
    """Return one vendor-generated complete ACTIONS snapshot through ``through``.

    The returned evidence is safe to persist in the corpus publication record;
    it contains timestamps/counts only, never the signed download URL or API key.
    """
    sharadar.validate_config()
    if EXPORT_MAX_POLLS < 1 or not math.isfinite(EXPORT_POLL_SECONDS) \
            or EXPORT_POLL_SECONDS < 0:
        raise ValueError(
            "SHARADAR_EXPORT_MAX_POLLS must be >=1 and poll seconds finite >=0")
    polls = EXPORT_MAX_POLLS if max_polls is None else int(max_polls)
    delay = EXPORT_POLL_SECONDS if poll_seconds is None else float(poll_seconds)
    if polls < 1 or not math.isfinite(delay) or delay < 0:
        raise ValueError("invalid Sharadar export polling configuration")

    if http is None:
        import httpx  # noqa: PLC0415
        http = httpx
    key = sharadar._api_key()
    url = f"{sharadar.NDL_BASE}/{sharadar.ACTIONS}.json"
    params: dict[str, object] = {
        "api_key": key,
        "qopts.export": "true",
        "date.gte": "1900-01-01",
        "date.lte": str(through),
    }

    with http.Client(timeout=sharadar.FETCH_TIMEOUT_SECS) as client:
        for poll in range(1, polls + 1):
            response = sharadar._get_with_retry(
                client, url, params, http=http, sleep=sleep, now=now)
            try:
                payload = response.json()
            except Exception as exc:
                raise SharadarSnapshotExportError(
                    "Sharadar export status HTTP 200 body is not valid JSON") from exc
            status, link, snapshot, refreshed = _decode_export_status(payload)
            if status == "fresh":
                if link is None:
                    raise SharadarSnapshotExportError(
                        "Sharadar fresh export supplied no download link")
                if snapshot < refreshed:
                    raise SharadarSnapshotExportError(
                        "Sharadar export claims fresh but its data snapshot began "
                        "before the table's last refresh")
                blob = _safe_download(
                    client, link, http=http, sleep=sleep, now=now)
                rows = _csv_rows(blob, required={
                    "date", "action", "ticker", "name", "value",
                    "contraticker", "contraname",
                })
                return rows, {
                    "authority": "nasdaq-data-link-table-export/v1",
                    "file_status": status,
                    "data_snapshot_time": snapshot.isoformat(),
                    "last_refreshed_time": refreshed.isoformat(),
                    "source_rows": len(rows),
                }
            if poll < polls:
                sleep(delay)
    raise SharadarSnapshotExportError(
        f"Sharadar ACTIONS export did not become fresh after {polls} poll(s)")


__all__ = [
    "SharadarSnapshotExportError", "fetch_complete_actions",
]
