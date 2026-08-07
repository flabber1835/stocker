"""The async/sync corpus bridge, against a real Postgres.

WHY A REAL DATABASE. The bridge's whole job is to make an async connection look
synchronous to a loader running in a worker thread, and its defect was about
WHEN rows arrive: it materialised the entire result set before returning. A fake
connection cannot express that — it hands over a list either way — which is why
the bug survived every unit test and was found by an OOM kill in production:
a 2021-2023 rehearsal died 16 minutes in at 4.1 GB RSS having built nothing.

These tests use a server-side cursor against real Postgres and assert both that
the bridge returns the right rows and that it does not buffer them all first.
"""
from __future__ import annotations

import asyncio
import importlib
import os
import sys

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

pytestmark = pytest.mark.asyncio

ROWS = 25_000


def _bridge():
    """Import bt-engine's bridge without leaving its `app` package loaded."""
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    saved = {k: v for k, v in sys.modules.items() if k == "app" or k.startswith("app.")}
    for k in saved:
        del sys.modules[k]
    sys.path.insert(0, os.path.join(root, "services", "bt-engine"))
    os.environ.setdefault("BT_DATABASE_URL",
                          "postgresql+asyncpg://test:test@localhost/test")
    try:
        return importlib.import_module("app.wealth_core_api")
    finally:
        sys.path.pop(0)
        for k in [k for k in list(sys.modules) if k == "app" or k.startswith("app.")]:
            del sys.modules[k]
        sys.modules.update(saved)


@pytest_asyncio.fixture
async def seeded(async_dsn: str):
    eng = create_async_engine(async_dsn, future=True)
    async with eng.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS bridge_probe"))
        await conn.execute(text(
            "CREATE TABLE bridge_probe (n INTEGER PRIMARY KEY, label TEXT)"))
        await conn.execute(text(
            "INSERT INTO bridge_probe SELECT g, 'row-' || g "
            "FROM generate_series(1, :n) g"), {"n": ROWS})
    try:
        yield eng
    finally:
        async with eng.begin() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS bridge_probe"))
        await eng.dispose()


async def _in_thread(eng, fn):
    """Drive the bridge exactly as `_load_corpus` does: the loader runs in a
    worker thread, each query marshals back onto the loop."""
    api = _bridge()
    loop = asyncio.get_running_loop()
    async with eng.connect() as aconn:
        conn = api._ThreadConn(aconn, loop)
        return await asyncio.to_thread(fn, api, conn)


async def test_every_row_arrives_exactly_once_and_in_order(seeded):
    def work(api, conn):
        rows = list(conn.execute(
            text("SELECT n, label FROM bridge_probe ORDER BY n")).mappings())
        return rows

    rows = await _in_thread(seeded, work)
    assert len(rows) == ROWS
    assert rows[0]["n"] == 1 and rows[-1]["n"] == ROWS
    assert [r["n"] for r in rows[:5]] == [1, 2, 3, 4, 5]
    assert rows[7]["label"] == "row-8"


async def test_rows_arrive_in_chunks_rather_than_all_at_once(seeded):
    """THE property the OOM was about, counted in ROUND TRIPS.

    The first version of this test asserted that iteration left `_buffer` empty
    — which is true of the materialising bridge too, since it yields from one
    big list without buffering. It passed under the defect. A test that cannot
    fail is worse than no test: it is the false confidence that let the original
    bug reach production.

    Counting fetches cannot be satisfied by a single big read: 25k rows at 1k
    per chunk is ~26 trips, and the old bridge made exactly two (everything,
    then empty).
    """
    def work(api, conn):
        api.FETCH_CHUNK = 1_000
        result = conn.execute(text("SELECT n, label FROM bridge_probe ORDER BY n"))
        calls = {"n": 0}
        inner = result._fetch_chunk

        def counting():
            calls["n"] += 1
            return inner()

        result._fetch_chunk = counting
        rows = list(result.mappings())
        return len(rows), calls["n"]

    n_rows, n_fetches = await _in_thread(seeded, work)
    assert n_rows == ROWS
    assert n_fetches >= ROWS // 1_000, (
        f"{n_fetches} server round trip(s) for {n_rows} rows at 1000/chunk — "
        f"the result was materialised, not streamed")


async def test_first_does_not_drain_the_table(seeded):
    """The coverage probe calls `first()` on an aggregate. It must cost one
    chunk, not the whole scan."""
    def work(api, conn):
        api.FETCH_CHUNK = 500
        result = conn.execute(
            text("SELECT n, label FROM bridge_probe ORDER BY n"))
        row = result.mappings().first()
        return row, len(result._buffer)

    row, buffered = await _in_thread(seeded, work)
    assert row["n"] == 1
    assert 0 < buffered <= 500, "first() pulled more than a single chunk"


async def test_first_then_iterate_does_not_lose_the_buffered_rows(seeded):
    """A subtle one: `first()` pulls a chunk, so a later iteration must replay
    it. Dropping it would silently skip the first N rows of the corpus — which
    would look like a shorter history rather than an error."""
    def work(api, conn):
        api.FETCH_CHUNK = 700
        result = conn.execute(
            text("SELECT n, label FROM bridge_probe ORDER BY n")).mappings()
        head = result.first()
        seen = [r["n"] for r in result]
        return head, seen

    head, seen = await _in_thread(seeded, work)
    assert head["n"] == 1
    assert len(seen) == ROWS
    assert seen[0] == 1 and seen[-1] == ROWS


async def test_an_empty_result_terminates_rather_than_looping(seeded):
    def work(api, conn):
        result = conn.execute(
            text("SELECT n, label FROM bridge_probe WHERE n < 0")).mappings()
        return result.first(), list(result)

    first, rows = await _in_thread(seeded, work)
    assert first is None and rows == []


async def test_a_parameterised_query_still_binds(seeded):
    def work(api, conn):
        return list(conn.execute(
            text("SELECT n FROM bridge_probe WHERE n BETWEEN :a AND :b ORDER BY n"),
            {"a": 10, "b": 12}).mappings())

    rows = await _in_thread(seeded, work)
    assert [r["n"] for r in rows] == [10, 11, 12]
