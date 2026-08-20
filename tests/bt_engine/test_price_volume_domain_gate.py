from __future__ import annotations

import asyncio
import datetime as dt

import pytest

from app import jobs_busy


class _Result:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _Conn:
    def __init__(self, rows):
        self.rows = list(rows)
        self.statements = []

    async def execute(self, statement, params=None):
        self.statements.append((str(statement), params))
        if not self.rows:
            raise AssertionError("unexpected database query")
        return _Result(self.rows.pop(0))


def test_semantic_epoch_gate_accepts_proven_singleton():
    conn = _Conn([("sharadar-raw-volume-v1", True, "complete migration")])
    asyncio.run(jobs_busy._require_price_volume_domain(conn))
    assert "bt_price_volume_domain_state" in conn.statements[0][0]


def test_semantic_epoch_gate_refuses_unproven_legacy_corpus():
    conn = _Conn([("sharadar-raw-volume-v1", False,
                   "legacy populated corpus requires volume-domain migration")])
    with pytest.raises(jobs_busy.CorpusGenerationUnavailable,
                       match="not proven for this READY corpus"):
        asyncio.run(jobs_busy._require_price_volume_domain(conn))


def test_semantic_epoch_gate_refuses_missing_singleton():
    conn = _Conn([None])
    with pytest.raises(jobs_busy.CorpusGenerationUnavailable,
                       match="no singleton authority row"):
        asyncio.run(jobs_busy._require_price_volume_domain(conn))


def test_ready_generation_cannot_bypass_unproven_volume_epoch():
    conn = _Conn([
        ("550e8400-e29b-41d4-a716-446655440000", "READY", "sharadar",
         dt.datetime(2026, 8, 19, tzinfo=dt.timezone.utc), "complete"),
        ("sharadar-raw-volume-v1", False, "invalidated by old writer"),
    ])
    with pytest.raises(jobs_busy.CorpusGenerationUnavailable,
                       match="not proven for this READY corpus"):
        asyncio.run(jobs_busy.load_ready_data_generation(conn))
    assert len(conn.statements) == 2


def test_ready_generation_passes_after_complete_post_fix_rewrite():
    conn = _Conn([
        ("550e8400-e29b-41d4-a716-446655440000", "READY", "sharadar",
         dt.datetime(2026, 8, 19, tzinfo=dt.timezone.utc), "complete"),
        ("sharadar-raw-volume-v1", True, "complete migration"),
    ])
    generation = asyncio.run(jobs_busy.load_ready_data_generation(conn))
    assert generation.status == "READY"
    assert generation.source_mode == "sharadar"
