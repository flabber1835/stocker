#!/usr/bin/env python3
"""Apply the pre-registered Wealth Core slot-funding correction.

This script exists only to make the branch mutation exact and reviewable.  It
refuses if any source anchor moved.  No performance result is read here.
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: str, old: str, new: str) -> None:
    p = ROOT / path
    text = p.read_text()
    n = text.count(old)
    if n != 1:
        raise RuntimeError(f"{path}: expected exactly one patch anchor, found {n}")
    p.write_text(text.replace(old, new, 1))


state_path = ROOT / "shared/stock_strategy_shared/wealth_core/state.py"
if "reserved_cash: float = 0.0" in state_path.read_text():
    print("slot-funding correction already applied; nothing to patch")
    raise SystemExit(0)

# ---------------------------------------------------------------------------
# Persistent state: a reservation owns both a slot and a cash budget.
# ---------------------------------------------------------------------------
replace_once(
    "shared/stock_strategy_shared/wealth_core/state.py",
    "    reserved_issuer: str | None = None\n",
    "    reserved_issuer: str | None = None\n"
    "    # Dollars committed to this still-unfilled entry.  Cash remains in\n"
    "    # `PortfolioState.cash` until execution, so this separate claim is what\n"
    "    # prevents another free slot from promising the same dollars.\n"
    "    reserved_cash: float = 0.0\n",
)
replace_once(
    "shared/stock_strategy_shared/wealth_core/state.py",
    "    def reserve(self, security_id: str, ticker: str, issuer_id: str) -> None:\n"
    "        self.reserved_for = security_id\n"
    "        self.reserved_ticker = ticker\n"
    "        self.reserved_issuer = issuer_id\n\n"
    "    def release_reservation(self) -> None:\n"
    "        self.reserved_for = self.reserved_ticker = self.reserved_issuer = None\n",
    "    def reserve(self, security_id: str, ticker: str, issuer_id: str,\n"
    "                reserved_cash: float) -> None:\n"
    "        amount = float(reserved_cash)\n"
    "        if not math.isfinite(amount) or amount <= 0:\n"
    "            raise ValueError(\"entry reservation cash must be finite and positive\")\n"
    "        self.reserved_for = security_id\n"
    "        self.reserved_ticker = ticker\n"
    "        self.reserved_issuer = issuer_id\n"
    "        self.reserved_cash = amount\n\n"
    "    def release_reservation(self) -> None:\n"
    "        self.reserved_for = self.reserved_ticker = self.reserved_issuer = None\n"
    "        self.reserved_cash = 0.0\n",
)
replace_once(
    "shared/stock_strategy_shared/wealth_core/state.py",
    "    def reserved_tickers(self) -> set[str]:\n"
    "        return {s.reserved_ticker for s in self.slots.values() if s.reserved_ticker}\n\n"
    "    def reserve_slot(self, slot_id: int, security_id: str, ticker: str,\n"
    "                     issuer_id: str) -> None:\n"
    "        self.slots[slot_id].reserve(security_id, ticker, issuer_id)\n",
    "    def reserved_tickers(self) -> set[str]:\n"
    "        return {s.reserved_ticker for s in self.slots.values() if s.reserved_ticker}\n\n"
    "    def reserved_entry_cash_total(self) -> float:\n"
    "        \"\"\"Cash already promised to queued entry orders.\n\n"
    "        The dollars remain part of portfolio equity until a fill occurs, but\n"
    "        they are not available to finance a second admission.\n"
    "        \"\"\"\n"
    "        return float(sum(s.reserved_cash for s in self.slots.values()\n"
    "                         if s.reserved_for is not None))\n\n"
    "    def uncommitted_cash(self) -> float:\n"
    "        return float(self.cash) - self.reserved_entry_cash_total()\n\n"
    "    def reserve_slot(self, slot_id: int, security_id: str, ticker: str,\n"
    "                     issuer_id: str, reserved_cash: float) -> None:\n"
    "        amount = float(reserved_cash)\n"
    "        slot = self.slots[slot_id]\n"
    "        if not slot.ready:\n"
    "            raise ValueError(f\"slot {slot_id} is not ready for reservation\")\n"
    "        available = self.uncommitted_cash()\n"
    "        if amount > available:\n"
    "            raise ValueError(\n"
    "                f\"entry reservation {amount!r} exceeds uncommitted cash \"\n"
    "                f\"{available!r}\")\n"
    "        slot.reserve(security_id, ticker, issuer_id, amount)\n",
)
# Keep zero-valued new state out of the old serialization/hash representation.
replace_once(
    "shared/stock_strategy_shared/wealth_core/state.py",
    "def _episode_json(ep) -> dict[str, Any]:\n",
    "def _slot_json(slot) -> dict[str, Any]:\n"
    "    \"\"\"Serialise a slot without inventing zero-valued hash movement.\n\n"
    "    `reserved_cash` is economic state only while a reservation exists.  Old\n"
    "    unreserved states omitted the field entirely, so zero continues to omit\n"
    "    it; a positive cash claim is persisted and hashed.\n"
    "    \"\"\"\n"
    "    d = asdict(slot)\n"
    "    if d.get(\"reserved_cash\") == 0.0:\n"
    "        d.pop(\"reserved_cash\", None)\n"
    "    return d\n\n\n"
    "def _episode_json(ep) -> dict[str, Any]:\n",
)
replace_once(
    "shared/stock_strategy_shared/wealth_core/state.py",
    '            "slots": {str(k): asdict(v) for k, v in sorted(self.slots.items())},\n',
    '            "slots": {str(k): _slot_json(v) for k, v in sorted(self.slots.items())},\n',
)

# ---------------------------------------------------------------------------
# Restore boundary: reservations without a positive budget, or budgets larger
# than the account cash they claim, are corrupt state and must not be accepted.
# ---------------------------------------------------------------------------
replace_once(
    "shared/stock_strategy_shared/wealth_core/state_restore_validation.py",
    "    present = tuple(value is not None for value in reservation)\n"
    "    if any(present) and not all(present):\n",
    "    present = tuple(value is not None for value in reservation)\n"
    "    reserved_cash = _finite(\n"
    "        raw.get(\"reserved_cash\", 0.0),\n"
    "        \"slot %d reserved_cash\" % slot_id, non_negative=True)\n"
    "    if any(present) and not all(present):\n",
)
replace_once(
    "shared/stock_strategy_shared/wealth_core/state_restore_validation.py",
    "    if all(present):\n"
    "        _text(reservation[0], \"slot %d reserved_for\" % slot_id)\n"
    "        _text(reservation[1], \"slot %d reserved_ticker\" % slot_id)\n"
    "        _text(reservation[2], \"slot %d reserved_issuer\" % slot_id)\n\n"
    "    if occupied is not None and any(present):\n",
    "    if all(present):\n"
    "        _text(reservation[0], \"slot %d reserved_for\" % slot_id)\n"
    "        _text(reservation[1], \"slot %d reserved_ticker\" % slot_id)\n"
    "        _text(reservation[2], \"slot %d reserved_issuer\" % slot_id)\n"
    "        if reserved_cash <= 0:\n"
    "            _fail(\"slot %d reservation\" % slot_id,\n"
    "                  \"must carry a positive cash budget\")\n"
    "    elif reserved_cash != 0:\n"
    "        _fail(\"slot %d reserved_cash\" % slot_id,\n"
    "              \"must be zero when no entry is reserved\")\n\n"
    "    if occupied is not None and any(present):\n",
)
replace_once(
    "shared/stock_strategy_shared/wealth_core/state_restore_validation.py",
    '        "reserved_issuer": reservation[2],\n'
    "    }\n",
    '        "reserved_issuer": reservation[2],\n'
    '        "reserved_cash": reserved_cash,\n'
    "    }\n",
)
replace_once(
    "shared/stock_strategy_shared/wealth_core/state_restore_validation.py",
    "    overlap = held.intersection(reserved)\n"
    "    if overlap:\n"
    "        _fail(\"slots\", \"reserve already-held securities: %s\" % sorted(overlap))\n\n"
    "    _validate_counter_map(\n",
    "    overlap = held.intersection(reserved)\n"
    "    if overlap:\n"
    "        _fail(\"slots\", \"reserve already-held securities: %s\" % sorted(overlap))\n\n"
    "    cash = _finite(d.get(\"cash\", 0.0), \"cash\", non_negative=True)\n"
    "    reserved_cash_total = sum(slot[\"reserved_cash\"] for slot in slots.values())\n"
    "    if reserved_cash_total > cash:\n"
    "        _fail(\"slots\", \"reserve more entry cash than account cash\")\n\n"
    "    _validate_counter_map(\n",
)

# ---------------------------------------------------------------------------
# Decision kernel: calculate the full whole-share target first; cash either
# funds that target or the candidate does not acquire a slot.
# ---------------------------------------------------------------------------
replace_once(
    "shared/stock_strategy_shared/wealth_core/engine.py",
    "import hashlib\nimport json\n",
    "import hashlib\nimport json\nimport math\n",
)
old_whole = '''def whole_shares(equity: float, price: float, cash: float,
                 cfg: WealthCoreConfig) -> int:
    """Spec §6: 4% of CURRENT portfolio equity, whole shares, actual available
    cash, 10bps cost on the traded side, no leverage.

    The cost is included in the affordability test rather than applied after —
    sizing to exactly `cash` and then paying commission would overdraw by the
    commission on every single admission.
    """
    if price is None or price <= 0 or equity <= 0 or cash <= 0:
        return 0
    target = equity * cfg.entry_weight
    per_share = price * (1.0 + cfg.transaction_cost_bps / 10_000.0)
    shares = int(min(target, cash) // per_share)
    return max(0, shares)
'''
new_whole = '''def whole_share_target(equity: float, price: float | None,
                       cfg: WealthCoreConfig) -> tuple[int, float]:
    """The complete decision-time whole-share target and its cash requirement.

    Cash is deliberately absent from this calculation.  A 4%/5% target is a
    portfolio decision; available cash answers the separate yes/no question of
    whether that complete whole-share order may claim a slot.
    """
    if price is None or price <= 0 or equity <= 0:
        return 0, 0.0
    target = float(equity) * cfg.entry_weight
    per_share = float(price) * (1.0 + cfg.transaction_cost_bps / 10_000.0)
    shares = max(0, int(target // per_share))
    return shares, float(shares * per_share)


def whole_shares(equity: float, price: float, cash: float,
                 cfg: WealthCoreConfig) -> int:
    """Return the FULL whole-share target only when cash can fund it.

    Historical Wealth Core used ``min(target, cash)`` here.  That let a $28 cash
    remainder buy one share and own the same scarce slot as a properly funded
    target episode.  The corrected invariant is binary at the decision boundary:
    fund the complete whole-share target or leave the slot vacant.
    """
    shares, required_cash = whole_share_target(equity, price, cfg)
    if shares <= 0 or cash is None or not math.isfinite(float(cash)):
        return 0
    return shares if float(cash) >= required_cash else 0
'''
replace_once("shared/stock_strategy_shared/wealth_core/engine.py", old_whole, new_whole)

replace_once(
    "shared/stock_strategy_shared/wealth_core/engine.py",
    "        shares = whole_shares(equity, px, state.cash, cfg)\n"
    "        if shares <= 0:\n"
    "            reject(cand, Reason.REJECT_INSUFFICIENT_CASH, price=px)\n"
    "            continue\n"
    "        slot_id = ready.pop(0)\n",
    "        target_shares, required_cash = whole_share_target(equity, px, cfg)\n"
    "        available_cash = state.uncommitted_cash()\n"
    "        if target_shares <= 0 or available_cash < required_cash:\n"
    "            reject(cand, Reason.REJECT_INSUFFICIENT_CASH, price=px,\n"
    "                   target_shares=target_shares, required_cash=required_cash,\n"
    "                   uncommitted_cash=available_cash)\n"
    "            continue\n"
    "        shares = target_shares\n"
    "        slot_id = ready.pop(0)\n",
)
replace_once(
    "shared/stock_strategy_shared/wealth_core/engine.py",
    "        state.reserve_slot(slot_id, cand.security_id, cand.ticker, issuer)\n",
    "        state.reserve_slot(slot_id, cand.security_id, cand.ticker, issuer,\n"
    "                           required_cash)\n",
)
replace_once(
    "shared/stock_strategy_shared/wealth_core/engine.py",
    '                                "target_weight": cfg.entry_weight,\n'
    '                                "equity_at_decision": equity}))\n',
    '                                "target_weight": cfg.entry_weight,\n'
    '                                "equity_at_decision": equity,\n'
    '                                "reserved_cash": required_cash,\n'
    '                                "uncommitted_cash_before": available_cash}))\n',
)

# ---------------------------------------------------------------------------
# Fill boundary: a queued entry may spend its own reservation, not the account's
# later cash balance.  Upward gaps can reduce shares inside that budget.
# ---------------------------------------------------------------------------
old_fill = '''            # NO LEVERAGE, checked at the fill and not only at the decision.
            # The size was computed from session t's close; this is t+1's open
            # and it can gap. Fill what the cash actually covers.
            fillable = min(po.shares, affordable_shares(state.cash, px, cfg))
            if fillable <= 0:
                state.slots[po.slot_id].release_reservation()
                res_cancelled.append(
                    {"session": session, "security_id": po.security_id,
                     "ticker": po.ticker, "slot_id": po.slot_id,
                     "wanted_shares": po.shares, "raw_open": px,
                     "cash": round(state.cash, 2), "reason": "UNAFFORDABLE_AT_OPEN"})
                continue
            if fillable < po.shares:
                res_cancelled.append(
                    {"session": session, "security_id": po.security_id,
                     "ticker": po.ticker, "slot_id": po.slot_id,
                     "wanted_shares": po.shares, "filled_shares": fillable,
                     "raw_open": px, "reason": "PARTIAL_AT_OPEN"})
                po.shares = fillable
'''
new_fill = '''            # NO LEVERAGE, and no borrowing from tomorrow's unrelated cash.
            # The decision reserved a dollar budget together with this slot.
            # A gap may reduce shares, but this order may spend only that budget.
            slot = state.slots[po.slot_id]
            if slot.reserved_for != po.security_id or slot.reserved_cash <= 0:
                res_cancelled.append(_cancelled_order(
                    state, po, session=session, reason="MISSING_CASH_RESERVATION"))
                continue
            reserved_budget = float(slot.reserved_cash)
            fillable = min(po.shares, affordable_shares(reserved_budget, px, cfg))
            if fillable <= 0:
                res_cancelled.append(_cancelled_order(
                    state, po, session=session, reason="UNAFFORDABLE_AT_OPEN",
                    reserved_cash=reserved_budget,
                    account_cash=round(state.cash, 2), raw_open=px))
                continue
            if fillable < po.shares:
                res_cancelled.append(
                    {"session": session, "security_id": po.security_id,
                     "ticker": po.ticker, "slot_id": po.slot_id,
                     "wanted_shares": po.shares, "filled_shares": fillable,
                     "raw_open": px, "reserved_cash": reserved_budget,
                     "reason": "PARTIAL_AT_OPEN"})
                po.shares = fillable
'''
replace_once("shared/stock_strategy_shared/wealth_core/adapter.py", old_fill, new_fill)

# ---------------------------------------------------------------------------
# Existing acceptance test: the former cash-clipped expectation is the defect.
# ---------------------------------------------------------------------------
replace_once(
    "tests/wealth_core/test_state_machine.py",
    "        assert whole_shares(100_000.0, 100.0, 100_000.0, CFG) == 39   # 4000/100.1\n"
    "        assert whole_shares(100_000.0, 100.0, 500.0, CFG) == 4        # cash-bound\n"
    "        assert whole_shares(100_000.0, 0.0, 100_000.0, CFG) == 0\n",
    "        assert whole_shares(100_000.0, 100.0, 100_000.0, CFG) == 39   # 4000/100.1\n"
    "        # Cash no longer shrinks a target into a microscopic slot owner.\n"
    "        assert whole_shares(100_000.0, 100.0, 500.0, CFG) == 0\n"
    "        assert whole_shares(100_000.0, 0.0, 100_000.0, CFG) == 0\n",
)

# ---------------------------------------------------------------------------
# Dedicated falsifiers.  These are intentionally independent of historical
# returns and exercise decision, persistence, fill, and restart boundaries.
# ---------------------------------------------------------------------------
test_file = ROOT / "tests/wealth_core/test_slot_funding.py"
test_file.write_text(r'''"""Falsifiers for the corrected Wealth Core slot-funding invariant."""
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
''')

print("applied Wealth Core slot-funding correction")
