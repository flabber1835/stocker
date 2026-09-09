from copy import deepcopy
import ast
from dataclasses import dataclass, field
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import random

import numpy as np
import pytest

from sentinel.controller import ex3_v5, median5
from stock_strategy_shared.wealth_core import v5
from stock_strategy_shared.wealth_core.adapter import PendingOrder, step_session
from stock_strategy_shared.wealth_core.engine import Operation, SecurityBar
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.prices import DailyBar
from stock_strategy_shared.wealth_core.state import PortfolioState


def oracle():
    source = Path(__file__).with_name("frozen_reference.txt").read_text()
    assert hashlib.sha256(source.encode()).hexdigest() == v5.REFERENCE_SOURCE_SHA256
    tree = ast.parse(source)
    names = {"LDRC_DD", "LDRC_R20", "LDRC_CEIL", "LDRC_REC", "LDRC_V"}
    nodes = [n for n in tree.body if
             isinstance(n, ast.FunctionDef) and n.name == "finite"
             or isinstance(n, ast.ClassDef) and n.name == "CandidateA"
             or isinstance(n, ast.Assign) and all(isinstance(t, ast.Name) and t.id in names for t in n.targets)]
    scope = dict(np=np, math=math)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "selected_v5_reference", "exec"), scope)
    return scope["CandidateA"]()


def test_agn1_uses_total_cash_and_amzn_is_rejected():
    assert v5.admission(equity=214460., cash=232.45, price=166.92) == (10723., "")
    assert v5.admission(equity=214460., cash=232.45, price=1000.) == (
        None, "TOTAL_CASH_ONE_SHARE_UNAFFORDABLE_AT_CLOSE")
    assert v5.admission(equity=100000., cash=100., price=1.) == (None, "CASH_SCARCITY")
    assert v5.admission(equity=100000., cash=100.01, price=1.) == (5000., "")


def test_open_budget_uses_actual_price_cash_and_released_cushion():
    assert v5.opening_quantity(intended=5000., cash=100000., price=50.) == 99
    assert v5.opening_quantity(intended=5000., cash=100000., price=200.) == 24
    assert v5.opening_quantity(intended=5000., cash=232.45, price=166.92) == 1
    assert v5.opening_quantity(intended=5000., cash=232.45, price=240.) == 0


def book():
    state = PortfolioState.fresh(100000., 20)
    state.initialized = True
    state.median5 = median5_features()
    return state


def median5_features():
    from stock_strategy_shared.wealth_core.median5 import fresh
    x = fresh(); x["formation_started"] = True
    return x


def bars(session, *, opened=100., close=100., volume=1e6, split=1.):
    return [DailyBar("A", "A", "SID:A", session,
                     signal_close_split_adj_div_unadj=close, raw_open=opened,
                     raw_mark_close=close, tradeable=volume > 0, split_ratio=split)]


def advance(state, pending, session, *, opened=100., close=100., volume=1e6,
            split=1., candidates=()):
    return step_session(session=session, state=state,
        bars=bars(session, opened=opened, close=close, volume=volume, split=split),
        security_bars=list(candidates), pending=pending, ledger=Ledger(),
        last_known={}, cfg=v5.config(), strategy_id=ex3_v5.STRATEGY_ID, strategy_version=1)


def test_close_admission_has_no_bound_quantity_and_open_reprices():
    state, pending = book(), []
    cand = SecurityBar("A", "A", "SID:A", [80., 100.], 100., True, "", (.5, .1, .2, 2.))
    advance(state, pending, "0001", candidates=[cand])
    assert len(pending) == 1
    assert pending[0].shares == 0 and pending[0].intended_dollars == 5000.
    restored = PendingOrder.from_dict(json.loads(json.dumps(pending[0].to_dict())))
    assert restored == pending[0]
    pending[:] = [restored]
    result = advance(state, pending, "0002", opened=50., close=50.)
    assert result.fills[0]["shares"] == 99
    assert state.episodes[0].current_shares == 99
    assert state.cash == pytest.approx(95045.05)
    assert pending == []


@pytest.mark.parametrize("opened,volume,reason", [
    (None, 1e6, "INVALID_OPEN_MARKET"),
    (50., 0., "INVALID_OPEN_MARKET"),
    (6000., 1e6, "UNAFFORDABLE_AT_OPEN"),
])
def test_invalid_and_zero_entries_release_reservations(opened, volume, reason):
    state = book(); state.reserve_slot(0, "A", "A", "SID:A")
    pending = [PendingOrder(Operation.OPEN_SLOT_POSITION, "A", "A", 0, 0,
                            "0001", "ENTRY_DURABLE_RANK", intended_dollars=5000.)]
    result = advance(state, pending, "0002", opened=opened, volume=volume)
    assert not pending and not state.reserved_security_ids() and not state.episodes
    assert result.cancelled[0]["reason"] == reason
    assert state.cash == 100000.


def test_split_preserves_dollars_and_sizes_whole_shares_at_new_price():
    state = book(); state.reserve_slot(0, "A", "A", "SID:A")
    pending = [PendingOrder(Operation.OPEN_SLOT_POSITION, "A", "A", 0, 0,
                            "0001", "ENTRY_DURABLE_RANK", intended_dollars=5000.)]
    result = advance(state, pending, "0002", opened=50., close=50., split=2.)
    assert result.fills[0]["shares"] == 99


def test_old_quantity_intent_is_rejected_before_state_mutation():
    state = book(); state.reserve_slot(0, "A", "A", "SID:A")
    pending = [PendingOrder(Operation.OPEN_SLOT_POSITION, "A", "A", 0, 49,
                            "0001", "ENTRY_DURABLE_RANK")]
    before = deepcopy(state.to_dict())
    with pytest.raises(ValueError, match="intended dollars"):
        advance(state, pending, "0002")
    assert state.to_dict() == before


def test_rec8_strict_r40_boundary_and_latch_release():
    state = median5.fresh(); state["latched"] = True
    state["previous_desired"] = .55
    def step(x, r40):
        return ex3_v5.recover(state=x, native=1., wc_drawdown=-.05,
            recent_r20=.02, recent_r40=r40, spy_r20=.01, wc_r20=.03)
    for _ in range(10):
        state, _ = step(state, -.04)
    assert state["full_streak"] == 0 and state["latched"]
    for _ in range(7):
        state, d = step(state, math.nextafter(-.04, math.inf))
        assert d["desired_allocation"] == .55
    state, d = step(state, math.nextafter(-.04, math.inf))
    assert d["desired_allocation"] == 1. and not state["latched"]


def test_controller_matches_selected_reference_with_restarts():
    ref, state, rng = oracle(), median5.fresh(), random.Random(849)
    for _ in range(4000):
        native = rng.choice([0., .55, .65, 1., 1.])
        dd = rng.choice([None, -.1, -.2, -.099])
        r20 = rng.choice([None, -.085, -.12, .02, .08])
        r40 = rng.choice([None, -.05, -.04, -.039, .02])
        spy20 = rng.choice([None, -.01, 0., .11, .12])
        wc20 = rng.choice([None, -.04, .01, .04])
        expected = ref.step(native, state["effective_native"], dd, r20, r40, spy20, wc20)
        state, decision = ex3_v5.recover(state=state, native=native, wc_drawdown=dd,
            recent_r20=r20, recent_r40=r40, spy_r20=spy20, wc_r20=wc20)
        assert (decision["desired_allocation"], decision["reason"]) == expected
        assert state["full_streak"] == ref.full_streak
        state = json.loads(json.dumps(state))


def test_selected_default_profile_and_identity():
    from sentinel.strategy import production_strategy, controller_for_identity
    from sentinel.core.session import SessionState
    from sentinel.controller.machine import Controller
    cfg, identity = production_strategy()
    assert cfg.strategy_id == ex3_v5.STRATEGY_ID
    assert identity["universe"] == "BROAD_SHARADAR_COMMON_EQUITY"
    assert controller_for_identity(identity) == cfg
    env = SessionState.fresh(starting_cash=100000., controller=Controller(cfg), strategy_identity=identity)
    assert len(env.wealth_core["slots"]) == 20
    assert SessionState.from_dict(env.to_dict()).to_dict() == env.to_dict()
