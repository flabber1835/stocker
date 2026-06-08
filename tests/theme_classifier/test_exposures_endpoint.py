"""Regression test for the /exposures endpoint date-parameter bug.

The endpoint 500'd ("invalid input for query argument: 'str' ... toordinal") because
_latest_meta returns as_of_date as a STRING and the members query bound it into a
DATE column. That made every /exposures call fail once the table had data → the
dashboard showed "service unavailable". The fix selects the latest date via a
subquery (no string round-trip). This test runs the real endpoint against a mocked
engine and asserts: (1) it returns 200/members without raising, and (2) the members
query does NOT bind a date parameter (so the bug can't return).
"""
import asyncio
from datetime import date
from unittest.mock import patch

import app.main as svc


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class _FakeConn:
    def __init__(self, captured):
        self._captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self._captured.append((sql, params or {}))
        if "max(computed_at)" in sql:        # _latest_meta
            return _FakeResult([{
                "as_of": date(2026, 6, 8),
                "computed_at": __import__("datetime").datetime(2026, 6, 8, 0, 0,
                              tzinfo=__import__("datetime").timezone.utc),
                "n": 24,
            }])
        # members query
        return _FakeResult([
            {"ticker": "AVGO", "exposure": 0.97, "in_seed": True, "avg_dollar_vol": 5e8},
            {"ticker": "VRT", "exposure": 0.95, "in_seed": True, "avg_dollar_vol": 5e8},
        ])


class _FakeEngine:
    def __init__(self):
        self.captured = []

    def connect(self):
        return _FakeConn(self.captured)


def test_exposures_returns_members_and_binds_no_date_param():
    fake = _FakeEngine()
    with patch.object(svc, "engine", fake):
        res = asyncio.run(svc.exposures(theme="ai_infra", min=0.35))

    assert res["count"] == 2
    assert res["members"][0]["ticker"] == "AVGO"
    assert res["members"][0]["rank"] == 1

    # The members query must not bind a date (the bug). Find the SELECT that pulls
    # exposure rows and assert its params are only theme + min.
    member_calls = [(s, p) for s, p in fake.captured if "SELECT ticker, exposure" in s]
    assert member_calls, "members query was not executed"
    sql, params = member_calls[0]
    assert "max(as_of_date)" in sql, "members query should resolve the latest date via subquery"
    assert set(params.keys()) <= {"t", "m"}, f"members query must not bind a date param: {params}"


def test_exposures_never_filters_out_seeds():
    """Regression: a curated seed (e.g. NVDA) must appear even when its exposure is
    below the threshold — seeds are core members by curation, the threshold gates
    only discovered adjacents. Asserts the query includes the 'OR in_seed' exemption
    and pins seeds first."""
    fake = _FakeEngine()
    with patch.object(svc, "engine", fake):
        asyncio.run(svc.exposures(theme="ai_infra", min=0.35))
    sql = [s for s, _ in fake.captured if "SELECT ticker, exposure" in s][0]
    norm = " ".join(sql.split()).lower()
    assert "or in_seed" in norm, "seeds must be exempt from the exposure threshold (OR in_seed)"
    assert "order by in_seed desc" in norm, "core (seed) members must be pinned first"
