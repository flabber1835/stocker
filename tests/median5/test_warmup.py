from dataclasses import replace
from types import SimpleNamespace

import pytest

from sentinel.controller.machine import Controller
from sentinel.core.loader import CorpusWindow
from sentinel.core.production import warm_session_state
from sentinel.core.session import SessionState
from sentinel.feed import calendar
from sentinel.strategy import production_strategy
from sentinel.shadow_runtime import _warmup_input_identity
from sentinel.shadow_observation import ShadowObserver, ShadowObservationRefused, _validate_warmup_input_identity
from stock_strategy_shared.wealth_core.feed import SecurityMeta, VendorBar


def test_prospective_warmup_keeps_book_cold_and_binds_peer_inputs():
    first = "2026-09-04"
    sessions = calendar.previous_sessions(first, 253)[:-1]
    meta = {str(i): SecurityMeta(str(i), f"T{i}", "Common Stock", str(i),
                                first_session=sessions[0]) for i in range(30)}
    bars = {s: [VendorBar(s, sid, m.ticker, 100.+day, 100.+day, 1e6,
                          signal_close=100.+day) for sid, m in meta.items()]
            for day, s in enumerate(sessions)}
    window = CorpusWindow(sessions, bars, meta)
    window.median5_spy_closes = {s: 100.+i*.05 for i, s in enumerate(sessions)}
    window.median5_terminals = {}
    cfg, identity = production_strategy()
    seed = SessionState.fresh(starting_cash=1e6, controller=Controller(cfg), strategy_identity=identity)
    warmed = warm_session_state(seed, window, publication_version=1,
                                prospective_concordance_witness=True)
    assert warmed.wealth_core["episodes"] == {}
    assert warmed.pending == []
    assert warmed.median5["witness_nav"] == [1.]
    assert warmed.wealth_core["median5"]["rank_history"] == []
    assert len(warmed.median5["spy_history"]) == 252
    assert warmed.wealth_core["median5"]["last_index"] == 251
    proof = _warmup_input_identity(window, sessions, prospective_witness=True)
    assert _validate_warmup_input_identity(proof, first_session=first) == proof
    ShadowObserver._assert_seed(SimpleNamespace(
        initial_state=warmed, strategy_identity=identity, controller_config=cfg,
        starting_cash="1000000", first_session=first))
    window.median5_spy_closes[sessions[-1]] *= 1.01
    changed = _warmup_input_identity(window, sessions, prospective_witness=True)
    assert changed["warmup_input_sha256"] != proof["warmup_input_sha256"]
    changed["median5_spy_sha256"] = proof["median5_spy_sha256"]
    with pytest.raises(ShadowObservationRefused, match="incoherent"):
        _validate_warmup_input_identity(changed, first_session=first)
