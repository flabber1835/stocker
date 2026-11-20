"""Bounded GET-only operational input transport for Alpaca.

No account or order endpoint is reachable through this client. Returned bytes,
timestamps and request parameters are evidence, never a vendor-wide snapshot.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request

import httpx

from sentinel.feed import provider_budget, provider_http, rolling_work
from sentinel.trading_environment import TradingEndpoint

DATA = "https://data.alpaca.markets"
ASSETS = "https://paper-api.alpaca.markets/v2/assets"
BAR_URL = DATA + "/v2/stocks/bars"
ACTION_URL = DATA + "/v1/corporate-actions"
ALLOWED = frozenset((ASSETS, BAR_URL, ACTION_URL))
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_PAGES = 2000
MAX_RETRIES = 4
NETWORK_FAILURES = (URLError, TimeoutError, OSError, httpx.TransportError)
MIN_REQUEST_INTERVAL_SECONDS = 0.35  # Basic historical-data allowance: 200/min.


@dataclass
class RequestMetrics:
    requests: int = 0
    retries: int = 0
    response_bytes: int = 0
    rate_limits: int = 0
    elapsed_ns: dict[str, int] = field(default_factory=dict)

    def fields(self):
        return dict(requests=self.requests, retries=self.retries, response_bytes=self.response_bytes,
                    rate_limits=self.rate_limits,
                    **{name + '_ms': self.elapsed_ns.get(name, 0) // 1_000_000
                       for name in ('pacing', 'http', 'decode', 'retry_backoff')})


_request_metrics: ContextVar[RequestMetrics | None] = ContextVar('alpaca_request_metrics', default=None)


@contextmanager
def measure_requests():
    """Aggregate diagnostics for one caller-owned part, without touching proof bytes."""
    metrics = RequestMetrics()
    token = _request_metrics.set(metrics)
    try:
        yield metrics
    finally:
        _request_metrics.reset(token)


@contextmanager
def _measure(metrics, phase):
    started = time.perf_counter_ns()
    try:
        yield
    finally:
        if metrics is not None:
            metrics.elapsed_ns[phase] = metrics.elapsed_ns.get(phase, 0) + time.perf_counter_ns() - started


class AlpacaTransportRefused(RuntimeError):
    pass


class AlpacaTransportUnavailable(AlpacaTransportRefused):
    """A bounded retry budget ended on a retryable provider/transport failure."""

    def __init__(self, message, *, delay=10):
        super().__init__(message)
        self.delay = delay


def request_timeout():
    left = provider_budget.remaining()
    if left is not None and left <= 0:
        raise AlpacaTransportUnavailable("source acquisition deadline exhausted")
    return 45.0 if left is None else min(45.0, left)


def provider_pause(seconds, sleep):
    left = provider_budget.remaining()
    if left is not None and seconds >= left:
        raise AlpacaTransportUnavailable("provider wait exceeds acquisition deadline", delay=seconds)
    sleep(seconds)
    request_timeout()


def check_provider(provider):
    request_timeout()
    delay = provider_budget.cooldown_remaining(provider)
    if delay:
        raise AlpacaTransportUnavailable("provider rate limit is still active", delay=delay)


def rate_limit(provider, headers, *, default):
    text = headers.get('Retry-After') if headers else None
    try:
        delay = max(1, int(text))
    except (TypeError, ValueError):
        try:
            delay = max(1, parsedate_to_datetime(text).timestamp() - time.time())
        except (AttributeError, TypeError, ValueError, OverflowError):
            delay = default
    provider_budget.defer_for(delay, provider=provider)
    return delay


def read_bounded(response, limit):
    # read1 bounds each iteration to a single underlying read on HTTPResponse.
    read = getattr(response, 'read1', response.read)
    raw = bytearray()
    while len(raw) <= limit:
        request_timeout()
        chunk = read(min(64 * 1024, limit + 1 - len(raw)))
        if not chunk:
            break
        raw.extend(chunk)
    request_timeout()
    return raw


def request_bytes(request, limit, *, opener=None, pooled=None):
    if opener is None:
        return (pooled or provider_http.fetch)(request, limit)
    with opener.open(request, timeout=request_timeout()) as response:
        if response.status != 200:
            raise AlpacaTransportRefused("provider returned a non-200 response")
        return read_bounded(response, limit)


class Client:
    def __init__(self, *, opener=None, sleeper=time.sleep, clock=None,
                 monotonic=time.monotonic, interval=MIN_REQUEST_INTERVAL_SECONDS, base_url=None):
        self.trading_endpoint = TradingEndpoint.parse(
            os.environ.get('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')
            if base_url is None else base_url)
        self.assets_url = self.trading_endpoint.assets_url
        self._allowed = frozenset((self.assets_url, BAR_URL, ACTION_URL))
        self._opener = opener
        self._pool = None
        self._sleep = sleeper
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic
        self._interval = interval
        self._last_request = None

    @contextmanager
    def pooled(self):
        """Keep connections alive only during an owned acquisition operation."""
        if self._opener is not None or self._pool is not None:
            yield
            return
        with provider_http.pool() as pool:
            self._pool = pool
            try:
                yield
            finally:
                self._pool = None

    def _pace(self):
        now = self._monotonic()
        if self._last_request is not None:
            delay = self._interval - (now - self._last_request)
            if delay > 0:
                provider_pause(delay, self._sleep)
                now = self._monotonic()
        self._last_request = now

    def get(self, endpoint: str, params: dict | None = None, *, text=False):
        if endpoint not in self._allowed or text:
            raise AlpacaTransportRefused("unsupported operational input endpoint")
        params = dict(params or {})
        if any(not isinstance(k, str) or not isinstance(v, (str, int))
               for k, v in params.items()):
            raise AlpacaTransportRefused("invalid provider request parameters")
        key = os.environ.get("ALPACA_API_KEY", "").strip()
        secret = os.environ.get("ALPACA_SECRET_KEY", "").strip()
        if not key or not secret:
            raise AlpacaTransportRefused("Alpaca read-only data credentials are absent")
        headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
        url = endpoint + ("?" + urlencode(params) if params else "")
        metrics = _request_metrics.get()
        for attempt in range(MAX_RETRIES):
            rolling_work.checkpoint()
            with _measure(metrics, 'pacing'):
                self._pace()
            check_provider(DATA)
            request = Request(url, headers=headers, method="GET")
            if metrics is not None:
                metrics.requests += 1
                metrics.retries += int(attempt > 0)
            try:
                with _measure(metrics, 'http'):
                    raw = request_bytes(request, MAX_RESPONSE_BYTES, opener=self._opener, pooled=self._pool)
                    if metrics is not None:
                        metrics.response_bytes += len(raw)
                    if len(raw) > MAX_RESPONSE_BYTES:
                        raise AlpacaTransportRefused("provider response exceeds bounded size")
                    observed = self._clock().astimezone(timezone.utc).isoformat()
                with _measure(metrics, 'decode'):
                    try:
                        value = raw.decode("utf-8-sig") if text else json.loads(raw)
                    except (UnicodeError, ValueError):
                        raise AlpacaTransportRefused("provider response is not valid UTF-8/JSON") from None
                    request_timeout()
                    return value, {"endpoint": endpoint, "params": params,
                                   "observed_at": observed,
                                   "sha256": hashlib.sha256(raw).hexdigest(),
                                   "bytes": len(raw)}
            except HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504):
                    raise AlpacaTransportRefused(
                        "provider refused request with HTTP " + str(exc.code)) from None
                wait = 0
                if exc.code == 429:
                    if metrics is not None:
                        metrics.rate_limits += 1
                    wait = rate_limit(DATA, exc.headers, default=60)
            except NETWORK_FAILURES:
                wait = 0
            if wait and (wait > 60 or attempt + 1 == MAX_RETRIES):
                raise AlpacaTransportUnavailable("provider rate limit exceeds retry window", delay=wait)
            if attempt + 1 == MAX_RETRIES:
                break
            with _measure(metrics, 'retry_backoff'):
                provider_pause(max(wait, min(2 ** attempt, 8)), self._sleep)
        raise AlpacaTransportUnavailable("provider request exhausted its retry budget")

    def pages(self, endpoint: str, params: dict, *, key: str):
        """Yield complete pages and byte evidence; repeated tokens refuse."""
        if endpoint not in (BAR_URL, ACTION_URL) or key not in ("bars", "corporate_actions"):
            raise AlpacaTransportRefused("unsupported operational pagination")
        token = None
        seen = set()
        for _ in range(MAX_PAGES):
            query = dict(params)
            if token:
                query["page_token"] = token
            value, proof = self.get(endpoint, query)
            if not isinstance(value, dict) or not isinstance(value.get(key), dict):
                raise AlpacaTransportRefused("provider page has invalid response shape")
            following = value.get("next_page_token")
            if following is not None and (not isinstance(following, str)
                                          or not following or following in seen):
                raise AlpacaTransportRefused("provider repeated or corrupted a page token")
            yield value[key], proof
            if following is None:
                return
            seen.add(following)
            token = following
        raise AlpacaTransportRefused("provider pagination exceeded the page bound")
