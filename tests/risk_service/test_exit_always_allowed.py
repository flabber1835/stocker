import asyncio

import app.main as rs


class _BoomEngine:
    """Engine whose every connection attempt fails — simulates a total DB outage
    (or any safety-control DB error)."""
    def connect(self):
        raise RuntimeError("DB down")


def _req(action, side):
    return rs.TradeCheckRequest(
        ticker="GOOG", action=action, side=side, qty=8, notional=2865.28,
        mode="immediate", trade_type="paper",
    )


def test_exit_and_trim_always_allowed_on_db_outage(monkeypatch):
    # A close/trim must never be trapped by a system condition. With the DB
    # unreachable, exits/sell_trims are approved; entries/buy_adds fail closed.
    monkeypatch.setattr(rs, "engine", _BoomEngine())
    monkeypatch.delenv("KILL_SWITCH", raising=False)
    for action, side in (("exit", "sell"), ("sell_trim", "sell")):
        approved, _reason, rule, _env = asyncio.run(rs._decide(_req(action, side)))
        assert approved is True and rule == "ok", (action, rule)
    approved, _reason, rule, _env = asyncio.run(rs._decide(_req("entry", "buy")))
    # Per-control isolation: the entry fails CLOSED, and the rule names the SPECIFIC
    # control that could not be evaluated (the first DB control for an entry is
    # sync-staleness) instead of a generic 'control_unavailable' — diagnosable.
    assert approved is False and rule == "sync_staleness_unavailable"
    assert rule.endswith("_unavailable")


def test_kill_switch_still_blocks_exit(monkeypatch):
    # The one absolute halt — the kill switch — still stops everything, incl. exits.
    monkeypatch.setattr(rs, "engine", _BoomEngine())
    monkeypatch.setenv("KILL_SWITCH", "true")
    approved, _reason, rule, _env = asyncio.run(rs._decide(_req("exit", "sell")))
    assert approved is False and rule == "kill_switch"
