"""FIX E — a CLOSE must not be rejected as notional_zero on a missing price.

_size_exit can produce notional = qty × 0 = 0 when the local display price is
absent. The risk-service's notional_zero guard previously rejected that BEFORE the
is_close exemption, so a de-risking exit was blocked by a missing display price.
The notional_zero guard is now buy-side only; closes (exit / sell_trim) are exempt
(they size qty-only at the broker). Entries/buy_adds still reject $0.
"""
import asyncio

import app.main as rs


def _req(action, side, notional):
    return rs.TradeCheckRequest(
        ticker="GOOG", action=action, side=side, qty=8, notional=notional,
        mode="immediate", trade_type="paper",
    )


def test_exit_with_zero_notional_not_rejected(monkeypatch):
    monkeypatch.setattr(rs, "engine", None)  # in-memory only path
    monkeypatch.delenv("KILL_SWITCH", raising=False)
    approved, _reason, rule, _env = asyncio.run(rs._decide(_req("exit", "sell", 0.0)))
    assert rule != "notional_zero"
    assert approved is True and rule == "ok"


def test_sell_trim_with_zero_notional_not_rejected(monkeypatch):
    monkeypatch.setattr(rs, "engine", None)
    monkeypatch.delenv("KILL_SWITCH", raising=False)
    approved, _reason, rule, _env = asyncio.run(rs._decide(_req("sell_trim", "sell", 0.0)))
    assert rule != "notional_zero"
    assert approved is True and rule == "ok"


def test_entry_with_zero_notional_still_rejected(monkeypatch):
    monkeypatch.setattr(rs, "engine", None)
    monkeypatch.delenv("KILL_SWITCH", raising=False)
    approved, _reason, rule, _env = asyncio.run(rs._decide(_req("entry", "buy", 0.0)))
    assert approved is False and rule == "notional_zero"


def test_buy_add_with_zero_notional_still_rejected(monkeypatch):
    monkeypatch.setattr(rs, "engine", None)
    monkeypatch.delenv("KILL_SWITCH", raising=False)
    approved, _reason, rule, _env = asyncio.run(rs._decide(_req("buy_add", "buy", 0.0)))
    assert approved is False and rule == "notional_zero"
