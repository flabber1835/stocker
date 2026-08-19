"""Financial-grade Sharadar reference-table acquisition.

Nasdaq Data Link's ordinary Tables API is cursor-paginated and exposes no
snapshot token in each page.  Two identical traversals prove repeatability, not
negative-space completeness: the same prematurely terminal response can repeat.

For the two tables where *absence itself* changes Sentinel economics, use Data
Link's documented Table Exporter instead:

* TICKERS omission can erase identity/eligibility authority;
* ACTIONS omission can erase a split, dividend, or terminal event.

The exporter produces one zipped CSV together with ``file.status``,
``file.data_snapshot_time`` and ``datatable.last_refreshed_time``.  Sentinel
accepts only a ``fresh`` file whose snapshot was initiated no earlier than the
latest table refresh.  Creating/regenerating exports are waited for only within a
bounded local ceiling; an old link is never treated as current authority.

SEP remains on the strict paginated transport because daily completeness is
independently witnessed by the stable TICKERS listing population.  SFP is a
single named SPY tail and remains on the strict paginated transport as well.
"""
from __future__ import annotations

import csv
import io
import math
import os
import time
import zipfile
from datetime import datetime, timezone
from typing import Callable, Iterator, Mapping, Optional

from sentinel.feed import sharadar

EXPORT_POLL_SECONDS = float(os.getenv("SHARADAR_EXPORT_POLL_SECONDS", "5"))
EXPORT_MAX_WAIT_SECONDS = float(os.getenv("SHARADAR_EXPORT_MAX_WAIT_SECONDS", "300"))

_SNAPSHOT_TABLES = frozenset({sharadar.TICKERS, sharadar.ACTIONS})


class SharadarExportUnavailable(sharadar.SharadarRequestError):
    """A current immutable reference snapshot could not be obtained in bounds."""


def validate_config() -> None:
    sharadar.validate_config()
    if not math.isfinite(EXPORT_POLL_SECONDS) or EXPORT_POLL_SECONDS <= 0:
        raise ValueError("SHARADAR_EXPORT_POLL_SECONDS must be finite and > 0")
    if not math.isfinite(EXPORT_MAX_WAIT_SECONDS) or EXPORT_MAX_WAIT_SECONDS <= 0:
        raise ValueError("SHARADAR_EXPORT_MAX_WAIT_SECONDS must be finite and > 0")
    if EXPORT_POLL_SECONDS > EXPORT_MAX_WAIT_SECONDS:
        raise ValueError(
            "SHARADAR_EXPORT_POLL_SECONDS may not exceed the export wait ceiling")


def _vendor_time(value, *, field: str) -> datetime:
    if value is None:
        raise sharadar.SharadarProtocolError(
            f"Sharadar export metadata is missing {field}")
    text = str(value).strip()
    if not text:
        raise sharadar.SharadarProtocolError(
            f"Sharadar export metadata has empty {field}")
    if text.endswith(" UTC"):
        text = text[:-4] + "+00:00"
    elif text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise sharadar.SharadarProtocolError(
            f"Sharadar export metadata has invalid {field}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _decode_export(payload, *, table: str):
    if not isinstance(payload, dict):
        raise sharadar.SharadarProtocolError(
            f"{table} export response root is not an object")
    root = payload.get("datatable_bulk_download")
    if not isinstance(root, dict):
        raise sharadar.SharadarProtocolError(
            f"{table} export response lacks datatable_bulk_download")
    file_meta = root.get("file")
    table_meta = root.get("datatable")
    if not isinstance(file_meta, dict) or not isinstance(table_meta, dict):
        raise sharadar.SharadarProtocolError(
            f"{table} export response lacks file/datatable metadata")
    status = str(file_meta.get("status") or "").strip().lower()
    if status not in {"fresh", "creating", "regenerating"}:
        raise sharadar.SharadarProtocolError(
            f"{table} export returned unknown file status {status!r}")
    if status != "fresh":
        return status, None

    link = file_meta.get("link")
    if not isinstance(link, str) or not link.strip().startswith("https://"):
        raise sharadar.SharadarProtocolError(
            f"{table} fresh export has no HTTPS file link")
    snapshot = _vendor_time(
        file_meta.get("data_snapshot_time"), field="file.data_snapshot_time")
    refreshed = _vendor_time(
        table_meta.get("last_refreshed_time"),
        field="datatable.last_refreshed_time")
    if snapshot < refreshed:
        raise sharadar.SharadarProtocolError(
            f"{table} export claims fresh but its snapshot predates the table refresh")
    return status, link.strip()


def _secret_get_with_retry(client, url: str, *, http, sleep,
                           now: Callable[[], datetime] | None = None):
    """Download a signed/key-bearing export URL without ever rendering the URL."""
    last_exc: Exception | None = None
    for attempt in range(sharadar.FETCH_MAX_RETRIES):
        status: Optional[int] = None
        retry_after: Optional[str] = None
        try:
            with sharadar._quiet_http_client_diagnostics():
                response = client.get(url)
                if response.status_code in sharadar.RETRYABLE_STATUS:
                    status = response.status_code
                    retry_after = response.headers.get("Retry-After")
                    raise _TransientExport(f"retryable HTTP {status}")
                response.raise_for_status()
            return response
        except _TransientExport as exc:
            last_exc = exc
        except sharadar.SharadarRetryDeferred:
            raise
        except Exception as exc:                         # noqa: BLE001
            if sharadar._is_transport_error(exc, http):
                last_exc = exc
            else:
                response = getattr(exc, "response", None)
                code = getattr(response, "status_code", None)
                label = f"HTTP {code}" if code is not None else type(exc).__name__
                raise sharadar.SharadarRequestError(
                    f"Sharadar export-file download failed ({label}); secret URL redacted"
                ) from None
        if attempt < sharadar.FETCH_MAX_RETRIES - 1:
            delay = sharadar.retry_delay(
                attempt, status, retry_after,
                now=now or (lambda: datetime.now(timezone.utc)))
            sleep(delay)
    assert last_exc is not None
    raise sharadar.SharadarRequestError(
        f"Sharadar export-file download failed after "
        f"{sharadar.FETCH_MAX_RETRIES} attempt(s) "
        f"({type(last_exc).__name__}); secret URL redacted") from None


class _TransientExport(Exception):
    pass


def _rows_from_zip(table: str, payload: bytes) -> list[dict]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except (zipfile.BadZipFile, ValueError) as exc:
        raise sharadar.SharadarProtocolError(
            f"{table} fresh export is not a valid ZIP archive") from exc
    with archive:
        files = [name for name in archive.namelist()
                 if not name.endswith("/") and name.lower().endswith(".csv")]
        if len(files) != 1:
            raise sharadar.SharadarProtocolError(
                f"{table} export must contain exactly one CSV, found {len(files)}")
        with archive.open(files[0], "r") as raw:
            text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
            reader = csv.DictReader(text)
            fields = tuple(reader.fieldnames or ())
            if not fields or any(not str(name).strip() for name in fields):
                raise sharadar.SharadarProtocolError(
                    f"{table} export has missing/empty CSV header")
            if len(set(fields)) != len(fields):
                raise sharadar.SharadarProtocolError(
                    f"{table} export has duplicate CSV columns")
            missing = sharadar._REQUIRED_COLUMNS[table].difference(fields)
            if missing:
                raise sharadar.SharadarProtocolError(
                    f"{table} export lacks required column(s): "
                    f"{', '.join(sorted(missing))}")
            rows: list[dict] = []
            for index, row in enumerate(reader):
                if None in row:
                    raise sharadar.SharadarProtocolError(
                        f"{table} export row {index} is wider than its CSV schema")
                rows.append(dict(row))
            return rows


def fetch_export(table: str, params: Mapping[str, str] | None = None, *,
                 http=None, sleep=time.sleep,
                 monotonic: Callable[[], float] = time.monotonic,
                 now: Callable[[], datetime] | None = None) -> Iterator[dict]:
    """Return one current full-file snapshot for TICKERS/ACTIONS.

    ``fresh`` is a vendor assertion about the generated file, not an inference
    from a row count.  We additionally require the file snapshot time to be at
    or after the table's last refresh before any row is exposed to callers.
    """
    validate_config()
    if table not in _SNAPSHOT_TABLES:
        raise ValueError(
            f"immutable export authority is defined only for {sorted(_SNAPSHOT_TABLES)}")
    supplied = sharadar._validated_params(params)
    key = sharadar._api_key()
    if http is None:
        import httpx                                      # noqa: PLC0415
        http = httpx
    url = f"{sharadar.NDL_BASE}/{table}.json"
    query: dict[str, object] = {
        "api_key": key,
        **supplied,
        "qopts.export": "true",
    }
    started = monotonic()
    with http.Client(timeout=sharadar.FETCH_TIMEOUT_SECS) as client:
        while True:
            response = sharadar._get_with_retry(
                client, url, query, http=http, sleep=sleep, now=now)
            try:
                payload = response.json()
            except Exception as exc:
                raise sharadar.SharadarProtocolError(
                    f"{table} export metadata is not valid JSON "
                    f"({type(exc).__name__})") from None
            status, link = _decode_export(payload, table=table)
            if status == "fresh":
                assert link is not None
                break
            elapsed = monotonic() - started
            if elapsed >= EXPORT_MAX_WAIT_SECONDS:
                raise SharadarExportUnavailable(
                    f"{table} immutable export stayed {status} for "
                    f"{elapsed:.0f}s; refusing to use the older/incomplete snapshot")
            delay = min(EXPORT_POLL_SECONDS,
                        max(0.0, EXPORT_MAX_WAIT_SECONDS - elapsed))
            sleep(delay)

        file_response = _secret_get_with_retry(
            client, link, http=http, sleep=sleep, now=now)
        rows = _rows_from_zip(table, file_response.content)
    return iter(rows)


def fetch_table(table: str, params: Mapping[str, str] | None = None, **kwargs):
    """Authoritative production source: immutable reference tables, strict pages otherwise."""
    if table in _SNAPSHOT_TABLES:
        return fetch_export(table, params, **kwargs)
    return sharadar.fetch_table(table, params, **kwargs)


__all__ = [
    "EXPORT_MAX_WAIT_SECONDS", "EXPORT_POLL_SECONDS", "SharadarExportUnavailable",
    "fetch_export", "fetch_table", "validate_config",
]
