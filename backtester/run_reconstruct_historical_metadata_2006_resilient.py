#!/usr/bin/env python3
"""Run the 2006 SEC metadata reconstruction with retry-safe HTTP reads.

The evidence harvester deliberately retains the original reconstruction semantics.
This wrapper only strengthens transport behavior for GitHub-hosted runners: interrupted
chunked responses, remote disconnects, and other HTTP transport exceptions are retried
without admitting partial bytes into the evidence cache.
"""
from __future__ import annotations

import http.client
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import backtester.reconstruct_historical_metadata_2006 as reconstruction


def _retry_safe_get(self: reconstruction.SecClient, url: str) -> bytes:
    path = self._path(url)
    if path.exists():
        self.cache_hits += 1
        return path.read_bytes()

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": reconstruction.USER_AGENT,
            "Accept-Encoding": "identity",
            "Connection": "close",
        },
    )
    last: Exception | None = None
    retryable = (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        http.client.HTTPException,
        http.client.IncompleteRead,
        http.client.RemoteDisconnected,
    )
    for attempt in range(8):
        tmp = Path(str(path) + f".tmp-{os.getpid()}")
        try:
            time.sleep(self.delay)
            with urllib.request.urlopen(req, timeout=60) as response:
                data = response.read()
            tmp.write_bytes(data)
            tmp.replace(path)
            self.requests += 1
            return data
        except retryable as exc:
            last = exc
            try:
                tmp.unlink()
            except FileNotFoundError:
                pass
            time.sleep(min(20.0, 0.75 * (2 ** attempt)))

    self.failures.append({"url": url, "error": repr(last)})
    raise reconstruction.ReconstructionError(
        f"SEC fetch failed after transport retries: {url}: {last}"
    )


def main() -> int:
    reconstruction.SecClient.get = _retry_safe_get
    return reconstruction.main()


if __name__ == "__main__":
    raise SystemExit(main())
