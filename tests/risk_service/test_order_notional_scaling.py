"""L1 — scale-aware per-order notional cap: effective cap =
max(MAX_ORDER_NOTIONAL, MAX_ORDER_PCT × account_value). Defuses the fixed-cap
scaling landmine (at equity > cap/position_weight every entry was rejected —
the system silently stopped rotating precisely because it grew) while keeping
absolute fat-finger protection for small accounts and the fail-closed behavior
when no DB is available."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import app.main as rs


class _ScriptEngine:
    """Engine returning a scripted queue of row-results, one per .execute()."""
    def __init__(self, results):
        self._results = list(results)

    def connect(self):
        eng = self

        class _Ctx:
            async def __aenter__(self_):
                conn = MagicMock()

                async def _exec(*a, **k):
                    res = MagicMock()
                    val = eng._results.pop(0) if eng._results else None
                    res.first.return_value = val
                    return res

                conn.execute = AsyncMock(side_effect=_exec)
                return conn

            async def __aexit__(self_, *a):
                return None
        return _Ctx()


def _req(notional):
    return rs.TradeCheckRequest(
        ticker="NVDA", action="entry", side="buy", qty=100, notional=notional,
        mode="immediate", trade_type="paper", sim_date=None,
    )


def _quiet_env(monkeypatch):
    monkeypatch.delenv("KILL_SWITCH", raising=False)
    monkeypatch.setenv("MAX_SYNC_AGE_HOURS", "0")
    monkeypatch.setenv("MAX_DATA_AGE_HOURS", "0")
    monkeypatch.setenv("MAX_DAILY_LOSS_PCT", "0")
    monkeypatch.setenv("MAX_POSITION_PCT", "1.0")
    monkeypatch.setenv("MAX_POSITIONS", "0")
    monkeypatch.delenv("MAX_CYCLE_BUY_NOTIONAL", raising=False)


def test_env_default_pct():
    assert rs._safety_env()["max_order_pct"] == 0.20


def test_under_absolute_cap_unaffected(monkeypatch):
    _quiet_env(monkeypatch)
    monkeypatch.setattr(rs, "engine", _ScriptEngine([]))
    approved, _r, rule, _ = asyncio.run(rs._decide(_req(8_000)))
    assert approved is True and rule == "ok"


def test_over_absolute_no_engine_fails_closed(monkeypatch):
    _quiet_env(monkeypatch)
    monkeypatch.setattr(rs, "engine", None)
    approved, reason, rule, _ = asyncio.run(rs._decide(_req(80_000)))
    assert approved is False and rule == "notional_limit"


def test_over_absolute_pct_disabled_rejects(monkeypatch):
    _quiet_env(monkeypatch)
    monkeypatch.setenv("MAX_ORDER_PCT", "0")
    monkeypatch.setattr(rs, "engine", _ScriptEngine([]))
    approved, _r, rule, _ = asyncio.run(rs._decide(_req(80_000)))
    assert approved is False and rule == "notional_limit"


def test_big_account_rescues_over_absolute_order(monkeypatch):
    """$80k entry on a $2M account: over the $50k absolute cap, but well inside
    20% × $2M = $400k → approved. The system keeps rotating after it grows."""
    _quiet_env(monkeypatch)
    monkeypatch.setattr(rs, "engine", _ScriptEngine([
        (2_000_000.0,),   # rescue: latest account_value
    ]))
    approved, reason, rule, _ = asyncio.run(rs._decide(_req(80_000)))
    assert approved is True and rule == "ok", (rule, reason)


def test_small_account_still_protected(monkeypatch):
    """$80k order on a $100k account: effective cap = max($50k, 20%×$100k=$20k)
    = $50k → rejected. Fat-finger protection intact at small scale."""
    _quiet_env(monkeypatch)
    monkeypatch.setattr(rs, "engine", _ScriptEngine([
        (100_000.0,),
    ]))
    approved, reason, rule, _ = asyncio.run(rs._decide(_req(80_000)))
    assert approved is False and rule == "notional_limit"
    assert "effective cap" in reason


def test_no_synced_account_falls_back_to_absolute(monkeypatch):
    _quiet_env(monkeypatch)
    monkeypatch.setattr(rs, "engine", _ScriptEngine([None]))  # no sync row
    approved, _r, rule, _ = asyncio.run(rs._decide(_req(80_000)))
    assert approved is False and rule == "notional_limit"
