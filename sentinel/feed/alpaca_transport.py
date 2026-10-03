"""Bounded GET-only operational input transport for Alpaca.

No account or order endpoint is reachable through this client. Returned bytes,
timestamps and request parameters are evidence, never a vendor-wide snapshot.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from sentinel.feed import rolling_work

DATA = "https://data.alpaca.markets"
ASSETS = "https://paper-api.alpaca.markets/v2/assets"
BAR_URL = DATA + "/v2/stocks/bars"
ACTION_URL = DATA + "/v1/corporate-actions"
ALLOWED = frozenset((ASSETS, BAR_URL, ACTION_URL))
MAX_RESPONSE_BYTES = 32 * 1024 * 1024
MAX_PAGES = 2000
MAX_RETRIES = 4
MIN_REQUEST_INTERVAL_SECONDS = 0.35  # Basic historical-data allowance: 200/min.


class AlpacaTransportRefused(RuntimeError):
    pass


class AlpacaTransportUnavailable(AlpacaTransportRefused):
    """A bounded retry budget ended on a retryable provider/transport failure."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, *, opener=None, sleeper=time.sleep, clock=None,
                 monotonic=time.monotonic, interval=MIN_REQUEST_INTERVAL_SECONDS):
        self._opener = opener or build_opener(_NoRedirect())
        self._sleep = sleeper
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic
        self._interval = interval
        self._last_request = None

    def _pace(self):
        now = self._monotonic()
        if self._last_request is not None:
            delay = self._interval - (now - self._last_request)
            if delay > 0:
                self._sleep(delay)
                now = self._monotonic()
        self._last_request = now

    def get(self, endpoint: str, params: dict | None = None, *, text=False):
        if endpoint not in ALLOWED or text:
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
        for attempt in range(MAX_RETRIES):
            rolling_work.checkpoint()
            self._pace()
            request = Request(url, headers=headers, method="GET")
            try:
                with self._opener.open(request, timeout=45) as response:
                    if response.status != 200:
                        raise AlpacaTransportRefused("provider returned a non-200 response")
                    raw = response.read(MAX_RESPONSE_BYTES + 1)
                    if len(raw) > MAX_RESPONSE_BYTES:
                        raise AlpacaTransportRefused("provider response exceeds bounded size")
                    observed = self._clock().astimezone(timezone.utc).isoformat()
                    try:
                        value = raw.decode("utf-8-sig") if text else json.loads(raw)
                    except (UnicodeError, ValueError):
                        raise AlpacaTransportRefused("provider response is not valid UTF-8/JSON") from None
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
                    raw_wait = exc.headers.get("Retry-After", "1") if exc.headers else "1"
                    try:
                        wait = min(60, max(1, int(raw_wait)))
                    except (TypeError, ValueError):
                        wait = 60
            except (URLError, TimeoutError, OSError):
                wait = 0
            if attempt + 1 == MAX_RETRIES:
                break
            self._sleep(max(wait, min(2 ** attempt, 8)))
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
