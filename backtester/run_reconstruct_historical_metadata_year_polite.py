#!/usr/bin/env python3
"""Run yearly SEC metadata harvest with conservative SEC-aware transport behavior.

This wrapper preserves the evidence semantics in reconstruct_historical_metadata_year.py
and only changes network transport: low request rate, explicit HTTP status logging,
Retry-After handling, exponential cooldowns for 403/429/5xx, and atomic cache writes.
"""
from __future__ import annotations

import email.utils
import http.client
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import backtester.reconstruct_historical_metadata_year as yearly


def _retry_after_seconds(headers) -> float | None:
    value = headers.get("Retry-After") if headers is not None else None
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            dt = email.utils.parsedate_to_datetime(value)
            return max(0.0, dt.timestamp() - time.time())
        except Exception:
            return None


def _polite_get(self: yearly.SecClient, url: str) -> bytes:
    path = self._path(url)
    if path.exists():
        self.cache_hits += 1
        return path.read_bytes()

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": yearly.base.USER_AGENT,
            "Accept-Encoding": "identity",
            "Connection": "close",
        },
    )
    last: Exception | None = None
    attempts = 8

    for attempt in range(attempts):
        tmp = Path(str(path) + f".tmp-{os.getpid()}")
        try:
            time.sleep(self.delay)
            with urllib.request.urlopen(req, timeout=90) as response:
                data = response.read()
            tmp.write_bytes(data)
            tmp.replace(path)
            self.requests += 1
            return data
        except urllib.error.HTTPError as exc:
            last = exc
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
            retry_after = _retry_after_seconds(exc.headers)
            status = exc.code
            if retry_after is not None:
                wait = retry_after
            elif status in (403, 429):
                wait = min(180.0, 30.0 * (2 ** attempt))
            elif 500 <= status <= 599:
                wait = min(90.0, 5.0 * (2 ** attempt))
            else:
                wait = min(30.0, 2.0 * (2 ** attempt))
            print(
                f"[HTTP_RETRY] year={self.year} attempt={attempt + 1}/{attempts} "
                f"status={status} retry_after={retry_after if retry_after is not None else 'none'} "
                f"sleep_s={wait:.1f} url={url}",
                flush=True,
            )
            time.sleep(wait)
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            http.client.HTTPException,
            http.client.IncompleteRead,
            http.client.RemoteDisconnected,
        ) as exc:
            last = exc
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
            wait = min(60.0, 2.0 * (2 ** attempt))
            print(
                f"[TRANSPORT_RETRY] year={self.year} attempt={attempt + 1}/{attempts} "
                f"error={type(exc).__name__} sleep_s={wait:.1f} url={url}",
                flush=True,
            )
            time.sleep(wait)

    self.failures.append({"url": url, "error": repr(last)})
    raise yearly.ReconstructionError(f"SEC fetch failed after retries: {url}: {last}")


def main() -> int:
    yearly.SecClient.get = _polite_get
    return yearly.main()


if __name__ == "__main__":
    raise SystemExit(main())
