"""Field-regression repair queue (layer 4 of the PBR armor).

Detect: a fetch that nulls a previously-populated fundamentals field enqueues
the ticker. Repair: next run force-refreshes queued tickers past the weekly skip
window, with a capped attempt count. Resolve: only when the QUEUED fields come
back non-null (not merely "no new regressions" — after the degraded row becomes
the previous row, a still-null field emits no new signal, so the weaker check
would self-resolve wrongly).
"""
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.repair_queue import (
    REGRESSION_FIELDS,
    detect_field_regressions,
    load_repair_set,
    record_check,
    regression_resolved,
)


# ── pure detection ────────────────────────────────────────────────────────────

def test_pbr_scenario_detected():
    prev = {"roe": 0.256, "total_assets": 238621205000.0, "gross_profit": 235890999000.0,
            "debt_to_equity": None}
    new = {"roe": 0.256, "total_assets": None, "gross_profit": 235890999000.0,
           "debt_to_equity": None}
    assert detect_field_regressions(prev, new) == ["total_assets"]


def test_always_null_field_is_not_a_regression():
    # PBR's debt_to_equity was null in EVERY row — sparse coverage, not a blip.
    prev = {"debt_to_equity": None}
    new = {"debt_to_equity": None}
    assert detect_field_regressions(prev, new) == []


def test_first_ever_fetch_never_regresses():
    assert detect_field_regressions(None, {"roe": None}) == []
    assert detect_field_regressions({}, {"roe": None}) == []


def test_value_change_is_not_a_regression():
    prev = {"roe": 0.10}
    new = {"roe": 0.99}
    assert detect_field_regressions(prev, new) == []


def test_multiple_regressions_listed():
    prev = {"roe": 0.1, "market_cap": 1e9, "pe_ratio": 12.0}
    new = {"roe": None, "market_cap": None, "pe_ratio": 12.0}
    assert set(detect_field_regressions(prev, new)) == {"roe", "market_cap"}


def test_regression_fields_cover_factor_inputs():
    for f in ("roe", "debt_to_equity", "gross_profit", "total_assets",
              "market_cap", "shares_outstanding"):
        assert f in REGRESSION_FIELDS


# ── pure resolution ───────────────────────────────────────────────────────────

def test_resolution_requires_every_queued_field():
    assert regression_resolved(["total_assets"], {"total_assets": 238.0}) is True
    assert regression_resolved(["total_assets", "roe"], {"total_assets": 238.0, "roe": None}) is False
    assert regression_resolved([], {"anything": None}) is True  # vacuous


def test_still_null_after_requeue_is_not_resolved():
    # The trap: once the degraded row is the previous row, null→null emits no NEW
    # regression — resolution must therefore check the queued list, not re-detection.
    assert detect_field_regressions({"total_assets": None}, {"total_assets": None}) == []
    assert regression_resolved(["total_assets"], {"total_assets": None}) is False


# ── record_check SQL behavior (mock session) ─────────────────────────────────

def _session():
    s = MagicMock()
    s.calls = []

    async def _exec(stmt, params=None):
        s.calls.append((str(stmt), params))
        res = MagicMock()
        res.fetchone.return_value = s._open_row
        return res

    s.execute = AsyncMock(side_effect=_exec)
    s._open_row = None
    return s


@pytest.mark.asyncio
async def test_record_check_enqueues_on_regression():
    s = _session()
    out = await record_check(s, "PBR", {"total_assets": 238.0}, {"total_assets": None})
    assert out == "enqueued"
    sql, params = s.calls[0]
    assert "INSERT INTO fundamentals_repair_queue" in sql
    assert "resolved_at = NULL" in sql
    assert json.loads(params["rf"]) == ["total_assets"]
    # a regression on a previously-resolved entry is a NEW incident → counters reset
    assert "THEN 0 ELSE fundamentals_repair_queue.attempts" in sql


@pytest.mark.asyncio
async def test_record_check_resolves_open_entry():
    s = _session()
    s._open_row = (["total_assets"],)   # open queue row with the queued fields
    out = await record_check(s, "PBR", {"total_assets": 238.0}, {"total_assets": 238.0})
    assert out == "resolved"
    assert any("SET resolved_at = NOW()" in sql for sql, _ in s.calls)


@pytest.mark.asyncio
async def test_record_check_keeps_open_when_still_null():
    s = _session()
    s._open_row = (["total_assets"],)
    # degraded row is now the prev row → no new regression, still null → stays open
    out = await record_check(s, "PBR", {"total_assets": None}, {"total_assets": None})
    assert out is None
    assert not any("resolved_at = NOW()" in sql for sql, _ in s.calls)


@pytest.mark.asyncio
async def test_record_check_noop_without_queue_entry():
    s = _session()
    out = await record_check(s, "AAPL", {"roe": 0.3}, {"roe": 0.31})
    assert out is None
    assert not any("INSERT INTO fundamentals_repair_queue" in sql for sql, _ in s.calls)


@pytest.mark.asyncio
async def test_load_repair_set_filters_cap_and_resolved():
    eng = MagicMock()
    conn = MagicMock()
    res = MagicMock()
    res.fetchall.return_value = [MagicMock(ticker="PBR"), MagicMock(ticker="PBR-A")]
    conn.execute = AsyncMock(return_value=res)
    eng.connect.return_value.__aenter__ = AsyncMock(return_value=conn)
    eng.connect.return_value.__aexit__ = AsyncMock(return_value=None)
    out = await load_repair_set(eng, max_attempts=3)
    assert out == {"PBR", "PBR-A"}
    sql = str(conn.execute.call_args.args[0])
    assert "resolved_at IS NULL" in sql and "attempts < :cap" in sql


# ── wiring contracts (main.py) ────────────────────────────────────────────────

def test_fetch_paths_bypass_skip_window_for_repair_set():
    import inspect
    import app.main as m
    src = inspect.getsource(m)
    # both fetch paths must consult the repair set BEFORE the weekly skip window
    assert src.count("ticker not in repair_set and _should_skip_fundamentals") == 2
    assert "load_repair_set(engine, FUND_REPAIR_MAX_ATTEMPTS)" in src
    assert src.count("bump_attempts(engine, repair_set)") == 2
    # detection hooks the single upsert used by every caller
    assert "record_check(" in inspect.getsource(m._upsert_fundamentals)


def test_attempt_cap_default():
    import app.main as m
    assert m.FUND_REPAIR_MAX_ATTEMPTS == 3
