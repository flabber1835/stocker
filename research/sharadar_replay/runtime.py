"""Explicit test-only transport, clock and producer seams."""
from __future__ import annotations

import datetime as dt
import os
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from .provider import Provider


@contextmanager
def simulated_runtime(provider: Provider, *, commit: str):
    from sentinel import identity
    from sentinel.feed import ingest, seed_coherence

    class ClockDateTime(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            if provider.step is None:
                raise RuntimeError("clock has no current event")
            instant = provider.step.at
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

    client_type = httpx.Client

    def client(*args, **kwargs):
        if "transport" in kwargs:
            raise RuntimeError("nested transport override is forbidden")
        kwargs["transport"] = httpx.MockTransport(provider)
        kwargs["trust_env"] = False
        return client_type(*args, **kwargs)

    clock_module = SimpleNamespace(datetime=ClockDateTime, date=dt.date,
                                   timedelta=dt.timedelta, timezone=dt.timezone)
    ceiling = seed_coherence.capture_update_ceiling
    instant = seed_coherence.capture_observation_instant
    with ExitStack() as stack:
        stack.enter_context(patch.object(httpx, "Client", client))
        stack.enter_context(patch.object(ingest, "_dt", clock_module))
        stack.enter_context(patch.object(seed_coherence, "capture_update_ceiling",
                                        lambda: ceiling(provider.step.at)))
        stack.enter_context(patch.object(seed_coherence, "capture_observation_instant",
                                        lambda: instant(provider.step.at)))
        stack.enter_context(patch.dict(os.environ, {
            "SHARADAR_API_KEY": "synthetic-provider-only",
            "SENTINEL_PUBLICATION_RECEIPT_KEY": "synthetic-replay-receipt-key-" * 3,
        }))
        stack.enter_context(patch.object(identity, "require_feed_producer_identity",
            return_value={"schema": "sentinel.feed-producer/1", "git_commit": commit,
                          "runtime_image_digest": "sha256:" + "0" * 64,
                          "image_source_revision": commit}))
        yield
