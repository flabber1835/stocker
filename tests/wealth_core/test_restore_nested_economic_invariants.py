"""Adversarial restart tests for nested Wealth Core economic state."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict

import pytest

from stock_strategy_shared.wealth_core.engine import (
    Reason,
    SecurityBar,
    WealthCoreConfig,
    decide,
)
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState
from stock_strategy_shared.wealth_core.terminal import (
    TerminalKind,
    TerminalTerms,
    sweep_pending_terms,
)


def _occupied_state(*, age=10, peak=100.0, entry=100.0):
    state = PortfolioState.fresh(1_000.0, n_slots=2)
    state.initialized = True
    state.slots[0].occupied_by = "SEC-A"
    state.episodes[0] = HoldingEpisode(
        security_id="SEC-A",
        ticker="AAA",
        issuer_id="ISS-A",
        slot_id=0,
        signal_date="2026-01-02",
        entry_date="2026-01-05",
        entry_raw_open=100.0,
        entry_split_adjusted_price=entry,
        initial_shares=10.0,
        current_shares=10.0,
        episode_peak_split_adjusted_close=peak,
        market_sessions_held=age,
        source_lots=[{
            "kind": "ADMISSION",
            "session": "2026-01-05",
            "security_id": "SEC-A",
            "ticker": "AAA",
            "shares": 10,
            "raw_open": 100.0,
        }],
    )
    return state


@pytest.mark.parametrize("field,value", [
    ("episode_peak_split_adjusted_close", float("nan")),
    ("episode_peak_split_adjusted_close", float("inf")),
    ("episode_peak_split_adjusted_close", 0.0),
    ("entry_split_adjusted_price", 0.0),
    ("entry_split_adjusted_price", float("nan")),
    ("initial_shares", 0.0),
    ("current_shares", -1.0),
    ("current_shares", float("nan")),
    ("market_sessions_held", -1),
    ("market_sessions_held", 1.5),
    ("market_sessions_held", True),
    ("review_completed", 1),
    ("exit_pending", "false"),
])
def test_restore_refuses_invalid_episode_economics(field, value):
    payload = _occupied_state().to_dict()
    payload["episodes"]["0"][field] = value

    with pytest.raises(ValueError, match="episode 0"):
        PortfolioState.from_dict(payload)


@pytest.mark.parametrize("value", [-1, 21, 1.5, True])
def test_restore_refuses_invalid_slot_cooldown(value):
    payload = PortfolioState.fresh(1_000.0, n_slots=2).to_dict()
    payload["slots"]["0"]["cooldown_sessions_elapsed"] = value

    with pytest.raises(ValueError, match="cooldown_sessions_elapsed"):
        PortfolioState.from_dict(payload)


def test_restore_refuses_partial_or_conflicting_slot_reservation():
    payload = PortfolioState.fresh(1_000.0, n_slots=2).to_dict()
    payload["slots"]["0"]["reserved_for"] = "SEC-A"
    with pytest.raises(ValueError, match="reservation"):
        PortfolioState.from_dict(payload)

    payload = _occupied_state().to_dict()
    payload["slots"]["0"].update({
        "reserved_for": "SEC-B",
        "reserved_ticker": "BBB",
        "reserved_issuer": "ISS-B",
    })
    with pytest.raises(ValueError, match="occupied and reserved"):
        PortfolioState.from_dict(payload)


def test_restore_refuses_slot_episode_identity_disagreement():
    payload = _occupied_state().to_dict()
    payload["slots"]["0"]["occupied_by"] = "SEC-B"

    with pytest.raises(ValueError, match="occupant disagrees"):
        PortfolioState.from_dict(payload)


@pytest.mark.parametrize("value", [-1, 21, 1.5, True])
def test_restore_refuses_invalid_security_cooldown(value):
    payload = PortfolioState.fresh(1_000.0, n_slots=2).to_dict()
    payload["security_cooldowns"] = {"SEC-X": value}

    with pytest.raises(ValueError, match="security_cooldowns"):
        PortfolioState.from_dict(payload)


def test_restore_refuses_held_or_reserved_security_in_security_cooldown():
    payload = _occupied_state().to_dict()
    payload["security_cooldowns"] = {"SEC-A": 3}
    with pytest.raises(ValueError, match="held or reserved"):
        PortfolioState.from_dict(payload)

    payload = PortfolioState.fresh(1_000.0, n_slots=2).to_dict()
    payload["slots"]["0"].update({
        "reserved_for": "SEC-A",
        "reserved_ticker": "AAA",
        "reserved_issuer": "ISS-A",
    })
    payload["security_cooldowns"] = {"SEC-A": 3}
    with pytest.raises(ValueError, match="held or reserved"):
        PortfolioState.from_dict(payload)


@pytest.mark.parametrize("field,value", [
    ("sessions_since_valid_mark", -1),
    ("sessions_since_valid_mark", 1.5),
    ("terminal_pending_sessions", -1),
    ("terminal_pending_sessions", 10),
])
def test_restore_refuses_invalid_settlement_clocks(field, value):
    state = _occupied_state()
    terms = TerminalTerms(
        session="2026-08-25",
        security_id="SEC-A",
        kind=TerminalKind.CASH_MERGER,
        cash_per_share=None,
        reference="event-1",
    )
    state.sessions_since_valid_mark["SEC-A"] = 1
    state.terminal_pending_sessions["SEC-A"] = 1
    state.terminal_pending_terms["SEC-A"] = {
        "terms": asdict(terms),
        "stale_at_event": 0,
    }
    payload = state.to_dict()
    payload[field]["SEC-A"] = value

    with pytest.raises(ValueError, match=field):
        PortfolioState.from_dict(payload)


def test_restore_refuses_terminal_counter_without_matching_terms():
    payload = _occupied_state().to_dict()
    payload["terminal_pending_sessions"] = {"SEC-A": 2}

    with pytest.raises(ValueError, match="counter and stored-term keys disagree"):
        PortfolioState.from_dict(payload)


def test_restore_refuses_pending_terms_for_wrong_security_or_stale_event_mark():
    state = _occupied_state()
    terms = TerminalTerms(
        session="2026-08-25",
        security_id="SEC-A",
        kind=TerminalKind.CASH_MERGER,
        cash_per_share=None,
        reference="event-1",
    )
    state.terminal_pending_sessions["SEC-A"] = 2
    state.terminal_pending_terms["SEC-A"] = {
        "terms": asdict(terms),
        "stale_at_event": 0,
    }
    payload = state.to_dict()

    wrong_security = deepcopy(payload)
    wrong_security["terminal_pending_terms"]["SEC-A"]["terms"][
        "security_id"] = "SEC-B"
    with pytest.raises(ValueError, match="security_id disagrees"):
        PortfolioState.from_dict(wrong_security)

    stale = deepcopy(payload)
    stale["terminal_pending_terms"]["SEC-A"]["stale_at_event"] = 11
    with pytest.raises(ValueError, match="mark-recency"):
        PortfolioState.from_dict(stale)


def _next_decision(state, close):
    state.age_one_session({"SEC-A": close})
    return decide(
        session="2026-08-26",
        state=state,
        bars=[SecurityBar(
            security_id="SEC-A", ticker="AAA", issuer_id="ISS-A",
            closes=[close], raw_close=close)],
        marks={},
        cfg=WealthCoreConfig(),
        strategy_id="test",
        strategy_version=1,
    )


@pytest.mark.parametrize("age,peak,close,reason", [
    (10, 100.0, 70.0, Reason.EXIT_TRAILING_STOP),
    (118, 100.0, 90.0, Reason.EXIT_REVIEW_WEAKNESS),
])
def test_valid_restore_preserves_next_session_exit_semantics(
        age, peak, close, reason):
    direct = _occupied_state(age=age, peak=peak)
    restored = PortfolioState.from_dict(deepcopy(direct.to_dict()))

    direct_decision = _next_decision(direct, close)
    restored_decision = _next_decision(restored, close)

    assert restored_decision.to_dict() == direct_decision.to_dict()
    assert any(op.reason is reason for op in restored_decision.operations)


def test_valid_restore_preserves_terminal_grace_expiry_and_settlement():
    state = _occupied_state()
    terms = TerminalTerms(
        session="2026-08-15",
        security_id="SEC-A",
        kind=TerminalKind.CASH_MERGER,
        cash_per_share=None,
        reference="event-1",
    )
    state.sessions_since_valid_mark["SEC-A"] = 1
    state.terminal_pending_sessions["SEC-A"] = 9
    state.terminal_pending_terms["SEC-A"] = {
        "terms": asdict(terms),
        "stale_at_event": 0,
    }

    restored = PortfolioState.from_dict(deepcopy(state.to_dict()))
    ledger = Ledger()
    result = sweep_pending_terms(
        restored,
        ledger=ledger,
        session="2026-08-26",
        last_known={"SEC-A": 50.0},
    )

    assert len(result) == 1
    assert result[0]["applied"] is True
    assert result[0]["settlement_source"] == "LAST_TRUSTWORTHY_MARK"
    assert restored.cash == pytest.approx(1_500.0)
    assert 0 not in restored.episodes
    assert restored.slots[0].cooldown_sessions_elapsed == 0
    assert restored.security_cooldowns["SEC-A"] == 0
