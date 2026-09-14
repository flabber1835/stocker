"""Economic formation invariants under the selected production champion."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from sentinel.controller.machine import Controller
from sentinel.core.kernel import advance_session
from sentinel.core.loader import CorpusWindow
from sentinel.core.production import warm_session_state
from sentinel.core.session import DefensiveBar, PublishedSession, SessionState
from sentinel.feed import calendar
from sentinel.strategy import production_strategy
from stock_strategy_shared.wealth_core.feed import SecurityMeta, VendorBar
from stock_strategy_shared.wealth_core.state import PortfolioState


@pytest.fixture
def market():
    axis = calendar.previous_sessions("2026-09-14", 254)
    meta = {str(i): SecurityMeta(str(i), f"T{i}", "Domestic Common Stock", str(i),
                               first_session=axis[0]) for i in range(40)}
    def prices(index):
        return [VendorBar(axis[index], sid, row.ticker,
                (50. + int(sid)) * (1.0004 + int(sid)*.00002)**index,
                (50. + int(sid)) * (1.0004 + int(sid)*.00002)**index,
                2000000, signal_close=(50. + int(sid)) * (1.0004 + int(sid)*.00002)**index)
                for sid, row in meta.items()]
    window = CorpusWindow(axis[:252], {s: prices(i) for i, s in enumerate(axis[:252])}, meta)
    window.median5_spy_closes = {s: 100. + i*.05 for i, s in enumerate(axis[:252])}
    window.median5_terminals = {}
    controller, strategy = production_strategy()
    seed = SessionState.fresh(starting_cash=1000000, controller=Controller(controller), strategy_identity=strategy)
    def published(index):
        day = axis[index]
        return PublishedSession(day, 1, prices(index), meta, {},
            [100. + i*.05 for i in range(index+1)], spy_sessions=axis[:index+1],
            spy_expected_sessions=axis[:index+1],
            defensive_bar=DefensiveBar(day, "SENTINEL:BIL", "BIL", 100., 100., 100., 100.),
            defensive_previous_bar=DefensiveBar(axis[index-1], "SENTINEL:BIL", "BIL", 100., 100., 100., 100.),
            signal_basis_anchors={b.security_id: b for b in prices(index-1)})
    return window, seed, controller, strategy, published


def warmed(seed, window):
    return warm_session_state(seed, window, publication_version=1, prospective_concordance_witness=True)


def test_warmup_keeps_all_cash_and_creates_no_economic_history(market):
    window, seed, *_ = market
    original = deepcopy(seed.to_dict())
    state = warmed(seed, window)
    book = PortfolioState.from_dict(state.wealth_core)
    assert seed.to_dict() == original
    assert book.cash == 1000000
    assert not book.episodes and not book.initialized
    assert not book.security_cooldowns and not book.unresolved_terminals
    assert len(book.slots) == 20
    assert all(s.occupied_by is None and s.reserved_for is None
               and s.cooldown_sessions_elapsed is None for s in book.slots.values())
    assert state.pending == [] and state.ledger == seed.ledger
    assert state.controller == seed.controller
    assert state.last_processed_session is None and state.last_decision is None
    assert state.controller_session_history == state.shadow_nav_history == state.trailing_stop_sessions == []
    assert state.shadow_peak_nav == 1000000
    assert state.feed["session_index"] == 251


def test_first_and_second_closes_are_economically_identical_after_warmup_restart(market):
    window, seed, controller, strategy, published = market
    state = warmed(seed, window)
    restored = SessionState.from_dict(json.loads(json.dumps(state.to_dict())))
    for index in (252, 253):
        state = advance_session(state, published(index), controller_config=controller, strategy_identity=strategy)
        restored = advance_session(restored, published(index), controller_config=controller, strategy_identity=strategy)
        assert state.to_dict() == restored.to_dict()
        restored = SessionState.from_dict(json.loads(json.dumps(restored.to_dict())))
    book = PortfolioState.from_dict(state.wealth_core)
    assert len(book.episodes) == 20
    assert book.cash >= 0
    assert len(state.controller_session_history) == 2


def test_source_row_order_cannot_change_warmup_features_or_first_two_closes(market):
    window, seed, controller, strategy, published = market
    baseline = warmed(seed, window)
    window.meta = dict(reversed(list(window.meta.items())))
    for rows in window.bars_by_session.values():
        rows.reverse()
    candidate = warmed(seed, window)
    assert baseline.to_dict() == candidate.to_dict()
    for index in (252, 253):
        session = published(index)
        baseline = advance_session(baseline, session, controller_config=controller, strategy_identity=strategy)
        candidate = advance_session(candidate, replace(session, bars=list(reversed(session.bars))),
                                    controller_config=controller, strategy_identity=strategy)
        assert baseline.to_dict() == candidate.to_dict()


@pytest.mark.parametrize("fault", ["first", "middle", "last", "future", "none", "nan", "zero", "negative"])
def test_warmup_identity_refuses_invalid_benchmark_before_hashing(market, fault):
    from sentinel import shadow_runtime
    window, *_ = market
    if fault in {"first", "middle", "last"}:
        del window.median5_spy_closes[window.sessions[{"first": 0, "middle": 120, "last": -1}[fault]]]
    elif fault == "future":
        window.median5_spy_closes["2026-09-14"] = 100.
    else:
        window.median5_spy_closes[window.sessions[120]] = {
            "none": None, "nan": float("nan"), "zero": 0., "negative": -1.}[fault]
    with pytest.raises(shadow_runtime.ShadowRuntimeRefused):
        shadow_runtime._warmup_input_identity(window, window.sessions, prospective_witness=True)


@pytest.mark.parametrize("fault", ["empty", "short", "duplicate", "reversed", "missing_spy", "nan_spy",
                                  "negative_spy", "nonfresh", "no_causal_metadata"])
def test_invalid_warmup_inputs_refuse_before_economic_activity(market, fault):
    window, seed, *_ = market
    if fault == "empty":
        window.sessions = []
    elif fault == "short":
        window.sessions = window.sessions[1:]
    elif fault == "duplicate":
        window.sessions.insert(1, window.sessions[0])
    elif fault == "reversed":
        window.sessions.reverse()
    elif fault == "missing_spy":
        del window.median5_spy_closes[window.sessions[100]]
    elif fault == "nan_spy":
        window.median5_spy_closes[window.sessions[100]] = float("nan")
    elif fault == "negative_spy":
        window.median5_spy_closes[window.sessions[100]] = -1
    elif fault == "nonfresh":
        seed.last_processed_session = window.sessions[-1]
    original = deepcopy(seed.to_dict())
    with pytest.raises(ValueError):
        warm_session_state(seed, window, publication_version=1,
                           prospective_concordance_witness=fault != "no_causal_metadata")
    assert seed.to_dict() == original


def test_irrelevant_young_instruments_do_not_change_champion_book_economics(market):
    window, seed, controller, strategy, published = market
    baseline = warmed(seed, window)
    day = window.sessions[-20]
    window.meta = dict(window.meta)
    window.meta["IPO"] = SecurityMeta("IPO", "UNIT", "Domestic Common Stock", "IPO", first_session=day)
    for session in window.sessions[-20:]:
        window.bars_by_session[session].append(VendorBar(session, "IPO", "UNIT", 10., 10., 1000, signal_close=10.))
    candidate = warmed(seed, window)
    for index in (252, 253):
        clean = published(index)
        with_ipo = replace(clean, meta=window.meta,
            bars=[*clean.bars, VendorBar(clean.session, "IPO", "UNIT", 10., 10., 1000, signal_close=10.)])
        baseline = advance_session(baseline, clean, controller_config=controller, strategy_identity=strategy)
        candidate = advance_session(candidate, with_ipo, controller_config=controller, strategy_identity=strategy)
        left, right = (PortfolioState.from_dict(s.wealth_core) for s in (baseline, candidate))
        assert left.cash == right.cash
        assert left.episodes == right.episodes
        assert left.slots == right.slots
        assert baseline.pending == candidate.pending
        assert baseline.ledger == candidate.ledger
        assert baseline.last_decision == candidate.last_decision
    assert len(left.episodes) == 20
