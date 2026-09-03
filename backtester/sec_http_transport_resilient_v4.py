#!/usr/bin/env python3
"""V4 SEC transport hardening for truncated HTTP bodies.

The frozen V2 transport already retries HTTP throttling, server errors, URL errors,
timeouts, and OS errors. Python's ``http.client.IncompleteRead`` is an
``HTTPException`` and can escape that retry loop when a chunked SEC response is
truncated. V4 retries the entire request and never accepts partial response bytes.
"""
from __future__ import annotations

import http.client
import time

from backtester import historical_metadata_reconstruction_v2 as v2


class ResilientSecHttpTransport(v2.SecHttpTransport):
    """Retry protocol-level truncation around the existing fail-closed transport."""

    def get(self, url: str):
        last_error = ""
        for protocol_attempt in range(1, self.max_attempts + 1):
            try:
                return super().get(url)
            except http.client.HTTPException as exc:
                # No cache file exists until the parent has read the complete body and
                # atomically replaces the temporary file, so partial bytes are discarded.
                self.last_request_at = time.monotonic()
                last_error = repr(exc)
                self.counters["transport_errors"] += 1
                self.counters["http_protocol_errors"] += 1
                if protocol_attempt == self.max_attempts:
                    break
                self.counters["retries"] += 1
                self.counters["http_protocol_retries"] += 1
                time.sleep(min(30.0, 1.0 * (2 ** (protocol_attempt - 1))))
        self.counters["failures"] += 1
        self.failures.append({
            "url": url,
            "error": last_error,
            "attempts": self.max_attempts,
            "failure_class": "http_protocol",
        })
        raise v2.ReconstructionError(
            f"SEC request failed after protocol retries: {url}: {last_error}"
        )
