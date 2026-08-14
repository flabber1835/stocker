"""Falsifiers for bt-data's one-generation mutation boundary."""
from __future__ import annotations

import asyncio
import inspect

import pytest
from fastapi import HTTPException

from app import main as bt_main
from app import sharadar_client


class _PayloadResponse:
    def __init__(self, cursor: str | None):
        self._cursor = cursor

    def json(self):
        return {
            "datatable": {
                "columns": [{"name": "ticker"}],
                "data": [["AAA"]],
            },
            "meta": {"next_cursor_id": self._cursor},
        }


def test_price_restatement_replaces_complete_ohlcv_row():
    src = inspect.getsource(bt_main._upsert_prices)
    for column in ("open", "high", "low", "close", "adjusted_close",
                   "close_unadjusted", "volume"):
        assert f"{column}=EXCLUDED.{column}" in src


def test_reversed_range_is_refused_before_reservation():
    with pytest.raises(HTTPException) as exc:
        bt_main._validated_range("2026-08-12", "2026-08-11")
    assert exc.value.status_code == 400
    with pytest.raises(ValueError):
        bt_main.year_chunks("2026-08-12", "2026-08-11")


def test_topup_frontier_excludes_configured_benchmarks():
    sql, params = bt_main._equity_frontier_sql()
    assert "MAX(date)" in sql and "NOT IN" in sql
    assert "SPY" in params.values()


def test_every_mutation_endpoint_uses_the_database_generation_gate():
    for endpoint in (
        bt_main.start_backfill,
        bt_main.start_fetch_benchmarks,
        bt_main.start_topup,
        bt_main.start_fundamentals_backfill,
        bt_main.start_actions_backfill,
        bt_main.start_universe_backfill,
        bt_main.start_price_backfill,
    ):
        assert "_schedule_mutation" in inspect.getsource(endpoint), endpoint.__name__


def test_the_whole_background_job_owns_one_publish_transition():
    src = inspect.getsource(bt_main._schedule_mutation)
    assert "_reserve_corpus_writer" in src
    assert "_run_reserved_generation" in src
    assert "background_tasks.add_task" in src
    assert not hasattr(bt_main, "_bump_data_version")
    for operation in (bt_main._run_backfill, bt_main._load_actions,
                      bt_main._load_benchmarks, bt_main._load_fundamentals,
                      bt_main._load_universe, bt_main._run_price_stage):
        assert "_publish_ready" not in inspect.getsource(operation)


def test_mode_mismatch_is_checked_before_publishing_marker_or_operation():
    src = inspect.getsource(bt_main._reserve_corpus_writer)
    mismatch = src.index("row.source_mode != mode")
    publishing = src.index("status='PUBLISHING'")
    assert mismatch < publishing


def test_unbound_populated_corpus_is_not_implicitly_claimed():
    src = inspect.getsource(bt_main._reserve_corpus_writer)
    population_check = src.index("row.source_mode is None")
    publishing = src.index("status='PUBLISHING'")
    assert "_CORPUS_POPULATED_SQL" in src
    assert population_check < publishing


def test_failure_leaves_publishing_unreadable():
    assert "status='PUBLISHING'" in inspect.getsource(
        bt_main._record_incomplete_generation)
    assert "status='READY'" not in inspect.getsource(
        bt_main._record_incomplete_generation)


def test_narrow_sf1_fetch_loads_prior_context():
    src = inspect.getsource(bt_main._load_fundamentals)
    assert "_load_prior_fundamental_context" in src
    assert "history[i - 4]" in src


def test_earnings_conflict_key_keeps_reported_date():
    src = inspect.getsource(bt_main._upsert_bt_earnings)
    assert "ON CONFLICT (ticker, fiscal_date_ending, reported_date)" in src
    assert "LEAST(" not in src


def test_repeated_vendor_cursor_is_refused(monkeypatch):
    responses = iter([_PayloadResponse("repeat"), _PayloadResponse("repeat")])

    async def fake_get(*args, **kwargs):
        return next(responses)

    monkeypatch.setattr(sharadar_client, "fetching_enabled", lambda: True)
    monkeypatch.setattr(sharadar_client, "is_mock", lambda: False)
    monkeypatch.setattr(sharadar_client, "_get_with_retry", fake_get)

    async def collect():
        return [row async for row in sharadar_client.fetch_table("SEP")]

    with pytest.raises(RuntimeError, match="repeated cursor"):
        asyncio.run(collect())


def test_vendor_page_cap_is_refused_while_more_pages_exist(monkeypatch):
    async def fake_get(*args, **kwargs):
        return _PayloadResponse("more")

    monkeypatch.setattr(sharadar_client, "fetching_enabled", lambda: True)
    monkeypatch.setattr(sharadar_client, "is_mock", lambda: False)
    monkeypatch.setattr(sharadar_client, "_get_with_retry", fake_get)
    monkeypatch.setattr(sharadar_client, "FETCH_PAGE_CAP", 1)

    async def collect():
        return [row async for row in sharadar_client.fetch_table("SEP")]

    with pytest.raises(RuntimeError, match="exceeded 1 pages"):
        asyncio.run(collect())


def test_generation_order_on_a_failure(monkeypatch):
    events: list[str] = []

    class Conn:
        async def execute(self, *args, **kwargs):
            events.append("record_incomplete")
        def in_transaction(self):
            return False
        async def commit(self):
            pass

    async def publish(conn, note):
        events.append("ready")

    async def release(conn):
        events.append("release")

    monkeypatch.setattr(bt_main, "_publish_ready", publish)
    monkeypatch.setattr(bt_main, "_release_corpus_writer", release)

    async def fail():
        events.append("mutate")
        raise RuntimeError("crash")

    with pytest.raises(RuntimeError):
        asyncio.run(bt_main._run_reserved_generation(Conn(), fail, "test"))
    assert events == ["mutate", "record_incomplete", "release"]
