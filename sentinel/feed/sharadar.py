"""The Sharadar provider boundary used by Sentinel.

Production currently reads Sharadar through Nasdaq Data Link's Tables API.  The
provider contract is deliberately above that transport: a future Sharadar
Direct adapter can implement :class:`SharadarSource` without pretending that a
base-URL change makes two different protocols interchangeable.

The boundary is fail closed.  HTTP 200 is not success until the complete Tables
page envelope, schema, row widths and cursor semantics have been validated.
Transport-owned authentication/pagination parameters cannot be supplied by a
caller, and Retry-After is never shortened merely to fit Sentinel's local
blocking ceiling.
"""
from __future__ import annotations

import logging
import math
import os
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Callable, Iterator, Mapping, Optional, Protocol
from urllib.parse import urlparse

NDL_BASE = os.getenv(
    "NDL_BASE_URL", "https://data.nasdaq.com/api/v3/datatables/SHARADAR")
FETCH_TIMEOUT_SECS = float(os.getenv("SHARADAR_FETCH_TIMEOUT", "120"))
FETCH_MAX_RETRIES = int(os.getenv("SHARADAR_FETCH_RETRIES", "6"))
FETCH_BACKOFF_BASE = float(os.getenv("SHARADAR_FETCH_BACKOFF", "2.0"))
RATE_LIMIT_BACKOFF_CAP = float(os.getenv("SHARADAR_429_BACKOFF_CAP", "900"))
FETCH_MAX_PAGES = int(os.getenv("SHARADAR_FETCH_MAX_PAGES", "100000"))
ALLOW_INSECURE_BASE_URL = os.getenv(
    "SHARADAR_ALLOW_INSECURE_BASE_URL", "").strip().lower() in {
        "1", "true", "yes"}

RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
SEP = "SEP"
SFP = "SFP"
ACTIONS = "ACTIONS"
TICKERS = "TICKERS"

# Columns that establish the source domains Sentinel actually consumes.  A page
# may contain more, but silently losing any of these turns a malformed HTTP 200
# into plausible market/reference data.  Requiring the full consumed ACTIONS
# and TICKERS shapes is intentional: a missing nullable field is protocol loss,
# not the same thing as that field being present with a NULL value.
_REQUIRED_COLUMNS = {
    SEP: frozenset({
        "ticker", "date", "open", "close", "closeunadj", "volume",
        "lastupdated",
    }),
    SFP: frozenset({"ticker", "date", "close", "closeadj", "closeunadj"}),
    ACTIONS: frozenset({
        "date", "action", "ticker", "name", "value", "contraticker",
        "contraname",
    }),
    TICKERS: frozenset({
        "table", "permaticker", "ticker", "category", "relatedtickers",
        "firstpricedate", "lastpricedate", "sector", "isdelisted", "exchange",
    }),
}
_RESERVED_PARAMS = frozenset({"api_key", "qopts.cursor_id"})
_MAX_CURSOR_LENGTH = 4096


class MissingApiKey(RuntimeError):
    pass


class PaginationError(RuntimeError):
    """The vendor cursor stream cannot prove complete forward progress."""


class SharadarRequestError(RuntimeError):
    """A vendor failure whose rendering is guaranteed not to contain a key."""


class SharadarProtocolError(SharadarRequestError):
    """A nominally successful response violates the Tables protocol contract."""


class SharadarRetryDeferred(SharadarRequestError):
    """The server requested a wait longer than this synchronous process may block."""

    def __init__(self, delay: float, status: Optional[int] = None):
        self.delay = float(delay)
        self.status = status
        label = f"HTTP {status}" if status is not None else "vendor"
        super().__init__(
            f"Sharadar {label} requested a {self.delay:.0f}s Retry-After; "
            f"local blocking ceiling is {RATE_LIMIT_BACKOFF_CAP:.0f}s. "
            "Deferring instead of retrying earlier than the provider requested.")


class SharadarSource(Protocol):
    """Source-level contract; transport details do not escape this interface."""

    authority: str

    def fetch_table(self, table: str,
                    params: Mapping[str, str] | None = None, **kwargs
                    ) -> Iterator[dict]: ...


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


def validate_config() -> None:
    """Validate transport configuration before an ingest can become durable."""
    if not math.isfinite(FETCH_TIMEOUT_SECS) or FETCH_TIMEOUT_SECS <= 0:
        raise ValueError("SHARADAR_FETCH_TIMEOUT must be finite and > 0")
    if isinstance(FETCH_MAX_RETRIES, bool) or not isinstance(FETCH_MAX_RETRIES, int) \
            or FETCH_MAX_RETRIES < 1:
        raise ValueError("SHARADAR_FETCH_RETRIES must be an integer >= 1")
    if not math.isfinite(FETCH_BACKOFF_BASE) or FETCH_BACKOFF_BASE < 0:
        raise ValueError("SHARADAR_FETCH_BACKOFF must be finite and >= 0")
    if not math.isfinite(RATE_LIMIT_BACKOFF_CAP) or RATE_LIMIT_BACKOFF_CAP <= 0:
        raise ValueError("SHARADAR_429_BACKOFF_CAP must be finite and > 0")
    if isinstance(FETCH_MAX_PAGES, bool) or not isinstance(FETCH_MAX_PAGES, int) \
            or FETCH_MAX_PAGES < 1:
        raise ValueError("SHARADAR_FETCH_MAX_PAGES must be an integer >= 1")
    parsed = urlparse(str(NDL_BASE))
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("NDL_BASE_URL must be an absolute URL")
    if parsed.scheme.lower() != "https" and not ALLOW_INSECURE_BASE_URL:
        raise ValueError(
            "NDL_BASE_URL must use HTTPS; set SHARADAR_ALLOW_INSECURE_BASE_URL "
            "only in an explicit test/development environment")


def _retry_after_seconds(value: str, *, now: Callable[[], datetime]) -> float:
    """Parse RFC Retry-After delta-seconds or HTTP-date."""
    text = str(value).strip()
    if not text:
        raise ValueError("empty Retry-After")
    try:
        seconds = float(text)
    except ValueError:
        dt = parsedate_to_datetime(text)
        if dt is None:
            raise ValueError("invalid Retry-After date")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        current = now()
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        seconds = (dt - current).total_seconds()
    if not math.isfinite(seconds):
        raise ValueError("non-finite Retry-After")
    return max(0.0, seconds)


def retry_delay(attempt: int, status: Optional[int],
                retry_after: Optional[str], *,
                now: Callable[[], datetime] | None = None) -> float:
    """Seconds before retry ``attempt`` (0-based), or defer if too long.

    Retry-After is authoritative for 429 and 503.  When its requested wait is
    longer than the configured synchronous blocking ceiling we fail retryably;
    sleeping only to the ceiling would retry *before* the provider allowed it.
    """
    clock = now or (lambda: datetime.now(timezone.utc))
    backoff = FETCH_BACKOFF_BASE * (2 ** attempt)
    if status == 429:
        backoff = max(backoff, 60.0 * (attempt + 1))
    if status in {429, 503} and retry_after:
        try:
            requested = _retry_after_seconds(retry_after, now=clock)
        except (TypeError, ValueError, OverflowError):
            requested = None
        if requested is not None:
            if requested > RATE_LIMIT_BACKOFF_CAP:
                raise SharadarRetryDeferred(requested, status)
            return max(backoff, requested)
    if backoff > RATE_LIMIT_BACKOFF_CAP and status == 429:
        raise SharadarRetryDeferred(backoff, status)
    return backoff


def _api_key() -> str:
    key = os.getenv("SHARADAR_API_KEY", "").strip()
    if not key:
        raise MissingApiKey(
            "SHARADAR_API_KEY is unset. Sentinel will not start a seed it cannot "
            "complete: an unauthenticated fetch can be mistaken for an empty "
            "table, so the boundary refuses before any durable ingest state.")
    return key


def _validated_params(params: Mapping[str, str] | None) -> dict[str, str]:
    supplied = dict(params or {})
    illegal = sorted(k for k in supplied if str(k).lower() in _RESERVED_PARAMS)
    if illegal:
        raise ValueError(
            "Sharadar caller parameters may not override transport-owned "
            f"parameter(s): {', '.join(illegal)}")
    return supplied


def _decode_page(payload, *, table: str,
                 expected_schema: tuple[str, ...] | None
                 ) -> tuple[tuple[str, ...], list, Optional[str]]:
    if not isinstance(payload, dict):
        raise SharadarProtocolError(f"{table}: response root is not an object")
    if "datatable" not in payload or not isinstance(payload["datatable"], dict):
        raise SharadarProtocolError(f"{table}: missing/invalid datatable object")
    dt = payload["datatable"]
    if "columns" not in dt or not isinstance(dt["columns"], list):
        raise SharadarProtocolError(f"{table}: missing/invalid datatable.columns")
    names: list[str] = []
    for i, descriptor in enumerate(dt["columns"]):
        if not isinstance(descriptor, dict):
            raise SharadarProtocolError(
                f"{table}: column descriptor {i} is not an object")
        name = descriptor.get("name")
        if not isinstance(name, str) or not name.strip():
            raise SharadarProtocolError(
                f"{table}: column descriptor {i} has no non-empty name")
        name = name.strip()
        if name in names:
            raise SharadarProtocolError(f"{table}: duplicate column {name!r}")
        names.append(name)
    schema = tuple(names)
    if expected_schema is not None and schema != expected_schema:
        raise SharadarProtocolError(
            f"{table}: schema changed during pagination from "
            f"{expected_schema!r} to {schema!r}")
    missing = _REQUIRED_COLUMNS.get(table, frozenset()).difference(schema)
    if missing:
        raise SharadarProtocolError(
            f"{table}: response lacks required column(s): "
            f"{', '.join(sorted(missing))}")
    if "data" not in dt or not isinstance(dt["data"], list):
        raise SharadarProtocolError(f"{table}: missing/invalid datatable.data")
    width = len(schema)
    for i, row in enumerate(dt["data"]):
        if not isinstance(row, (list, tuple)) or len(row) != width:
            actual = len(row) if isinstance(row, (list, tuple)) else "non-sequence"
            raise SharadarProtocolError(
                f"{table}: row {i} width {actual} does not match schema width {width}")
    if "meta" not in payload or not isinstance(payload["meta"], dict):
        raise SharadarProtocolError(f"{table}: missing/invalid meta object")
    meta = payload["meta"]
    if "next_cursor_id" not in meta:
        raise SharadarProtocolError(f"{table}: meta.next_cursor_id is missing")
    raw_cursor = meta["next_cursor_id"]
    cursor: Optional[str]
    if raw_cursor is None:
        cursor = None
    elif isinstance(raw_cursor, str) and raw_cursor.strip():
        cursor = raw_cursor.strip()
        if len(cursor) > _MAX_CURSOR_LENGTH:
            raise SharadarProtocolError(
                f"{table}: next_cursor_id exceeds {_MAX_CURSOR_LENGTH} characters")
    else:
        raise SharadarProtocolError(
            f"{table}: next_cursor_id must be null or a non-empty string")
    if not dt["data"] and cursor is not None:
        raise SharadarProtocolError(
            f"{table}: empty page supplied a continuation cursor")
    return schema, dt["data"], cursor


def _fetch_ndl_table(table: str, params: Mapping[str, str] | None = None, *,
                     http=None, sleep=time.sleep,
                     now: Callable[[], datetime] | None = None) -> Iterator[dict]:
    validate_config()
    if table not in _REQUIRED_COLUMNS:
        raise ValueError(
            f"unsupported Sharadar table {table!r}; provider boundary permits "
            f"only {sorted(_REQUIRED_COLUMNS)}")
    supplied = _validated_params(params)
    key = _api_key()
    if http is None:
        import httpx                      # noqa: PLC0415 -- optional at import
        http = httpx
    url = f"{NDL_BASE}/{table}.json"
    cursor: Optional[str] = None
    seen_cursors: set[str] = set()
    pages = 0
    expected_schema: tuple[str, ...] | None = None

    with http.Client(timeout=FETCH_TIMEOUT_SECS) as client:
        while True:
            if pages >= FETCH_MAX_PAGES:
                raise PaginationError(
                    f"{table} pagination exceeded the bounded cap of "
                    f"{FETCH_MAX_PAGES:,} pages")
            q: dict[str, object] = {"api_key": key, **supplied}
            if cursor is not None:
                q["qopts.cursor_id"] = cursor
            resp = _get_with_retry(
                client, url, q, http=http, sleep=sleep, now=now)
            pages += 1
            try:
                payload = resp.json()
            except Exception as exc:
                raise SharadarProtocolError(
                    f"{table}: HTTP 200 body is not valid JSON ({type(exc).__name__})") \
                    from None
            schema, rows, next_cursor = _decode_page(
                payload, table=table, expected_schema=expected_schema)
            expected_schema = schema
            for row in rows:
                yield dict(zip(schema, row))
            if next_cursor is None:
                return
            if next_cursor in seen_cursors:
                raise PaginationError(
                    f"{table} pagination repeated cursor {next_cursor!r} after "
                    f"{pages:,} page(s); refusing an incomplete/infinite fetch")
            seen_cursors.add(next_cursor)
            cursor = next_cursor


def _get_with_retry(client, url: str, params: dict, *, http, sleep,
                    now: Callable[[], datetime] | None = None):
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
        except SharadarRetryDeferred:
            raise
        except Exception as exc:          # noqa: BLE001 -- classified below
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
            delay = retry_delay(
                attempt, status, retry_after,
                now=now or (lambda: datetime.now(timezone.utc)))
            print(f"[sentinel-feed] transient fetch failure "
                  f"({status or type(last_exc).__name__}) attempt "
                  f"{attempt + 1}/{FETCH_MAX_RETRIES} -- retrying in {delay:.0f}s",
                  flush=True)
            sleep(delay)
    assert last_exc is not None
    raise SharadarRequestError(
        f"Sharadar request failed after {FETCH_MAX_RETRIES} attempt(s) "
        f"({type(last_exc).__name__}) for {_safe_request_target(url, params)}") \
        from None


class _Transient(Exception):
    """A retryable HTTP status, raised so one backoff path handles every case."""


def _is_transport_error(exc: Exception, http) -> bool:
    for name in ("TimeoutException", "TransportError"):
        kind = getattr(http, name, None)
        if kind is not None and isinstance(exc, kind):
            return True
    return False


class NasdaqDataLinkSharadarSource:
    """Current production adapter for Nasdaq Data Link's Sharadar Tables API."""

    authority = "nasdaq-data-link-tables/SHARADAR"

    def fetch_table(self, table: str,
                    params: Mapping[str, str] | None = None, **kwargs
                    ) -> Iterator[dict]:
        return _fetch_ndl_table(table, params, **kwargs)


class DirectSharadarSource:
    """Reserved boundary for Sharadar's distinct direct API.

    This class intentionally has no pseudo-migration-by-base-URL.  Implementing
    the direct provider requires an explicit protocol adapter and parity tests.
    """

    authority = "sharadar-direct"

    def fetch_table(self, table: str,
                    params: Mapping[str, str] | None = None, **kwargs
                    ) -> Iterator[dict]:
        raise NotImplementedError(
            "Sharadar Direct is a different provider protocol and has no "
            "certified Sentinel adapter yet")


DEFAULT_SOURCE: SharadarSource = NasdaqDataLinkSharadarSource()


def fetch_table(table: str, params: Mapping[str, str] | None = None, *,
                http=None, sleep=time.sleep,
                now: Callable[[], datetime] | None = None) -> Iterator[dict]:
    """Compatibility entry point, routed through the explicit source adapter."""
    return DEFAULT_SOURCE.fetch_table(
        table, params, http=http, sleep=sleep, now=now)


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
    """Split a range into calendar years for bounded, restartable seed work."""
    date_from, date_to = validate_date_range(date_from, date_to)
    y0, y1 = int(date_from[:4]), int(date_to[:4])
    out = []
    for y in range(y0, y1 + 1):
        lo = max(f"{y}-01-01", date_from)
        hi = min(f"{y}-12-31", date_to)
        if lo <= hi:
            out.append((lo, hi))
    return out
