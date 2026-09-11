"""Exercise the actual selected kernel on the lab's economic facts before SQL."""
from copy import deepcopy
from types import SimpleNamespace
import pytest

from stock_strategy_shared.wealth_core.feed import SecurityMeta, VendorBar
from sentinel.core.kernel import advance_session
from sentinel.core.production import warm_session_state
from sentinel.core.session import Controller, DefensiveBar, PublishedSession, SessionState
from sentinel.feed import calendar
from sentinel.paper.preparation import _default_paper_strategy

from tests.internal_state import market, oracles
from tests.internal_state.contract import InvariantFailure


def test_same_session_provider_retry_advances_observation_only():
    from research.sharadar_replay.provider import Provider
    provider = Provider()
    failed = market.step(market.FIRST, faulty=True)
    provider.advance(failed)
    corrected = market.step(market.FIRST, observed_after=failed.at)
    provider.advance(corrected)
    assert corrected.at > failed.at
    assert corrected.through == failed.through
    assert corrected.expected == failed.expected
    assert corrected.tables == failed.tables
    assert failed.faults and not corrected.faults


@pytest.mark.parametrize("fault", ["roundoff", "volume", "price", "identity", "missing"])
def test_corpus_storage_precision_preserves_independent_falsifiers(fault):
    from research.sharadar_replay.oracle import StateMismatch
    expected = market.step(market.SEED).expected
    rows = list(expected.bars)
    row = list(rows[5])
    if fault == "roundoff":
        row[6] = 2000499.9999999998
    elif fault == "volume":
        row[6] += 0.000001
    elif fault == "price":
        row[4] += 0.000001
    elif fault == "identity":
        row[0] = "WRONG-ID"
    rows[5] = tuple(row)
    if fault == "missing":
        rows.pop()
    actual = expected.model_copy(update={"bars": tuple(rows)})
    if fault == "roundoff":
        market.compare_corpus(expected, actual)
    else:
        with pytest.raises(StateMismatch):
            market.compare_corpus(expected, actual)


def inputs(day, seed=0, shocks=()):
    facts = market.step(day, seed, shocks=shocks).expected
    axis = market.sessions(day)
    meta = {row[0]: SecurityMeta(row[0], row[1], category=row[2], permaticker=row[0],
                                first_session=market.START) for row in facts.identities}
    bars = {}
    for row in facts.bars:
        bars.setdefault(row[1], []).append(VendorBar(row[1], row[0], row[2], row[4], row[5], row[6],
                                                  split_ratio=row[7], dividend_per_share=row[8]))
    published = PublishedSession(session=day, data_version=2, bars=bars[day], meta=meta,
        sectors={sid: "Industrials" for sid in meta},
        spy_closeadj=[r[1] for r in facts.spy[-127:]], spy_sessions=axis[-127:],
        spy_expected_sessions=axis[-127:], defensive_bar=DefensiveBar(*facts.defensive[-1]),
        defensive_previous_bar=DefensiveBar(*facts.defensive[-2]))
    return bars, meta, published


def formed_state(seed=0, days=3):
    config, identity = _default_paper_strategy()
    state = SessionState.fresh(starting_cash=100000, controller=Controller(config), strategy_identity=identity)
    day = market.FIRST
    bars, meta, _ = inputs(day, seed)
    warm = SimpleNamespace(sessions=market.sessions(day)[-128:-1], bars_by_session=bars, meta=meta)
    state = warm_session_state(state, warm, publication_version=1, prospective_concordance_witness=True)
    for _ in range(days):
        _, _, published = inputs(day, seed)
        before = deepcopy(state.to_dict())
        state = advance_session(state, published, controller_config=config, strategy_identity=identity)
        # The prior object must still encode its original history.
        restored = SessionState.from_dict(before)
        again = advance_session(restored, published, controller_config=config, strategy_identity=identity)
        assert again.state_hash == state.state_hash
        day = calendar.next_session(day)
    return config, state


def test_fictional_market_populates_actual_wealth_core_witness_and_ldrc():
    _, state = formed_state()
    raw = state.to_dict()
    oracles.canonical_state(raw, identity=state.strategy_identity, cursor=state.last_processed_session)
    assert any(slot["occupied_by"] for slot in raw["wealth_core"]["slots"].values())
    assert raw["recent_leadership"]["session_history"]
    assert raw["ldrc"]["last_session"] == state.last_processed_session


def test_restart_preserves_all_path_dependent_state_on_next_session():
    config, state = formed_state(42)
    _, _, published = inputs(calendar.next_session(state.last_processed_session), 42)
    retained = deepcopy(state.to_dict())
    uninterrupted = advance_session(state, published, controller_config=config, strategy_identity=state.strategy_identity)
    resumed = advance_session(SessionState.from_dict(retained), published, controller_config=config,
                              strategy_identity=state.strategy_identity)
    assert uninterrupted.to_dict() == resumed.to_dict()
    assert retained == state.to_dict()


def test_fictional_drawdown_drives_the_actual_controller_and_preserves_history():
    config, state = formed_state()
    day = calendar.next_session(state.last_processed_session)
    shocks = [(day, -2200)]
    exposures = []
    for index in range(11):
        if index == 3:
            shocks.append((day, 3000))
        _, _, published = inputs(day, shocks=shocks)
        state = advance_session(state, published, controller_config=config, strategy_identity=state.strategy_identity)
        raw = state.to_dict()
        oracles.canonical_state(raw, identity=state.strategy_identity, cursor=day)
        exposures.append(raw["last_decision"]["target_core_exposure"])
        day = calendar.next_session(day)
    assert min(exposures) < 1, exposures
    assert state.ldrc["last_session"] == state.last_processed_session


@pytest.mark.parametrize("fault,invariant", [("cash", "shadow_cash_conservation"),
    ("shares", "shadow_share_conservation"), ("ledger", "shadow_trade_conservation"),
    ("slot", "episode_slot_ownership")])
def test_shadow_oracle_rejects_false_portfolio_and_ledger_facts(fault, invariant):
    _, state = formed_state()
    raw = state.to_dict()
    if fault == "cash":
        raw["wealth_core"]["cash"] += 1
    elif fault == "shares":
        raw["wealth_core"]["episodes"]["0"]["current_shares"] += 1
    elif fault == "ledger":
        raw["ledger"]["events"][0]["fees"] += 1
    else:
        raw["wealth_core"]["slots"]["0"]["occupied_by"] = "unknown"
    with pytest.raises(InvariantFailure) as captured:
        oracles.canonical_state(raw, identity=state.strategy_identity, cursor=state.last_processed_session)
    assert captured.value.invariant == invariant
