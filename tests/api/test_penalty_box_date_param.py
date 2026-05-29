"""
Regression test for the penalty-box date-parameter bug.

_load_penalty_box queries `vetter_penalty_box WHERE penalty_box_until >= :today`.
The column is a Postgres DATE, and asyncpg requires a real datetime.date object
for a DATE-typed parameter — it calls `.toordinal()` on the value when encoding,
which fails on a string:

    asyncpg.exceptions.DataError: invalid input for query argument $1:
    '2026-05-29' ('str' object has no attribute 'toordinal')

Passing date.today().isoformat() (a str) 500'd the /rankings/with-overlays
endpoint, which surfaced in the dashboard as a misleading "NO DATA" badge even
though rankings existed in the DB.

This test captures the params dict passed to conn.execute and asserts the
`today` bind value is a datetime.date, not a str.
"""
from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.main import _load_penalty_box


class _CapturingConn:
    """Minimal async conn stub that records the params dict of the last execute."""

    def __init__(self):
        self.captured_params = None

    async def execute(self, sql, params=None):
        self.captured_params = params
        result = MagicMock()
        result.mappings = MagicMock(return_value=[])  # no penalty-box rows
        return result


@pytest.mark.asyncio
async def test_load_penalty_box_passes_date_object_not_string():
    """The :today bind value must be a datetime.date — asyncpg rejects str for a DATE column."""
    conn = _CapturingConn()
    result = await _load_penalty_box(conn)

    assert result == {}, "no rows → empty dict"
    assert conn.captured_params is not None, "_load_penalty_box must execute a parameterized query"
    today = conn.captured_params["today"]
    assert isinstance(today, datetime.date), (
        f"penalty_box_until is a DATE column; asyncpg needs a datetime.date, "
        f"got {type(today).__name__}={today!r}. Passing .isoformat() 500s the endpoint."
    )
    # And specifically NOT a string (date is not a subclass trap — be explicit)
    assert not isinstance(today, str)
    assert today == datetime.date.today()
