"""Vendor-backed complete-table snapshots for negative-space authority.

Nasdaq Data Link's ordinary Tables API is cursor-paginated and exposes no
immutable generation token for a traversal. Repeating a traversal proves that
the observed content stopped changing; it cannot prove a stable partial result
contains every row.

The official Tables *Exporter* has a stronger contract for the narrow cases
where absence/removal is itself economic authority: ``qopts.export=true``
generates the entire requested table as one zipped CSV and reports both
``file.data_snapshot_time`` and ``datatable.last_refreshed_time`` once the file
is fresh. Sentinel accepts only a ``fresh`` file whose snapshot creation began at
or after the vendor's latest table refresh.

ACTIONS consumes that complete file directly. TICKERS uses it only as an
identity-key witness so paginated JSON preserves NULL-vs-empty metadata semantics.
SEP uses bounded exports for the current decision-history reconciliation; those
rows are normalized through the same production membrane before comparison.
"""
from __future__ import annotations

import csv
import io
import math
import os
import time
import zipfile
from datetime import datetime, timezone
from typing import Callable, Iterable, Mapping
from urllib.parse import urlparse

from sentinel.feed import action_snapshot, sharadar

EXPORT_MAX_POLLS = int(os.getenv("SHARADAR_EXPORT_MAX_POLLS", "20"))
EXPORT_POLL_SECONDS = float(os.getenv("SHARADAR_EXPORT_POLL_SECONDS", "30"))


class SharadarSnapshotExportError(sharadar.SharadarRequestError):
    """The provider could not prove a complete, current export snapshot."""


def validate_config() -> None:
    sharadar.validate_config()
    if isinstance(EXPORT_MAX_POLLS, bool) or not isinstance(EXPORT_MAX_POLLS, int) \
            or EXPORT_MAX_POLLS < 1:
        raise ValueError("SHARADAR_EXPORT_MAX_POLLS must be an integer >= 1")
    if not math.isfinite(EXPORT_POLL_SECONDS) or EXPORT_POLL_SECONDS < 0:
        raise ValueError("SHARADAR_EXPORT_POLL_SECONDS must be finite and >= 0")


def _aware_iso(value, *, field: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise SharadarSnapshotExportError(
            f"Sharadar export omitted required {field}")
    if text.endswith(" UTC"):
        text = text[:-4] + "+00:00"
    elif text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise SharadarSnapshotExportError(
            f"Sharadar export returned invalid {field}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _decode_export_status(
        payload) -> tuple[str, str | None, datetime | None, datetime | None]:
    if not isinstance(payload, dict):
        raise SharadarSnapshotExportError(
            "Sharadar export status root is not an object")
    root = payload.get("datatable_bulk_download")
    if not isinstance(root, dict):
        raise SharadarSnapshotExportError(
            "Sharadar export status lacks datatable_bulk_download")
    file_info = root.get("file")
    if not isinstance(file_info, dict):
        raise SharadarSnapshotExportError(
            "Sharadar export status lacks file evidence")
    status = str(file_info.get("status") or "").strip().lower()
    if status not in {"fresh", "creating", "regenerating"}:
        raise SharadarSnapshotExportError(
            f"Sharadar export returned unknown file status {status!r}")
    link = file_info.get("link")
    if link is not None:
        link = str(link).strip() or None
    if status != "fresh":
        return status, link, None, None
    table_info = root.get("datatable")
    if not isinstance(table_info, dict):
        raise SharadarSnapshotExportError(
            "Sharadar fresh export status lacks datatable evidence")
    snapshot = _aware_iso(
        file_info.get("data_snapshot_time"), field="data_snapshot_time")
    refreshed = _aware_iso(
        table_info.get("last_refreshed_time"), field="last_refreshed_time")
    return status, link, snapshot, refreshed


def _safe_download(client, link: str, *, http, sleep, now) -> bytes:
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
        except Exception as exc:  # noqa: BLE001
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


def _fetch_complete(
        table: str, *, params: Mapping[str, str] | None, required: set[str],
        http=None, sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] | None = None,
        poll_seconds: float | None = None,
        max_polls: int | None = None) -> tuple[object, dict]:
    validate_config()
    polls = EXPORT_MAX_POLLS if max_polls is None else int(max_polls)
    delay = EXPORT_POLL_SECONDS if poll_seconds is None else float(poll_seconds)
    if polls < 1 or not math.isfinite(delay) or delay < 0:
        raise ValueError("invalid Sharadar export polling configuration")
    if table not in {sharadar.ACTIONS, sharadar.TICKERS, sharadar.SEP}:
        raise ValueError("complete export authority is defined only for ACTIONS/TICKERS/SEP")
    if http is None:
        import httpx  # noqa: PLC0415
        http = httpx
    key = sharadar._api_key()
    url = f"{sharadar.NDL_BASE}/{table}.json"
    query: dict[str, object] = {
        "api_key": key,
        **sharadar._validated_params(params),
        "qopts.export": "true",
    }
    with http.Client(timeout=sharadar.FETCH_TIMEOUT_SECS) as client:
        for poll in range(1, polls + 1):
            response = sharadar._get_with_retry(
                client, url, query, http=http, sleep=sleep, now=now)
            try:
                payload = response.json()
            except Exception as exc:
                raise SharadarSnapshotExportError(
                    f"Sharadar {table} export status HTTP 200 body is not valid JSON"
                ) from exc
            status, link, snapshot, refreshed = _decode_export_status(payload)
            if status == "fresh":
                if link is None:
                    raise SharadarSnapshotExportError(
                        f"Sharadar fresh {table} export supplied no download link")
                assert snapshot is not None and refreshed is not None
                if snapshot < refreshed:
                    raise SharadarSnapshotExportError(
                        f"Sharadar {table} export claims fresh but its data snapshot "
                        "began before the table's last refresh")
                blob = _safe_download(
                    client, link, http=http, sleep=sleep, now=now)
                evidence = {
                    "authority": "nasdaq-data-link-table-export/v1",
                    "table": table,
                    "file_status": status,
                    "data_snapshot_time": snapshot.isoformat(),
                    "last_refreshed_time": refreshed.isoformat(),
                }
                if table == sharadar.ACTIONS:
                    try:
                        rows = action_snapshot.ActionSnapshot.from_zip_bytes(
                            blob, required_columns=required)
                    except action_snapshot.ActionSnapshotError as exc:
                        raise SharadarSnapshotExportError(str(exc)) from exc
                    evidence.update({
                        "source_rows": rows.source_rows,
                        "distinct_source_rows": len(rows),
                        "exact_repeat_rows": rows.exact_repeat_rows,
                    })
                    return rows, evidence
                rows = _csv_rows(blob, required=required)
                evidence["source_rows"] = len(rows)
                return rows, evidence
            if poll < polls:
                sleep(delay)
    raise SharadarSnapshotExportError(
        f"Sharadar {table} export did not become fresh after {polls} poll(s)")


def fetch_complete_actions(
        *, through: str, **kwargs
        ) -> tuple[action_snapshot.ActionSnapshot, dict]:
    return _fetch_complete(
        sharadar.ACTIONS,
        params={"date.gte": "1900-01-01", "date.lte": str(through)},
        required={"date", "action", "ticker", "name", "value",
                  "contraticker", "contraname"}, **kwargs)


def fetch_complete_sep(*, start: str, end: str, **kwargs) -> tuple[list[dict], dict]:
    """Complete bounded SEP file used for current decision-history proof."""
    return _fetch_complete(
        sharadar.SEP,
        params={"date.gte": str(start), "date.lte": str(end)},
        required={"ticker", "date", "open", "close", "closeunadj", "volume",
                  "lastupdated"}, **kwargs)


def fetch_complete_ticker_keys(**kwargs) -> tuple[set[tuple[str, str]], dict]:
    rows, evidence = _fetch_complete(
        sharadar.TICKERS, params=None,
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
        raise SharadarSnapshotExportError(
            "Sharadar TICKERS export contains no usable table=SEP identity keys")
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
    raise SharadarSnapshotExportError(
        "Sharadar paginated TICKERS key set disagrees with the vendor fresh "
        f"whole-table export: paged={len(paged):,}, export={len(exported):,}, "
        f"missing_from_pages={missing[:8]}, extra_in_pages={extra[:8]}. "
        "Refusing common-mode partial TICKERS/SEP authority.")


__all__ = [
    "EXPORT_MAX_POLLS", "EXPORT_POLL_SECONDS", "SharadarSnapshotExportError",
    "assert_complete_ticker_keys", "fetch_complete_actions",
    "fetch_complete_sep", "fetch_complete_ticker_keys", "validate_config",
]
