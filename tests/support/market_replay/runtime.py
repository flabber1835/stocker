"""Explicit test-only transport, clock and producer seams."""
from __future__ import annotations

import datetime as dt
import os
import tempfile
from pathlib import Path
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import patch


from .provider import Provider


@contextmanager
def simulated_runtime(provider: Provider, *, commit: str):
    from sentinel import identity
    from sentinel.feed import acquisition_work, archive_tables, ingest, operational_source, provider_budget, seed_coherence, snapshot_export, snapshot_source

    class ClockDateTime(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            if provider.step is None:
                raise RuntimeError("clock has no current event")
            instant = provider.step.at
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    provider._reader = snapshot_export.download_snapshot

    def captured_rows(table, params=None):
        capture = operational_source.current()
        if capture is not None and table in (archive_tables.SEP, archive_tables.ACTIONS):
            return capture.fetch_rows(table, params)
        return provider.fetch_rows(table, params)

    def exported(table, *, params, required):
        capture = operational_source.current()
        if capture is not None:
            return capture.export_rows(table, params, required=required)
        return provider.read_snapshot(provider.snapshot(table, params=params), required=required)

    def corroborate(*, through, evidence):
        from sentinel.feed.authority import VendorPublicationUnstable
        current = provider.snapshot(archive_tables.ACTIONS, params={'date.gte':'1900-01-01', 'date.lte':through})
        if current.refreshed.isoformat() != evidence.get('last_refreshed_time'):
            raise VendorPublicationUnstable('Captured action generation changed')
        return evidence

    clock_module = SimpleNamespace(datetime=ClockDateTime, date=dt.date,
                                   timedelta=dt.timedelta, timezone=dt.timezone)
    ceiling = seed_coherence.capture_update_ceiling
    boundary = seed_coherence.capture_update_boundary
    instant = seed_coherence.capture_observation_instant
    elapsed = [0.0]
    def advance(seconds):
        elapsed[0] += seconds
    network_clock = SimpleNamespace(monotonic=lambda: elapsed[0], sleep=advance,
                                   time=lambda: provider.step.at.timestamp() + elapsed[0])
    with ExitStack() as stack:
        cache = stack.enter_context(tempfile.TemporaryDirectory(prefix="replay-source-cache-"))
        stack.enter_context(patch.object(acquisition_work, "cache_root", lambda: Path(cache)))
        stack.enter_context(patch.object(acquisition_work, "time", network_clock))
        stack.enter_context(patch.object(provider_budget, "time", network_clock))
        stack.enter_context(patch.object(snapshot_source, "archive_tables",
            SimpleNamespace(fetch_table=captured_rows, TICKERS=archive_tables.TICKERS)))
        stack.enter_context(patch.object(archive_tables, "require_capture",
            lambda: operational_source.current() or provider))
        stack.enter_context(patch.object(snapshot_export, "probe_snapshot", provider.snapshot))
        stack.enter_context(patch.object(snapshot_export, "download_snapshot", provider.read_snapshot))
        stack.enter_context(patch.object(snapshot_export, "_fetch_complete", exported))
        stack.enter_context(patch.object(snapshot_export, "require_actions_refresh", corroborate))
        stack.enter_context(patch.object(ingest, "_dt", clock_module))
        stack.enter_context(patch.object(seed_coherence, "capture_update_boundary",
                                        lambda: boundary(provider.step.at)))
        stack.enter_context(patch.object(seed_coherence, "capture_update_ceiling",
                                        lambda: ceiling(provider.step.at)))
        stack.enter_context(patch.object(seed_coherence, "capture_observation_instant",
                                        lambda: instant(provider.step.at)))
        stack.enter_context(patch.dict(os.environ, {
            "SENTINEL_PUBLICATION_RECEIPT_KEY": "synthetic-replay-receipt-key-" * 3,
        }))
        stack.enter_context(patch.object(identity, "require_feed_producer_identity",
            return_value={"schema": "sentinel.feed-producer/1", "git_commit": commit,
                          "runtime_image_digest": "sha256:" + "0" * 64,
                          "image_source_revision": commit}))
        yield
