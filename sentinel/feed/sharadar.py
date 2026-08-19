"""The Sharadar (Nasdaq Data Link) client.

```text
GET https://data.nasdaq.com/api/v3/datatables/SHARADAR/{TABLE}.json
    ?api_key=...&date.gte=YYYY-MM-DD&date.lte=YYYY-MM-DD&qopts.cursor_id=...
```

Cursor-paginated: `datatable.data` rows, `datatable.columns` schema,
`meta.next_cursor_id` (None when done). Rows are yielded as column-name -> value
dicts.

RETRY SEMANTICS ARE CARRIED FORWARD, NOT RE-DERIVED. A full seed is thousands of
cursor pages over hours, and without retry a single transient blip failed the
entire run — the "stuck at 25M then frozen" symptom bt-data was built to cure.
Two behaviours matter and both are non-obvious:

  * a retried GET repeats the SAME cursor page, which is safe because the GET is
    idempotent — retrying a mutation would not be;
  * **429 is not an ordinary transient.** Nasdaq throttles heavy usage and a
    throttle can last many minutes, far longer than a 2..32s exponential backoff,
    which gave up in about a minute and killed the load. 429 therefore honours
    `Retry-After` and otherwise waits 60s x attempt, tolerating ~15 minutes of
    throttling.

Non-retryable 4xx (auth, bad request) still fail fast: waiting fifteen minutes to
re-learn that an API key is wrong helps nobody. A syntactically successful HTTP
response with a malformed datatable envelope also fails immediately. Treating a
bad provider response as an empty table is more dangerous than an outage because
it can publish a plausible partial corpus.

Sentinel may not import a retired Stocker service, so `retry_delay` is a
re-implementation — and `tests/sentinel/test_feed_sharadar.py` pins it against
bt-data's original, because these constants encode an outage rather than a
preference.

Synchronous. A batch loader has no event loop to share and no concurrency to
exploit; async would buy nothing and cost the ability to run this from a script.
"""
from __future__ import annotations

import os
import time
import logging
from contextlib import contextmanager
from datetime import date
from typing import Callable, Iterator, Mapping, Optional

NDL_BASE = os.getenv("NDL_BASE_URL",
                     "https://data.nasdaq.com/api/v3/datatables/SHARADAR")

# Bound an individual network operation. The page retry loop provides outage
# tolerance; a two-minute socket timeout only makes each failed attempt hang.
FETCH_TIMEOUT_SECS = float(os.getenv("SHARADAR_FETCH_TIMEOUT", "30"))
FETCH_MAX_RETRIES = int(os.getenv("SHARADAR_FETCH_RETRIES", "6"))
FETCH_BACKOFF_BASE = float(os.getenv("SHARADAR_FETCH_BACKOFF", "2.0"))
RATE_LIMIT_BACKOFF_CAP = float(os.getenv("SHARADAR_429_BACKOFF_CAP", "900"))
FETCH_MAX_PAGES = int(os.getenv("SHARADAR_FETCH_MAX_PAGES", "100000"))

RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

#: The tables Sentinel reads. SF1 is absent deliberately: Wealth Core consumes no
#: fundamentals, so fetching them would cost hours of seed time for data nothing
#: reads.
SEP = "SEP"
SFP = "SFP"
ACTIONS = "ACTIONS"
TICKERS = "TICKERS"


class MissingApiKey(RuntimeError):
    pass


class PaginationError(RuntimeError):
    """The vendor cursor stream cannot prove complete forward progress."""


class SharadarRequestError(RuntimeError):
    """A vendor failure whose rendering is guaranteed not to contain a key."""


class SharadarProtocolError(RuntimeError):
    """HTTP succeeded but the Sharadar datatable response is not trustworthy."""


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


def retry_delay(attempt: int, status: Optional[int],
                retry_after: Optional[str]) -> float:
    """Seconds before retry `attempt` (0-based). Pure, so it is testable."""
    if status == 429:
        delay = 60.0 * (attempt + 1)
        if retry_after:
            try:
                delay = max(delay, float(retry_after))
            except ValueError:
                pass                      # HTTP-date form — keep the default
        return min(delay, RATE_LIMIT_BACKOFF_CAP)
    return FETCH_BACKOFF_BASE * (2 ** attempt)


def _api_key() -> str:
    key = os.getenv("SHARADAR_API_KEY", "").strip()
    if not key:
        raise MissingApiKey(
            "SHARADAR_API_KEY is unset. Sentinel will not start a seed it cannot "
            "complete: an unauthenticated fetch returns an EMPTY table, and an "
            "empty table is indistinguishable from a quiet market unless someone "
            "notices the row count. Refusing up front is the only reading that "
            "cannot be mistaken for success.")
    return key


def _decode_page(resp, table: str, page: int) -> tuple[list[str], list, Optional[str]]:
    """Validate one successful Sharadar datatable response before yielding it.

    This is deliberately outside `_get_with_retry`: JSON/schema corruption is a
    protocol failure, not a transport failure, and repeating the same page can
    turn a deterministic provider defect into a long outage without making the
    bytes any more trustworthy.
    """
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
    raw_rows = dt.get("data")
    if not isinstance(raw_columns, list) or not raw_columns:
        raise SharadarProtocolError(
            f"{table} page {page} has no valid datatable.columns schema")
    if not isinstance(raw_rows, list):
        raise SharadarProtocolError(
            f"{table} page {page} has no valid datatable.data array")

    cols: list[str] = []
    for index, column in enumerate(raw_columns):
        if not isinstance(column, Mapping):
            raise SharadarProtocolError(
                f"{table} page {page} column {index} is not an object")
        name = column.get("name")
        if not isinstance(name, str) or not name:
            raise SharadarProtocolError(
                f"{table} page {page} column {index} has no valid name")
        if name in cols:
            raise SharadarProtocolError(
                f"{table} page {page} repeats column {name!r}")
        cols.append(name)

    for index, row in enumerate(raw_rows):
        if not isinstance(row, (list, tuple)):
            raise SharadarProtocolError(
                f"{table} page {page} row {index} is not an array")
        if len(row) != len(cols):
            raise SharadarProtocolError(
                f"{table} page {page} row {index} has {len(row)} values for "
                f"{len(cols)} columns")

    meta = payload.get("meta")
    if meta is None:
        next_cursor = None
    elif not isinstance(meta, Mapping):
        raise SharadarProtocolError(
            f"{table} page {page} meta is not an object")
    else:
        next_cursor = meta.get("next_cursor_id")
        if next_cursor is not None and not isinstance(next_cursor, (str, int)):
            raise SharadarProtocolError(
                f"{table} page {page} next_cursor_id has invalid type "
                f"{type(next_cursor).__name__}")
        if next_cursor is not None:
            next_cursor = str(next_cursor)
            if not next_cursor:
                next_cursor = None
    return cols, raw_rows, next_cursor


def fetch_table(table: str, params: Mapping[str, str] | None = None, *,
                http=None, sleep=time.sleep) -> Iterator[dict]:
    """Yield every row of `table` matching `params`, following the cursor.

    `http` is injectable so the ingest can be driven end-to-end without a
    network; production passes nothing and gets `httpx`.
    """
    # Refuse missing credentials before importing the optional HTTP client. A
    # deployment with two faults must still report the safety boundary first.
    key = _api_key()
    if http is None:
        import httpx                      # noqa: PLC0415 — optional at import
        http = httpx
    url = f"{NDL_BASE}/{table}.json"
    cursor: Optional[str] = None
    seen_cursors: set[str] = set()
    pages = 0

    if FETCH_MAX_PAGES <= 0:
        raise PaginationError("SHARADAR_FETCH_MAX_PAGES must be positive")

    with http.Client(timeout=FETCH_TIMEOUT_SECS) as client:
        while True:
            if pages >= FETCH_MAX_PAGES:
                raise PaginationError(
                    f"{table} pagination exceeded the bounded cap of "
                    f"{FETCH_MAX_PAGES:,} pages")
            q = {"api_key": key, **(params or {})}
            if cursor:
                q["qopts.cursor_id"] = cursor
            resp = _get_with_retry(client, url, q, http=http, sleep=sleep)
            pages += 1
            cols, rows, next_cursor = _decode_page(resp, table, pages)
            for row in rows:
                yield dict(zip(cols, row))
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
                last_exc = exc            # reset / read timeout / DNS blip
            else:
                response = getattr(exc, "response", None)
                code = getattr(response, "status_code", None)
                label = f"HTTP {code}" if code is not None else type(exc).__name__
                raise SharadarRequestError(
                    f"Sharadar request failed ({label}) for "
                    f"{_safe_request_target(url, params)}") from None
        if attempt < FETCH_MAX_RETRIES - 1:
            delay = retry_delay(attempt, status, retry_after)
            print(f"[sentinel-feed] transient fetch failure "
                  f"({status or type(last_exc).__name__}) attempt "
                  f"{attempt + 1}/{FETCH_MAX_RETRIES} — retrying in {delay:.0f}s",
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
    """Split a range into calendar years.

    Chunking is what makes progress meaningful and a restart cheap: the SEP fetch
    is thousands of cursor pages over hours, and a run that reports one unit of
    work reports nothing at all until it is finished.
    """
    date_from, date_to = validate_date_range(date_from, date_to)
    y0, y1 = int(date_from[:4]), int(date_to[:4])
    out = []
    for y in range(y0, y1 + 1):
        lo = max(f"{y}-01-01", date_from)
        hi = min(f"{y}-12-31", date_to)
        if lo <= hi:
            out.append((lo, hi))
    return out
