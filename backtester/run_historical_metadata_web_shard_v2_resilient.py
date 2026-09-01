#!/usr/bin/env python3
"""Transport-hardened launcher for historical metadata V2 web shards.

This module is deliberately outside the authenticated economic/parser source bundle.
It changes only transport retry/observability behavior while invoking the pinned V2
runner and reconstruction implementation unchanged.
"""
from __future__ import annotations

import builtins
import http.client
import json
import os
import re
import time
from pathlib import Path

from backtester import historical_metadata_reconstruction_v2 as base
from backtester import run_historical_metadata_web_shard_v2 as runner

_PROGRESS_RE = re.compile(
    r"^\[PROGRESS\]\s+shard=(\S+)\s+(?:ciks=(\d+)/(\d+)\s+pct=([0-9.]+)%|start\b)(.*)$"
)


class _RetryableBodyError(RuntimeError):
    pass


class ResilientSecHttpTransport(base.SecHttpTransport):
    """Add bounded retries for response-body failures missed by the base transport."""

    def _discard_cached_response(self, url: str) -> None:
        path = self._cache_path(url)
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    @staticmethod
    def _validate_body(url: str, data: bytes | None) -> None:
        if data is None:
            return
        if not data:
            raise _RetryableBodyError("empty HTTP 200 response body")
        if url.lower().split("?", 1)[0].endswith(".json"):
            try:
                json.loads(data)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise _RetryableBodyError(f"invalid JSON response body: {exc}") from exc

    def get(self, url: str):
        last_error: BaseException | None = None
        # The base transport already performs bounded retries for HTTP status,
        # URLError, timeout and OSError failures. This outer loop covers failures
        # raised while consuming an otherwise-open response body (notably
        # http.client.IncompleteRead) plus complete-but-invalid/empty bodies.
        for body_attempt in range(1, self.max_attempts + 1):
            try:
                data, result = super().get(url)
                try:
                    self._validate_body(url, data)
                except _RetryableBodyError:
                    # super().get counted this as a success and persisted it.
                    self._discard_cached_response(url)
                    if self.counters["successes"] > 0:
                        self.counters["successes"] -= 1
                    status_key = f"status_{result.status}"
                    if self.counters[status_key] > 0:
                        self.counters[status_key] -= 1
                    raise
                return data, result
            except (http.client.HTTPException, _RetryableBodyError, EOFError) as exc:
                last_error = exc
                self.last_request_at = time.monotonic()
                self._discard_cached_response(url)
                self.counters["transport_errors"] += 1
                if body_attempt >= self.max_attempts:
                    break
                self.counters["retries"] += 1
                delay = min(30.0, float(2 ** (body_attempt - 1)))
                builtins.print(
                    f"[TRANSPORT-RETRY] body_attempt={body_attempt}/{self.max_attempts} "
                    f"delay={delay:.1f}s error={type(exc).__name__}: {exc}",
                    flush=True,
                )
                time.sleep(delay)

        self.counters["failures"] += 1
        error_text = repr(last_error) if last_error is not None else "unknown response-body failure"
        self.failures.append({"url": url, "error": error_text, "attempts": self.max_attempts})
        raise base.ReconstructionError(f"SEC response body failed after retries: {url}: {error_text}")


def _install_live_github_progress() -> None:
    """Mirror percentage progress into GitHub's live log, annotations and summary."""
    real_print = builtins.print
    summary = os.environ.get("GITHUB_STEP_SUMMARY", "")
    last_notice_bucket: dict[str, int] = {}

    def visible_print(*values, **kwargs):
        real_print(*values, **kwargs)
        text = " ".join(str(value) for value in values)
        match = _PROGRESS_RE.match(text)
        if not match:
            return
        shard, done, total, pct, tail = match.groups()
        if done is None:
            label = f"Shard {shard}: starting/resuming"
            pct_value = 0.0
        else:
            pct_value = float(pct)
            label = f"Shard {shard}: {pct_value:.1f}% ({done}/{total} CIKs){tail}"

        if summary:
            try:
                Path(summary).write_text(
                    "# Historical metadata V2 — live progress\n\n"
                    f"**{label}**\n\n"
                    "This file is refreshed after every completed CIK. "
                    "The active job log also streams every percentage update.\n",
                    encoding="utf-8",
                )
            except OSError:
                pass

        bucket = int(pct_value // 5) if done is not None else -1
        if last_notice_bucket.get(shard) != bucket or "status=PASS" in tail:
            last_notice_bucket[shard] = bucket
            # Workflow command annotations are rendered by the GitHub Actions UI.
            real_print(f"::notice title=SEC metadata live progress::{label}", flush=True)

    builtins.print = visible_print


def main() -> int:
    original_transport = base.SecHttpTransport
    _install_live_github_progress()
    base.SecHttpTransport = ResilientSecHttpTransport
    try:
        return runner.main()
    finally:
        base.SecHttpTransport = original_transport


if __name__ == "__main__":
    raise SystemExit(main())
