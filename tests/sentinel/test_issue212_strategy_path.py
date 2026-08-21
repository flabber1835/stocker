import json
import random

import pytest

from sentinel.controller.concordance import (
    advance_recent_leadership,
    state_from_dict as witness_from_dict,
    state_to_dict as witness_to_dict,
)
from sentinel.controller.concordance_parent import load as load_parent
from sentinel.controller.ldrc import (
    LDRCConfig,
    LDRCState,
    ldrc_step,
    state_from_dict as ldrc_from_dict,
    state_to_dict as ldrc_to_dict,
)
from sentinel.controller.machine import Controller
from sentinel.controller.recent_leadership import session_return
from sentinel.core.decision import runtime_strategy_identity
from sentinel.core.loader import CorpusWindow
from sentinel.core.production import SessionState, warm_session_state
from stock_strategy_shared.wealth_core.engine import WealthCoreConfig, score_universe
from stock_strategy_shared.wealth_core.feed import (
    DecisionMetadataTimelineBuilder,
    Feed,
    SecurityMeta,
    VendorBar,
)
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.state import PortfolioState
from tools.sentinel_concordance_differential import ReferenceConcordance


def _sessions(count=253):
    return [f"S{i:04d}" for i in range(1, count + 1)]


def _meta(*, common=True):
    category = "Domestic Common Stock" if common else "Domestic ETF"
    return {
        f"SEC-{i:03d}": SecurityMeta(
            security_id=f"SEC-{i:03d}", ticker=f"T{i:03d}",
            category=category, permaticker=f"SEC-{i:03d}",
            first_session="S0001")
        for i in range(30)
    }


def _bars(session, day):
    return [
        VendorBar(
            session=session, security_id=f"SEC-{i:03d}", ticker=f"T{i:03d}",
            raw_close=100.0 * ((1.0002 + i * 0.00001) ** day),
            raw_open=100.0, volume=1_000_000.0)
        for i in range(30)
    ]


def _surface(feed, session, bars):
    normalized = feed.advance(session, bars)
    scored = score_universe(normalized.security_bars, WealthCoreConfig())
    candidates = tuple(
        row for row in scored
        if row.momentum is not None and row.recent is not None)
    closes = {
        bar.security_id: float(feed.series[bar.security_id].signal_closes[-1])
        for bar in bars
        if feed.series[bar.security_id].signal_closes[-1] is not None
    }
    eligible = sum(1 for row in normalized.security_bars if row.eligible)
    return candidates, eligible, closes


def test_fresh_warmup_primes_only_causal_zero_capital_witness_and_day_one_matches_reference():
    sessions = _sessions()
    warm = sessions[:-1]
    causal_meta = _meta(common=True)
    window = CorpusWindow(
        sessions=warm,
        bars_by_session={
            session: _bars(session, day)
            for day, session in enumerate(warm, start=1)
        },
        # Deliberately poisonous current/future projection. If warmup reads it
        # instead of the session-effective maps, no security is eligible.
        meta=_meta(common=False),
    )
    warm_builder = DecisionMetadataTimelineBuilder(warm)
    for session in warm:
        warm_builder.add_snapshot(session, causal_meta)
    window.metadata_timeline = warm_builder.finish()
    config = load_parent()
    identity = runtime_strategy_identity(config, concordance=True)
    fresh = SessionState.fresh(
        starting_cash=1_000_000.0, controller=Controller(config),
        strategy_identity=identity)

    warmed = warm_session_state(
        fresh, window, publication_version=17)
    witness = witness_from_dict(warmed.recent_leadership)

    assert witness.last_session == warm[-1]
    assert len(witness.nav_history) == 41
    assert session_return(witness.nav_history, 20) is not None
    assert session_return(witness.nav_history, 40) is not None
    assert warmed.ldrc == fresh.ldrc
    assert warmed.controller == fresh.controller
    assert warmed.controller_session_history == []
    assert warmed.last_processed_session is None
    assert warmed.last_decision is None
    assert PortfolioState.from_dict(warmed.wealth_core).episodes == {}
    assert warmed.pending == []
    assert Ledger.from_dict(warmed.ledger).events == []

    # Independently replay the retained witness formula on the same causal
    # Wealth Core audit surface, then compare the first live close as well.
    builder = DecisionMetadataTimelineBuilder(sessions)
    for session in sessions:
        builder.add_snapshot(session, causal_meta)
    feed = Feed({}, metadata_timeline=builder.finish())
    reference = ReferenceConcordance()
    for day, session in enumerate(warm, start=1):
        candidates, eligible, closes = _surface(
            feed, session, _bars(session, day))
        if eligible:
            reference._witness(  # noqa: SLF001 - independent test oracle
                session=session, candidate_rows=candidates,
                eligible_universe_count=eligible, signal_closes=closes)
    assert witness_to_dict(witness) == {
        "version": 1,
        "selected_recent": list(reference.selected_recent),
        "selected_close": [list(row) for row in reference.selected_close],
        "nav_history": list(reference.nav_history),
        "session_history": list(reference.session_history),
        "last_session": reference.witness_last_session,
    }

    live_session = sessions[-1]
    candidates, eligible, closes = _surface(
        feed, live_session, _bars(live_session, len(sessions)))
    production_after, production_decision = advance_recent_leadership(
        session=live_session, candidate_rows=candidates,
        eligible_universe_count=eligible, signal_closes=closes,
        state=witness)
    reference_decision, reference_state = reference._witness(  # noqa: SLF001
        session=live_session, candidate_rows=candidates,
        eligible_universe_count=eligible, signal_closes=closes)
    assert production_decision.__dict__ == reference_decision
    assert witness_to_dict(production_after) == reference_state

    # An immediate restart consumes the exact same bounded witness image.
    restarted = SessionState.from_dict(json.loads(json.dumps(warmed.to_dict())))
    assert restarted.state_hash == warmed.state_hash
    assert restarted.recent_leadership == warmed.recent_leadership


def _ldrc_step(state, session, *, r20=-0.10, r40=-0.10, spy=0.12,
               cfg=LDRCConfig()):
    return ldrc_step(
        session=session, native_allocation=1.0,
        effective_native_allocation=1.0, wc_drawdown=-0.12,
        recent_r20=r20, recent_r40=r40, spy_r20=spy,
        state=state, cfg=cfg)


def test_spy_v_rebound_clear_is_authoritative_until_next_session():
    state = LDRCState(
        divergence_latched=True, previous_native_allocation=1.0,
        previous_desired_allocation=0.55, last_session="2026-01-01")
    state, decision = _ldrc_step(state, "2026-01-02")
    assert state.divergence_latched is False
    assert decision.desired_allocation == 1.0
    assert decision.reason == "DIVERGENCE_CLEAR_SPY_V_REBOUND"

    state, decision = _ldrc_step(
        state, "2026-01-03", spy=0.05)
    assert state.divergence_latched is True
    assert decision.desired_allocation == 0.55
    assert decision.reason == "LD_ENTER_DIVERGENCE"


def test_persistence_clear_also_cannot_reenter_under_adversarial_thresholds():
    cfg = LDRCConfig(recent_r20_trigger=0.10, recovery_sessions=7)
    state = LDRCState(
        divergence_latched=True, recovery_streak=6,
        previous_native_allocation=1.0, previous_desired_allocation=0.55,
        last_session="2026-01-01")
    state, decision = _ldrc_step(
        state, "2026-01-02", r20=0.01, r40=0.01, spy=0.01, cfg=cfg)
    assert state.divergence_latched is False
    assert "DIVERGENCE_CLEAR_PERSISTENCE" in decision.reason
    assert "LD_ENTER_DIVERGENCE" not in decision.reason


def test_clear_reentry_adversarial_threshold_matrix_has_no_same_session_relatched_case():
    values = (-0.1000000001, -0.10, -0.0999999999)
    recent = (-0.0800000001, -0.08, -0.0799999999)
    spy_values = (0.1100000001, 0.12, 0.50)
    for dd in values:
        for r20 in recent:
            for spy in spy_values:
                state = LDRCState(
                    divergence_latched=True,
                    previous_native_allocation=1.0,
                    previous_desired_allocation=0.55,
                    last_session="2026-01-01")
                next_state, decision = ldrc_step(
                    session="2026-01-02", native_allocation=1.0,
                    effective_native_allocation=1.0, wc_drawdown=dd,
                    recent_r20=r20, recent_r40=-0.10, spy_r20=spy,
                    state=state)
                assert next_state.divergence_latched is False
                assert "DIVERGENCE_CLEAR_SPY_V_REBOUND" in decision.reason
                assert "LD_ENTER_DIVERGENCE" not in decision.reason


def test_randomized_restart_transition_equivalence_after_clear_fix():
    rng = random.Random(212)
    state = LDRCState()
    for index in range(1, 10_001):
        kwargs = dict(
            session=f"S{index:05d}",
            native_allocation=rng.choice((0.0, 0.55, 0.65, 1.0)),
            effective_native_allocation=rng.choice((0.0, 0.55, 0.65, 1.0)),
            wc_drawdown=rng.choice((None, -0.20, -0.10, -0.099, 0.0)),
            recent_r20=rng.choice((None, -0.20, -0.08, 0.0, 0.02)),
            recent_r40=rng.choice((None, -0.20, 0.0, 0.02)),
            spy_r20=rng.choice((None, -0.01, 0.0, 0.11, 0.12)),
        )
        reloaded = ldrc_from_dict(json.loads(json.dumps(ldrc_to_dict(state))))
        live_state, live_decision = ldrc_step(state=state, **kwargs)
        restart_state, restart_decision = ldrc_step(state=reloaded, **kwargs)
        assert restart_state == live_state
        assert restart_decision == live_decision
        state = live_state


@pytest.mark.parametrize("value", [True, False])
def test_boolean_integer_financial_fields_are_rejected(value):
    with pytest.raises(ValueError, match="recovery_streak"):
        ldrc_to_dict(LDRCState(recovery_streak=value))
    with pytest.raises(ValueError, match="recovery_sessions"):
        _ldrc_step(LDRCState(), "2026-01-01", cfg=LDRCConfig(
            recovery_sessions=value))
    with pytest.raises(ValueError, match="sessions"):
        session_return((1.0, 1.1), value)
