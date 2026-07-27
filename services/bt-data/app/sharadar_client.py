"""Thin async client for Sharadar tables via the Nasdaq Data Link API.

Endpoint shape (Tables API):
  GET https://data.nasdaq.com/api/v3/datatables/SHARADAR/{TABLE}.json
      ?api_key=...&date.gte=YYYY-MM-DD&date.lte=YYYY-MM-DD&ticker=AAPL,MSFT&qopts.cursor_id=...

Tables: SEP (prices), SF1 (fundamentals), TICKERS (metadata).
Responses are cursor-paginated: datatable.data (rows), datatable.columns (schema),
meta.next_cursor_id (None when done). We yield dict rows (column-name → value).

DATA MODE is EXPLICIT (BT_DATA_MODE=sharadar|frozen|mock, default sharadar):

  sharadar  fetch from Nasdaq Data Link. Requires SHARADAR_API_KEY.
  frozen    NO fetching, but the corpus already in bt-postgres is REAL and
            research-grade. This is the state after a subscription is cancelled:
            20 years of downloaded history keeps working, backtests keep
            running, only new data stops. Needs no key and is NOT mock.
  mock      tiny synthetic dataset so the service + backfill + tests run with
            no network/key. Results are NOT research-grade.

`frozen` exists because "can fetch new data" and "can run backtests" are
different capabilities, and conflating them would mean cancelling the
subscription bricked a corpus that is already paid for and on disk.

A MISSING KEY IS NOT A REQUEST FOR MOCK DATA. This used to be
`BT_MOCK_DATA or not SHARADAR_API_KEY`, so a secret that failed to load silently
substituted a synthetic corpus — and every downstream number stayed shaped like
a real backtest, feeding a promotion gate that rewrites the live strategy. Now
`mode=sharadar` with no key raises at startup. Legacy BT_MOCK_DATA=true is still
honoured as an explicit request for mock.
"""
from __future__ import annotations

import asyncio
import os
from datetime import date, timedelta
from typing import AsyncIterator, Optional

import httpx

NDL_BASE = os.getenv("NDL_BASE_URL", "https://data.nasdaq.com/api/v3/datatables/SHARADAR")
SHARADAR_API_KEY = os.getenv("SHARADAR_API_KEY", "")
BT_MOCK_DATA = os.getenv("BT_MOCK_DATA", "").lower() in ("1", "true", "yes")
BT_DATA_MODE = (os.getenv("BT_DATA_MODE", "") or
                ("mock" if BT_MOCK_DATA else "sharadar")).strip().lower()
VALID_DATA_MODES = ("sharadar", "frozen", "mock")

# A full-universe backfill follows thousands of cursor pages over several hours.
# WITHOUT retry, a single transient blip (network reset, Sharadar 429/5xx, read
# timeout) raised out of fetch_table and failed the ENTIRE run — the "stuck at
# 25M then frozen" symptom. Retry the SAME cursor page (idempotent GET) with
# exponential backoff so a hiccup self-heals instead of aborting the load.
# Non-retryable 4xx (auth/bad-request) still fail fast.
#
# 429 (rate-limit) gets SPECIAL treatment: Nasdaq throttles heavy usage (five
# full re-downloads in one day will do it) and a throttle can last many
# minutes — far longer than the generic 2..32s backoff, which gave up in ~1
# minute and killed the run. For 429 we honor the Retry-After header when
# present and otherwise wait 60s×attempt, tolerating up to ~15 min of
# throttling before giving up. Every retry is LOGGED so docker logs finally
# show what a "silent" stall actually is.
FETCH_TIMEOUT_SECS = float(os.getenv("SHARADAR_FETCH_TIMEOUT", "120"))
FETCH_MAX_RETRIES = int(os.getenv("SHARADAR_FETCH_RETRIES", "6"))
FETCH_BACKOFF_BASE = float(os.getenv("SHARADAR_FETCH_BACKOFF", "2.0"))
RATE_LIMIT_BACKOFF_CAP = float(os.getenv("SHARADAR_429_BACKOFF_CAP", "900"))
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


def _retry_delay(attempt: int, status: int | None, retry_after: str | None) -> float:
    """Pure: seconds to wait before retry `attempt` (0-based). 429 honors
    Retry-After and defaults to 60s×(attempt+1); everything else uses the
    generic exponential backoff."""
    if status == 429:
        delay = 60.0 * (attempt + 1)
        if retry_after:
            try:
                delay = max(delay, float(retry_after))
            except ValueError:
                pass  # HTTP-date form — keep the default
        return min(delay, RATE_LIMIT_BACKOFF_CAP)
    return FETCH_BACKOFF_BASE * (2 ** attempt)


async def _get_with_retry(client: httpx.AsyncClient, url: str, params: dict) -> httpx.Response:
    """GET with bounded backoff retry on transient failures (429-aware)."""
    last_exc: Exception | None = None
    for attempt in range(FETCH_MAX_RETRIES):
        status: int | None = None
        retry_after: str | None = None
        try:
            resp = await client.get(url, params=params)
            if resp.status_code in _RETRYABLE_STATUS:
                # synthesise a retryable error so the same backoff path applies
                raise httpx.HTTPStatusError(
                    f"retryable HTTP {resp.status_code}",
                    request=resp.request, response=resp)
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status not in _RETRYABLE_STATUS:
                raise  # 400/401/403/404 etc. — real error, don't retry
            retry_after = exc.response.headers.get("Retry-After") if exc.response is not None else None
            last_exc = exc
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_exc = exc  # connection reset / read timeout / DNS blip
        if attempt < FETCH_MAX_RETRIES - 1:
            delay = _retry_delay(attempt, status, retry_after)
            print(f"[bt-data] transient fetch failure "
                  f"({status or type(last_exc).__name__}) attempt "
                  f"{attempt + 1}/{FETCH_MAX_RETRIES} — retrying in {delay:.0f}s",
                  flush=True)
            await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc


class DataModeError(RuntimeError):
    """Configured for real data without the means to fetch it."""


def data_mode() -> str:
    """'sharadar' | 'frozen' | 'mock' — EXPLICIT, never inferred from a missing
    secret."""
    if BT_DATA_MODE not in VALID_DATA_MODES:
        raise DataModeError(
            f"BT_DATA_MODE={BT_DATA_MODE!r} is not one of "
            f"{', '.join(VALID_DATA_MODES)}")
    return BT_DATA_MODE


def corpus_is_real() -> bool:
    """Is the data backing this service genuine market history?

    True for BOTH sharadar and frozen — a cancelled subscription does not make
    the 20 years already on disk synthetic. Only `mock` is not real. This is the
    predicate that belongs on a research result, not `is_mock()`'s inverse by
    accident."""
    return data_mode() in ("sharadar", "frozen")


def fetching_enabled() -> bool:
    """Can this service acquire NEW data? False when frozen."""
    return data_mode() != "frozen"


def verify_data_mode() -> str:
    """Called at STARTUP. Fails loudly rather than downgrading to synthetic data.

    The whole point: a research platform whose corpus can be replaced by a toy
    dataset because an env var did not load produces reports that look exactly
    like real ones."""
    mode = data_mode()
    if mode == "sharadar" and not SHARADAR_API_KEY:
        raise DataModeError(
            "BT_DATA_MODE=sharadar but SHARADAR_API_KEY is empty. Refusing to "
            "fall back to synthetic data — a missing secret must not silently "
            "replace the historical corpus. Set the key; set BT_DATA_MODE=frozen "
            "to keep using the corpus already downloaded WITHOUT fetching (the "
            "right setting after cancelling the subscription); or set "
            "BT_DATA_MODE=mock to ask for synthetic data deliberately.")
    return mode


def is_mock() -> bool:
    """Mock ONLY when explicitly configured. A missing key is an error, not a
    mode (see verify_data_mode)."""
    return data_mode() == "mock"


async def fetch_table(
    table: str,
    *,
    params: Optional[dict] = None,
    page_limit: Optional[int] = None,
) -> AsyncIterator[dict]:
    """Yield rows (as column-name→value dicts) from a Sharadar table, following
    the cursor pagination. `params` are Nasdaq Data Link filters
    (e.g. {"date.gte": "2020-01-01", "ticker": "AAPL,MSFT"}).

    page_limit caps the number of pages fetched (None = all) — useful for tests.
    """
    if not fetching_enabled():
        raise DataModeError(
            "BT_DATA_MODE=frozen: refusing to fetch. The corpus already in "
            "bt-postgres stays fully usable — backtests and sweeps are "
            "unaffected; only acquiring NEW data is disabled.")
    if is_mock():
        async for row in _mock_rows(table, params or {}):
            yield row
        return

    cursor: Optional[str] = None
    pages = 0
    async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_SECS) as client:
        while True:
            q = {"api_key": SHARADAR_API_KEY, **(params or {})}
            if cursor:
                q["qopts.cursor_id"] = cursor
            resp = await _get_with_retry(client, f"{NDL_BASE}/{table}.json", q)
            payload = resp.json()
            dt = payload["datatable"]
            cols = [c["name"] for c in dt["columns"]]
            for raw in dt["data"]:
                yield dict(zip(cols, raw))
            cursor = (payload.get("meta") or {}).get("next_cursor_id")
            pages += 1
            if pages % 25 == 0:   # heartbeat: fetch progress is visible in logs
                print(f"[bt-data] {table} fetch: {pages} pages "
                      f"({params or {}})", flush=True)
            if not cursor or (page_limit is not None and pages >= page_limit):
                break


# ── Mock dataset (no network / no key) ─────────────────────────────────────────
# A handful of tickers with a deterministic synthetic price walk + a couple of
# quarterly fundamentals, so the backfill, the data-depth report, and the engine
# can be exercised end-to-end before the real Sharadar subscription is live.

_MOCK_TICKERS = ["AAA", "BBB", "CCC", "SPY"]
_MOCK_START = date(2022, 1, 3)
_MOCK_DAYS = 400


async def _mock_rows(table: str, params: dict) -> AsyncIterator[dict]:
    if table == "SEP":
        base = {"AAA": 100.0, "BBB": 50.0, "CCC": 200.0, "SPY": 400.0}
        drift = {"AAA": 0.05, "BBB": 0.02, "CCC": -0.01, "SPY": 0.03}  # %/day-ish
        for t in _MOCK_TICKERS:
            px = base[t]
            for i in range(_MOCK_DAYS):
                d = _MOCK_START + timedelta(days=i)
                if d.weekday() >= 5:  # skip weekends
                    continue
                # deterministic wiggle
                px = px * (1 + drift[t] / 100.0) + ((i % 7) - 3) * 0.01
                yield {
                    "ticker": t, "date": d.isoformat(),
                    "open": round(px * 0.999, 4), "high": round(px * 1.01, 4),
                    "low": round(px * 0.99, 4), "close": round(px, 4),
                    "closeadj": round(px, 4), "closeunadj": round(px, 4),
                    "volume": 1_000_000 + (i % 5) * 50_000,
                }
    elif table == "SFP":
        # Fund prices (ETFs) — mock SPY so the benchmark path is exercisable.
        px = 400.0
        for i in range(_MOCK_DAYS):
            d = _MOCK_START + timedelta(days=i)
            if d.weekday() >= 5:
                continue
            px = px * 1.0003 + ((i % 7) - 3) * 0.01
            yield {"ticker": "SPY", "date": d.isoformat(),
                   "open": round(px * 0.999, 4), "high": round(px * 1.01, 4),
                   "low": round(px * 0.99, 4), "close": round(px, 4),
                   "closeadj": round(px, 4), "closeunadj": round(px, 4),
                   "volume": 80_000_000}
    elif table == "SF1":
        for t in ["AAA", "BBB", "CCC"]:
            for q, dk in enumerate(["2022-03-15", "2022-06-15", "2022-09-15",
                                    "2022-12-15", "2023-03-15"]):
                yield {
                    "ticker": t, "datekey": dk, "calendardate": dk, "dimension": "ARQ",
                    "pe": 15 + q, "pb": 2.0 + q * 0.1, "roe": 0.15 + q * 0.01,
                    "de": 0.5 + q * 0.05, "revenue": 1000 + q * 50, "eps": 2.0 + q * 0.1,
                }
    elif table == "TICKERS":
        meta = {"AAA": ("Alpha Co", "Technology"), "BBB": ("Beta Inc", "Energy"),
                "CCC": ("Gamma Ltd", "Financial Services"), "SPY": ("S&P 500 ETF", "ETF")}
        for t, (name, sector) in meta.items():
            yield {
                "ticker": t, "name": name, "sector": sector,
                "category": "ETF" if t == "SPY" else "Domestic Common Stock",
                "exchange": "NYSE",
            }
