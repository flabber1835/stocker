"""Strict Nasdaq Data Link transport for the Sharadar tables Sentinel consumes.

The transport owns authentication and cursor state. Business callers own table
filters such as ``ticker``, ``date.gte`` and ``lastupdated.gte``. A successful
HTTP status is not source success: every datatable page is schema-validated
before a row is yielded, and a schema change anywhere in one traversal refuses
the whole fetch.

Retrying repeats the same idempotent GET. 429 and 503 ``Retry-After`` values are
honoured in both delta-seconds and HTTP-date forms. If the provider asks us to
block longer than Sentinel's configured ceiling, we defer/fail this run instead
of intentionally retrying before the provider told us to.
"""
from __future__ import annotations

import logging
import math
import os
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Iterator, Mapping, Optional
from urllib.parse import urlparse

NDL_BASE = os.getenv(
    "NDL_BASE_URL", "https://data.nasdaq.com/api/v3/datatables/SHARADAR")
FETCH_TIMEOUT_SECS = float(os.getenv("SHARADAR_FETCH_TIMEOUT", "30"))
FETCH_MAX_RETRIES = int(os.getenv("SHARADAR_FETCH_RETRIES", "6"))
FETCH_BACKOFF_BASE = float(os.getenv("SHARADAR_FETCH_BACKOFF", "2.0"))
RATE_LIMIT_BACKOFF_CAP = float(os.getenv("SHARADAR_429_BACKOFF_CAP", "900"))
FETCH_MAX_PAGES = int(os.getenv("SHARADAR_FETCH_MAX_PAGES", "100000"))
ALLOW_INSECURE_BASE_URL = os.getenv(
    "SHARADAR_ALLOW_INSECURE_BASE_URL", "").lower() in ("1", "true", "yes")
MAX_CURSOR_LENGTH = 2048

RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
TRANSPORT_OWNED_PARAMS = frozenset({"api_key", "qopts.cursor_id"})

SEP = "SEP"
SFP = "SFP"
ACTIONS = "ACTIONS"
TICKERS = "TICKERS"

# These are consumer requirements, not an attempt to freeze the provider's full
# schema. Extra columns are accepted; absence of a field we use is not.
REQUIRED_COLUMNS = {
    SEP: frozenset({"ticker", "date", "open", "close", "closeunadj",
                    "closeadj", "volume", "lastupdated"}),
    SFP: frozenset({"ticker", "date", "open", "close", "closeunadj",
                    "closeadj", "volume"}),
    ACTIONS: frozenset({"date", "action", "ticker", "name", "value",
                        "contraticker", "contraname"}),
    TICKERS: frozenset({"ticker", "permaticker", "category", "relatedtickers",
                        "firstpricedate", "lastpricedate", "exchange",
                        "lastupdated"}),
}


class MissingApiKey(RuntimeError):
    pass


class PaginationError(RuntimeError):
    """The vendor cursor stream cannot prove complete forward progress."""


class SharadarRequestError(RuntimeError):
    """A vendor failure whose rendering is guaranteed not to contain a key."""


class SharadarProtocolError(RuntimeError):
    """HTTP succeeded but the datatable response is not trustworthy."""


class SharadarTransportConfigError(RuntimeError):
    """Transport settings are unsafe before an HTTP request is attempted."""


class SharadarRetryDeferred(RuntimeError):
    """Provider-directed retry delay exceeds this process' blocking budget."""


@contextmanager
def _quiet_http_client_diagnostics():
    """Suppress URL-bearing httpx/httpcore records around an authenticated GET."""
    manager = logging.Logger.manager.loggerDict
    names = {"httpx", "httpcore"}
    names.update(str(name) for name in manager
                 if str(name).startswith(("httpx.", "httpcore.")))
    saved = {}
    for name in names:
        logger = logging.getLogger(name)
        saved[name] = (logger.level, logger.disabled)
        logger.setLevel(logging.CRITICAL + 1)
        logger.disabled = True
    try:
        yield
    finally:
        for name, (level, disabled) in saved.items():
            logger = logging.getLogger(name)
            logger.setLevel(level)
            logger.disabled = disabled


def _safe_request_target(url: str, params: Mapping[str, object]) -> str:
    visible = [f"{key}={value}" for key, value in sorted(params.items())
               if str(key).lower() != "api_key"]
    return str(url) + (("?" + "&".join(visible)) if visible else "")


def validate_transport_config() -> None:
    """Refuse invalid environment/config before opening an HTTP client."""
    numeric = (
        ("SHARADAR_FETCH_TIMEOUT", FETCH_TIMEOUT_SECS, False),
        ("SHARADAR_FETCH_BACKOFF", FETCH_BACKOFF_BASE, True),
        ("SHARADAR_429_BACKOFF_CAP", RATE_LIMIT_BACKOFF_CAP, False),
    )
    for name, value, zero_ok in numeric:
        if not math.isfinite(value) or value < 0 or (not zero_ok and value <= 0):
            raise SharadarTransportConfigError(
                f"{name} must be finite and {'>= 0' if zero_ok else '> 0'}")
    if not isinstance(FETCH_MAX_RETRIES, int) or FETCH_MAX_RETRIES < 1:
        raise SharadarTransportConfigError(
            "SHARADAR_FETCH_RETRIES must be an integer >= 1")
    if not isinstance(FETCH_MAX_PAGES, int) or FETCH_MAX_PAGES < 1:
        raise SharadarTransportConfigError(
            "SHARADAR_FETCH_MAX_PAGES must be an integer >= 1")
    parsed = urlparse(str(NDL_BASE))
    if not parsed.scheme or not parsed.netloc:
        raise SharadarTransportConfigError(
            "NDL_BASE_URL must be an absolute URL")
    if parsed.scheme.lower() != "https" and not ALLOW_INSECURE_BASE_URL:
        raise SharadarTransportConfigError(
            "NDL_BASE_URL must use HTTPS; set SHARADAR_ALLOW_INSECURE_BASE_URL "
            "only for an explicit test/development transport")


def _validate_business_params(params: Mapping[str, object] | None) -> None:
    for key in (params or {}):
        normalized = str(key).strip().lower()
        if (normalized in TRANSPORT_OWNED_PARAMS
                or normalized.startswith("qopts.cursor")):
            raise SharadarTransportConfigError(
                f"caller parameter {key!r} is transport-owned")


def parse_retry_after(value: Optional[str], *, now: datetime | None = None
                      ) -> Optional[float]:
    """RFC Retry-After delta-seconds or HTTP-date -> non-negative seconds."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        seconds = float(text)
        return max(0.0, seconds) if math.isfinite(seconds) else None
    except ValueError:
        pass
    try:
        target = parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        return None
    if target.tzinfo is None:
        target = target.replace(tzinfo=timezone.utc)
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return max(0.0, (target - reference).total_seconds())


def retry_delay(attempt: int, status: Optional[int], retry_after: Optional[str],
                *, now: datetime | None = None) -> float:
    """Seconds before retry `attempt` (0-based), excluding ceiling refusal."""
    provider = (parse_retry_after(retry_after, now=now)
                if status in (429, 503) else None)
    if status == 429:
        local = min(60.0 * (attempt + 1), RATE_LIMIT_BACKOFF_CAP)
    else:
        local = FETCH_BACKOFF_BASE * (2 ** attempt)
    return max(local, provider) if provider is not None else local


def _api_key() -> str:
    key = os.getenv("SHARADAR_API_KEY", "").strip()
    if not key:
        raise MissingApiKey(
            "SHARADAR_API_KEY is unset. Sentinel will not start a fetch it "
            "cannot authenticate; an empty/partial source must never resemble "
            "a quiet market.")
    return key


def _decode_page(resp, table: str, page: int, *,
                 expected_schema: tuple[str, ...] | None = None
                 ) -> tuple[tuple[str, ...], list, Optional[str]]:
    """Validate one successful datatable response before yielding any row."""
    try:
        payload = resp.json()
    except Exception as exc:  # noqa: BLE001 - provider decoder types vary
        raise SharadarProtocolError(
            f"{table} page {page} returned invalid JSON ({type(exc).__name__})") from None
    if not isinstance(payload, Mapping):
        raise SharadarProtocolError(
            f"{table} page {page} response root is not an object")

    dt = payload.get("datatable")
    if not isinstance(dt, Mapping):
        raise SharadarProtocolError(
            f"{table} page {page} has no valid datatable object")
    raw_columns = dt.get("columns")
    if not isinstance(raw_columns, list) or not raw_columns:
        raise SharadarProtocolError(
            f"{table} page {page} has no valid datatable.columns schema")
    if "data" not in dt or not isinstance(dt.get("data"), list):
        raise SharadarProtocolError(
            f"{table} page {page} has no valid datatable.data array")
    raw_rows = dt["data"]

    cols: list[str] = []
    for index, column in enumerate(raw_columns):
        if not isinstance(column, Mapping):
            raise SharadarProtocolError(
                f"{table} page {page} column {index} is not an object")
        name = column.get("name")
        if not isinstance(name, str) or not name.strip():
            raise SharadarProtocolError(
                f"{table} page {page} column {index} has no valid name")
        if name in cols:
            raise SharadarProtocolError(
                f"{table} page {page} repeats column {name!r}")
        cols.append(name)
    schema = tuple(cols)
    if expected_schema is not None and schema != expected_schema:
        raise SharadarProtocolError(
            f"{table} page {page} schema changed during pagination")

    required = REQUIRED_COLUMNS.get(str(table).upper())
    if required is None:
        raise SharadarProtocolError(f"unsupported Sharadar table {table!r}")
    missing = sorted(required.difference(schema))
    if missing:
        raise SharadarProtocolError(
            f"{table} page {page} is missing required column(s): " + ", ".join(missing))

    for index, row in enumerate(raw_rows):
        if not isinstance(row, (list, tuple)):
            raise SharadarProtocolError(
                f"{table} page {page} row {index} is not an array")
        if len(row) != len(schema):
            raise SharadarProtocolError(
                f"{table} page {page} row {index} has {len(row)} values for "
                f"{len(schema)} columns")

    if "meta" not in payload or not isinstance(payload.get("meta"), Mapping):
        raise SharadarProtocolError(
            f"{table} page {page} has no valid meta object")
    meta = payload["meta"]
    if "next_cursor_id" not in meta:
        raise SharadarProtocolError(
            f"{table} page {page} meta has no next_cursor_id field")
    next_cursor = meta["next_cursor_id"]
    if next_cursor in (None, ""):
        return schema, raw_rows, None
    if not isinstance(next_cursor, (str, int)) or isinstance(next_cursor, bool):
        raise SharadarProtocolError(
            f"{table} page {page} next_cursor_id has invalid type "
            f"{type(next_cursor).__name__}")
    next_cursor = str(next_cursor)
    if not next_cursor or len(next_cursor) > MAX_CURSOR_LENGTH:
        raise SharadarProtocolError(
            f"{table} page {page} next_cursor_id has invalid length")
    return schema, raw_rows, next_cursor


def fetch_table(table: str, params: Mapping[str, str] | None = None, *,
                http=None, sleep=time.sleep) -> Iterator[dict]:
    """Yield validated rows for one supported table, following vendor cursors."""
    validate_transport_config()
    _validate_business_params(params)
    key = _api_key()
    table = str(table).upper()
    if table not in REQUIRED_COLUMNS:
        raise SharadarProtocolError(f"unsupported Sharadar table {table!r}")
    if http is None:
        import httpx                      # noqa: PLC0415 — optional at import
        http = httpx
    url = f"{NDL_BASE.rstrip('/')}/{table}.json"
    cursor: Optional[str] = None
    seen_cursors: set[str] = set()
    pages = 0
    schema: tuple[str, ...] | None = None

    with http.Client(timeout=FETCH_TIMEOUT_SECS) as client:
        while True:
            if pages >= FETCH_MAX_PAGES:
                raise PaginationError(
                    f"{table} pagination exceeded the bounded cap of "
                    f"{FETCH_MAX_PAGES:,} pages")
            q = {**(params or {}), "api_key": key}
            if cursor:
                q["qopts.cursor_id"] = cursor
            resp = _get_with_retry(client, url, q, http=http, sleep=sleep)
            pages += 1
            schema, rows, next_cursor = _decode_page(
                resp, table, pages, expected_schema=schema)
            for row in rows:
                yield dict(zip(schema, row))
            if not next_cursor:
                return
            if next_cursor in seen_cursors:
                raise PaginationError(
                    f"{table} pagination repeated cursor {next_cursor!r} after "
                    f"{pages:,} page(s); refusing an incomplete/infinite fetch")
            seen_cursors.add(next_cursor)
            cursor = next_cursor


def _get_with_retry(client, url: str, params: dict, *, http, sleep):
    last_exc: Exception | None = None
    for attempt in range(FETCH_MAX_RETRIES):
        status: Optional[int] = None
        retry_after: Optional[str] = None
        try:
            with _quiet_http_client_diagnostics():
                resp = client.get(url, params=params)
                if resp.status_code in RETRYABLE_STATUS:
                    status = resp.status_code
                    retry_after = resp.headers.get("Retry-After")
                    raise _Transient(f"retryable HTTP {status}")
                resp.raise_for_status()
            return resp
        except _Transient as exc:
            last_exc = exc
        except Exception as exc:          # noqa: BLE001 — classified below
            if _is_transport_error(exc, http):
                last_exc = exc
            else:
                response = getattr(exc, "response", None)
                code = getattr(response, "status_code", None)
                label = f"HTTP {code}" if code is not None else type(exc).__name__
                raise SharadarRequestError(
                    f"Sharadar request failed ({label}) for "
                    f"{_safe_request_target(url, params)}") from None
        if attempt < FETCH_MAX_RETRIES - 1:
            provider_delay = (parse_retry_after(retry_after)
                              if status in (429, 503) else None)
            if (provider_delay is not None
                    and provider_delay > RATE_LIMIT_BACKOFF_CAP):
                raise SharadarRetryDeferred(
                    f"Sharadar HTTP {status} requested Retry-After "
                    f"{provider_delay:.0f}s, beyond this run's "
                    f"{RATE_LIMIT_BACKOFF_CAP:.0f}s blocking ceiling; refusing "
                    "to retry earlier than the provider requested") from None
            delay = retry_delay(attempt, status, retry_after)
            print(f"[sentinel-feed] transient fetch failure "
                  f"({status or type(last_exc).__name__}) attempt "
                  f"{attempt + 1}/{FETCH_MAX_RETRIES} — retrying in {delay:.0f}s",
                  flush=True)
            sleep(delay)
    assert last_exc is not None
    raise SharadarRequestError(
        f"Sharadar request failed after {FETCH_MAX_RETRIES} attempt(s) "
        f"({type(last_exc).__name__}) for {_safe_request_target(url, params)}") from None


class _Transient(Exception):
    """A retryable HTTP status, raised so one backoff path handles every case."""


def _is_transport_error(exc: Exception, http) -> bool:
    for name in ("TimeoutException", "TransportError"):
        kind = getattr(http, name, None)
        if kind is not None and isinstance(exc, kind):
            return True
    return False


def date_params(date_from: str, date_to: str) -> dict:
    validate_date_range(date_from, date_to)
    return {"date.gte": date_from, "date.lte": date_to}


def validate_date_range(date_from: str, date_to: str) -> tuple[str, str]:
    """Validate an inclusive ISO range before any durable run or vendor read."""
    lo, hi = date.fromisoformat(str(date_from)), date.fromisoformat(str(date_to))
    if lo > hi:
        raise ValueError(f"reversed date range: {lo} is after {hi}")
    return lo.isoformat(), hi.isoformat()


def year_chunks(date_from: str, date_to: str) -> list[tuple[str, str]]:
    """Split a range into calendar years for bounded progress/restart work."""
    date_from, date_to = validate_date_range(date_from, date_to)
    y0, y1 = int(date_from[:4]), int(date_to[:4])
    out = []
    for y in range(y0, y1 + 1):
        lo = max(f"{y}-01-01", date_from)
        hi = min(f"{y}-12-31", date_to)
        if lo <= hi:
            out.append((lo, hi))
    return out
