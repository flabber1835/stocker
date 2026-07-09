"""R1 (sim_date authenticity) + R2 (cycle buy-notional backstop) risk controls."""
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


def _req(action="entry", side="buy", sim_date=None, notional=2865.28):
    return rs.TradeCheckRequest(
        ticker="GOOG", action=action, side=side, qty=8, notional=notional,
        mode="immediate", trade_type="paper", sim_date=sim_date,
    )


# ── R1 ────────────────────────────────────────────────────────────────────────

def test_unknown_sim_date_rejected(monkeypatch):
    monkeypatch.delenv("KILL_SWITCH", raising=False)
    monkeypatch.setattr(rs, "engine", _ScriptEngine([None]))  # delta_runs lookup → no row
    approved, reason, rule, _ = asyncio.run(rs._decide(_req(sim_date="2099-01-01")))
    assert approved is False and rule == "invalid_sim_date"
    assert "2099-01-01" in reason


def test_null_sim_date_skips_validation(monkeypatch):
    # No sim_date → R1 does not run; the first DB control (sync staleness) does.
    monkeypatch.delenv("KILL_SWITCH", raising=False)
    monkeypatch.setattr(rs, "engine", _ScriptEngine([None]))  # sync lookup → no successful sync
    approved, _reason, rule, _ = asyncio.run(rs._decide(_req(sim_date=None)))
    assert rule != "invalid_sim_date"


def test_known_sim_date_passes_r1(monkeypatch):
    monkeypatch.delenv("KILL_SWITCH", raising=False)
    # [delta_runs row exists] then [sync lookup → none] → fails LATER at sync, not R1
    monkeypatch.setattr(rs, "engine", _ScriptEngine([(1,), None]))
    approved, _reason, rule, _ = asyncio.run(rs._decide(_req(sim_date="2026-07-02")))
    assert rule != "invalid_sim_date"


# ── R2 ────────────────────────────────────────────────────────────────────────

def test_cycle_buy_cap_env_default_disabled(monkeypatch):
    monkeypatch.delenv("MAX_CYCLE_BUY_NOTIONAL", raising=False)
    assert rs._safety_env()["max_cycle_buy_notional"] == 0.0


def test_cycle_buy_cap_blocks_when_exceeded(monkeypatch):
    monkeypatch.delenv("KILL_SWITCH", raising=False)
    monkeypatch.setenv("MAX_CYCLE_BUY_NOTIONAL", "10000")
    # Disable every OTHER DB control via env so only max_positions + R2 query — the
    # scripted queue is then just [projected_count, cycle_buy_sum].
    monkeypatch.setenv("MAX_SYNC_AGE_HOURS", "0")     # skip sync staleness
    monkeypatch.setenv("MAX_DATA_AGE_HOURS", "0")     # skip data staleness
    monkeypatch.setenv("MAX_DAILY_LOSS_PCT", "0")     # skip daily loss
    monkeypatch.setenv("MAX_POSITION_PCT", "1.0")     # skip position-pct (guard is <1.0)
    monkeypatch.setenv("MAX_POSITIONS", "0")          # skip max-positions (guard is >0)
    engine = _ScriptEngine([
        (9500.0,),      # R2: cycle buy notional so far (9500 + 2865 > 10000 → block)
    ])
    monkeypatch.setattr(rs, "engine", engine)
    approved, reason, rule, _ = asyncio.run(rs._decide(_req(action="entry", notional=2865.28)))
    assert approved is False and rule == "cycle_buy_notional_limit", (rule, reason)
    assert "exceeds cap" in reason
