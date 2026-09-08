"""Falsifiers for the corrected Wealth Core slot-funding invariant."""
from __future__ import annotations

from copy import deepcopy

import pytest

from stock_strategy_shared.wealth_core.adapter import step_session
from stock_strategy_shared.wealth_core.engine import (
    Operation,
    Reason,
    SecurityBar,
    WealthCoreConfig,
    decide,
    whole_share_target,
    whole_shares,
)
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.marks import Mark, MarkStatus
from stock_strategy_shared.wealth_core.prices import DailyBar
from stock_strategy_shared.wealth_core.state import PortfolioState

SID, VER = "stocker_wealth_core_v1", 1


def rising(n=127):
    return [100.0 + i for i in range(n)]


def sb(sec="S1"):
    return SecurityBar(sec, f"T{sec[1:]}", f"I{sec[1:]}", rising())


def marks(**prices):
    return {sec: Mark(sec, MarkStatus.CURRENT, raw_mark_close=px)
            for sec, px in prices.items()}


def daily(sec="S1", session="d0", *, open_=100.0, mark=100.0,
          signal=100.0, tradeable=True):
    return DailyBar(
        security_id=sec, ticker=f"T{sec[1:]}", issuer_id=f"I{sec[1:]}",
        session=session, signal_close_split_adj_div_unadj=signal,
        raw_open=open_, raw_mark_close=mark, tradeable=tradeable,
        split_ratio=1.0, dividend_per_share=0.0,
        unresolved_corporate_action=False)


def decision(st, *, cfg=None, price=100.0, bars=None, noncash_assets=0.0):
    cfg = cfg or WealthCoreConfig(n_slots=len(st.slots))
    bars = bars or [sb("S1")]
    return decide(
        session="d0", state=st, bars=bars,
        marks=marks(**{b.security_id: price for b in bars}), cfg=cfg,
        strategy_id=SID, strategy_version=VER,
        noncash_assets=noncash_assets)


def queue_one(*, cash, cfg, price=100.0):
    st = PortfolioState.fresh(cash, n_slots=1)
    st.initialized = True
    pending = []
    result = step_session(
        session="d0", state=st,
        bars=[daily("S1", "d0", open_=price, mark=price, signal=226.0)],
        pending=pending, ledger=Ledger(), last_known={}, cfg=cfg,
        strategy_id=SID, strategy_version=VER,
        security_bars=[sb("S1")])
    assert len(pending) == 1
    assert result.decision is not None
    return st, pending


def test_whole_shares_is_full_target_or_zero_never_cash_clipped():
    cfg = WealthCoreConfig()
    shares, required = whole_share_target(100_000.0, 100.0, cfg)
    assert shares == 39
    assert required == pytest.approx(3_903.9)
    assert whole_shares(100_000.0, 100.0, required, cfg) == 39
    assert whole_shares(100_000.0, 100.0, 500.0, cfg) == 0


def test_microscopic_cash_cannot_claim_a_slot_against_large_equity():
    st = PortfolioState.fresh(28.19, n_slots=1)
    st.initialized = True
    d = decision(st, price=23.07, noncash_assets=1_000_000.0)

    assert not [o for o in d.operations
                if o.operation is Operation.OPEN_SLOT_POSITION]
    assert st.slots[0].reserved_for is None
    assert st.reserved_entry_cash_total() == 0.0
    rejected = [r for r in d.admission_rejections
                if r["reason"] == Reason.REJECT_INSUFFICIENT_CASH.value]
    assert rejected
    assert rejected[0]["uncommitted_cash"] == pytest.approx(28.19)
    assert rejected[0]["required_cash"] > 39_000.0


def test_funded_admission_reserves_slot_and_exact_whole_share_notional():
    cfg = WealthCoreConfig(n_slots=1)
    st = PortfolioState.fresh(100_000.0, n_slots=1)
    st.initialized = True
    d = decision(st, cfg=cfg, price=100.0)
    opens = [o for o in d.operations
             if o.operation is Operation.OPEN_SLOT_POSITION]
    assert len(opens) == 1 and opens[0].shares == 39
    assert st.cash == 100_000.0, "reservation is a claim, not an early fill"
    assert st.slots[0].reserved_cash == pytest.approx(3_903.9)
    assert st.reserved_entry_cash_total() == pytest.approx(3_903.9)
    assert st.uncommitted_cash() == pytest.approx(96_096.1)
    assert opens[0].detail["reserved_cash"] == pytest.approx(3_903.9)


def test_initial_construction_cannot_promise_the_same_cash_twice():
    # Each target wants 5 shares * $100.10 = $500.50.  One fits; two do not.
    cfg = WealthCoreConfig(entry_weight=0.51, n_slots=2)
    st = PortfolioState.fresh(1_000.0, n_slots=2)
    d = decision(st, cfg=cfg, price=100.0, bars=[sb("S1"), sb("S2")])
    opens = [o for o in d.operations
             if o.operation is Operation.OPEN_SLOT_POSITION]
    assert len(opens) == 1
    assert st.reserved_entry_cash_total() == pytest.approx(500.5)
    assert st.uncommitted_cash() == pytest.approx(499.5)
    assert any(r["reason"] == Reason.REJECT_INSUFFICIENT_CASH.value
               for r in d.admission_rejections)


def test_runtime_reservation_boundary_refuses_cash_overcommit():
    st = PortfolioState.fresh(1_000.0, n_slots=2)
    st.reserve_slot(0, "S1", "T1", "I1", 600.0)
    with pytest.raises(ValueError, match="exceeds uncommitted cash"):
        st.reserve_slot(1, "S2", "T2", "I2", 500.0)


def test_restart_preserves_positive_cash_claim_and_refuses_legacy_empty_claim():
    st = PortfolioState.fresh(100_000.0, n_slots=1)
    st.initialized = True
    decision(st, cfg=WealthCoreConfig(n_slots=1), price=100.0)
    raw = st.to_dict()
    assert raw["slots"]["0"]["reserved_cash"] == pytest.approx(3_903.9)

    restored = PortfolioState.from_dict(deepcopy(raw))
    assert restored.state_hash() == st.state_hash()
    assert restored.slots[0].reserved_cash == pytest.approx(3_903.9)

    missing = deepcopy(raw)
    missing["slots"]["0"].pop("reserved_cash")
    with pytest.raises(ValueError, match="positive cash budget"):
        PortfolioState.from_dict(missing)


def test_restore_refuses_aggregate_reserved_cash_above_account_cash():
    raw = PortfolioState.fresh(1_000.0, n_slots=2).to_dict()
    for i, amount in ((0, 600.0), (1, 500.0)):
        raw["slots"][str(i)].update({
            "reserved_for": f"S{i}", "reserved_ticker": f"T{i}",
            "reserved_issuer": f"I{i}", "reserved_cash": amount})
    with pytest.raises(ValueError, match="reserve more entry cash"):
        PortfolioState.from_dict(raw)


def test_unreserved_legacy_slot_may_omit_zero_reserved_cash_without_hash_movement():
    st = PortfolioState.fresh(1_000.0, n_slots=1)
    raw = st.to_dict()
    assert "reserved_cash" not in raw["slots"]["0"]
    restored = PortfolioState.from_dict(deepcopy(raw))
    assert restored.state_hash() == st.state_hash()


def test_upward_gap_clips_inside_reserved_budget_not_later_account_cash():
    cfg = WealthCoreConfig(n_slots=1)
    st, pending = queue_one(cash=100_000.0, cfg=cfg, price=100.0)
    reserved = st.slots[0].reserved_cash
    assert reserved == pytest.approx(3_903.9)

    result = step_session(
        session="d1", state=st,
        bars=[daily("S1", "d1", open_=110.0, mark=110.0, signal=226.0)],
        pending=pending, ledger=Ledger(), last_known={}, cfg=cfg,
        strategy_id=SID, strategy_version=VER, security_bars=[])

    expected = int(reserved // (110.0 * 1.001))
    assert expected == 35
    assert result.fills[0]["shares"] == expected
    assert st.episodes[0].current_shares == expected
    assert st.cash == pytest.approx(100_000.0 - expected * 110.0 * 1.001)
    assert st.slots[0].reserved_cash == 0.0
    assert not pending
    partial = [r for r in result.cancelled if r["reason"] == "PARTIAL_AT_OPEN"]
    assert partial and partial[0]["reserved_cash"] == pytest.approx(reserved)


def test_nontradeable_open_keeps_pending_order_and_cash_reservation():
    cfg = WealthCoreConfig(n_slots=1)
    st, pending = queue_one(cash=100_000.0, cfg=cfg, price=100.0)
    reserved = st.slots[0].reserved_cash

    step_session(
        session="d1", state=st,
        bars=[daily("S1", "d1", open_=None, mark=101.0,
                    signal=226.0, tradeable=False)],
        pending=pending, ledger=Ledger(), last_known={}, cfg=cfg,
        strategy_id=SID, strategy_version=VER, security_bars=[])

    assert len(pending) == 1 and pending[0].sessions_waiting == 1
    assert st.slots[0].reserved_for == "S1"
    assert st.slots[0].reserved_cash == pytest.approx(reserved)
    assert st.cash == 100_000.0




def test_restart_mid_pending_entry_preserves_the_reserved_budget():
    cfg = WealthCoreConfig(n_slots=1)
    st, pending = queue_one(cash=100_000.0, cfg=cfg, price=100.0)
    ledger = Ledger()
    last_known = {}

    # The first executable opportunity is absent, so both claims must remain.
    step_session(
        session="d1", state=st,
        bars=[daily("S1", "d1", open_=None, mark=101.0,
                    signal=226.0, tradeable=False)],
        pending=pending, ledger=ledger, last_known=last_known, cfg=cfg,
        strategy_id=SID, strategy_version=VER, security_bars=[])
    assert len(pending) == 1
    budget = st.slots[0].reserved_cash
    assert budget > 0

    restored = PortfolioState.from_dict(deepcopy(st.to_dict()))
    restored_pending = [type(p).from_dict(deepcopy(p.to_dict())) for p in pending]
    restored_ledger = Ledger.from_dict(deepcopy(ledger.to_dict()))
    restored_last_known = deepcopy(last_known)
    assert restored.slots[0].reserved_cash == pytest.approx(budget)

    next_bar = [daily("S1", "d2", open_=105.0, mark=105.0, signal=226.0)]
    clean = step_session(
        session="d2", state=st, bars=next_bar, pending=pending,
        ledger=ledger, last_known=last_known, cfg=cfg,
        strategy_id=SID, strategy_version=VER, security_bars=[])
    restarted = step_session(
        session="d2", state=restored, bars=next_bar,
        pending=restored_pending, ledger=restored_ledger,
        last_known=restored_last_known, cfg=cfg,
        strategy_id=SID, strategy_version=VER, security_bars=[])

    assert clean.fills == restarted.fills
    assert st.to_dict() == restored.to_dict()
    assert ledger.to_dict() == restored_ledger.to_dict()
    assert pending == restored_pending == []


def test_pending_open_without_its_cash_claim_is_cancelled_fail_closed():
    cfg = WealthCoreConfig(n_slots=1)
    st, pending = queue_one(cash=100_000.0, cfg=cfg, price=100.0)
    # Simulate queue/state corruption at a cross-process boundary.  The order
    # must not be allowed to reach into otherwise free account cash.
    st.slots[0].release_reservation()
    result = step_session(
        session="d1", state=st,
        bars=[daily("S1", "d1", open_=100.0, mark=100.0, signal=226.0)],
        pending=pending, ledger=Ledger(), last_known={}, cfg=cfg,
        strategy_id=SID, strategy_version=VER, security_bars=[])
    assert not result.fills
    assert pending == []
    rows = [r for r in result.cancelled
            if r["reason"] == "MISSING_CASH_RESERVATION"]
    assert rows and rows[0]["reservation_released"] is False


def test_gap_beyond_reserved_budget_cancels_even_when_account_has_cash():
    cfg = WealthCoreConfig(n_slots=1)
    # 4% of $3,000 = $120 -> one $100.10 share is the complete target.
    st, pending = queue_one(cash=3_000.0, cfg=cfg, price=100.0)
    assert pending[0].shares == 1
    assert st.slots[0].reserved_cash == pytest.approx(100.1)

    result = step_session(
        session="d1", state=st,
        bars=[daily("S1", "d1", open_=200.0, mark=200.0, signal=226.0)],
        pending=pending, ledger=Ledger(), last_known={}, cfg=cfg,
        strategy_id=SID, strategy_version=VER, security_bars=[])

    assert not result.fills
    assert not pending
    assert 0 not in st.episodes
    assert st.cash == 3_000.0
    assert st.slots[0].reserved_for is None
    assert st.slots[0].reserved_cash == 0.0
    rows = [r for r in result.cancelled if r["reason"] == "UNAFFORDABLE_AT_OPEN"]
    assert rows and rows[0]["reservation_released"] is True
    assert rows[0]["reserved_cash"] == pytest.approx(100.1)
