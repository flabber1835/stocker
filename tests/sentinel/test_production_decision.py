"""Pure tests for the production shadow/controller execution adapter."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from sentinel.core import decision as decision_module
from sentinel.binding import AccountBinding, AccountMismatch, AccountNotBound
from sentinel.authority import RolloutMode, RolloutState
from sentinel.controller import frozen_rule
from sentinel.controller.machine import Controller
from sentinel.core.decision import (
    DATA_SEMANTICS_IDENTITY_SCHEMA,
    DEFENSIVE_SECURITY_ID,
    build_execution_plan,
    data_semantics_source_identity,
    publication_fingerprint,
    runtime_strategy_identity,
    shadow_target,
)
from sentinel.core.production import SessionState
from sentinel.execution.contract import (
    BrokerAccountIdentity,
    BrokerAccountSnapshot,
    BrokerInstrument,
    BrokerObservation,
    BrokerOrder,
    BrokerPosition,
    Completeness,
    IncompleteObservation,
    Side,
)
from sentinel.execution.states import CommandState
from sentinel.feed.publication import Publication
from stock_strategy_shared.wealth_core.adapter import PendingOrder
from stock_strategy_shared.wealth_core.engine import Operation
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState


DECISION_SESSION = date(2026, 8, 11)
EFFECTIVE_SESSION = date(2026, 8, 12)


def _episode(slot: int, security_id: str, ticker: str,
             shares: float) -> HoldingEpisode:
    return HoldingEpisode(
        security_id=security_id, ticker=ticker,
        issuer_id=f"issuer-{security_id}", slot_id=slot,
        signal_date="2026-01-02", entry_date="2026-01-05",
        entry_raw_open=100.0, entry_split_adjusted_price=100.0,
        initial_shares=shares, current_shares=shares)


def _state(*, episodes=(), pending=(), equity="2000",
           exposure="0.55", last_known=None) -> SessionState:
    episodes = list(episodes)
    pending = list(pending)
    portfolio = PortfolioState.fresh(2_000)
    for episode in episodes:
        portfolio.episodes[episode.slot_id] = episode
    anchors = {}
    for security_id, ticker, issuer_id in [
            (item.security_id, item.ticker, item.issuer_id)
            for item in episodes] + [
            (item.security_id, item.ticker, f"issuer-{item.security_id}")
            for item in pending]:
        anchors[security_id] = {
            "security_id": security_id, "ticker": ticker,
            "issuer_id": issuer_id, "split_factor": 1.0,
            "sessions": [], "session_indices": [], "signal_closes": [],
            "raw_closes": [], "volumes": [],
        }
    controller = Controller(frozen_rule.load()).initial_state()
    controller["last_session"] = DECISION_SESSION.isoformat()
    controller["last_target_core"] = float(exposure)
    return SessionState(
        wealth_core=portfolio.to_dict(),
        pending=[item.to_dict() for item in pending],
        ledger={"events": []}, last_known=dict(last_known or {}),
        feed={"session_index": -1, "seen_sessions": {}, "series": anchors},
        controller=controller, shadow_peak_nav=2_000,
        last_processed_session=DECISION_SESSION.isoformat(), data_version=7,
        strategy_identity={
            "strategy": "sentinel-test",
            "controller_rule_sha256": "controller-hash",
            "wealth_core_source_sha256": "wealth-hash",
            "data_semantics_source_sha256": "data-hash",
        },
        last_decision={
            "session": DECISION_SESSION.isoformat(),
            "target_core_exposure": exposure,
            "reason": "test", "evidence": {},
        },
        last_evidence={"wealth_core": {"estimated_equity": equity}},
    )


def _binding(account_id="paper-123") -> AccountBinding:
    return AccountBinding(
        deployment_id="sentinel-paper", broker="alpaca",
        broker_account_id=account_id, takeover_epoch=3)


def _account(account_id="paper-123", equity="10000",
             cash=None) -> BrokerAccountSnapshot:
    cash = equity if cash is None else cash
    return BrokerAccountSnapshot(
        identity=BrokerAccountIdentity(
            broker="alpaca", account_id=account_id),
        equity=Decimal(equity), cash=Decimal(cash),
        buying_power=Decimal(cash), multiplier=Decimal(1))


def _publication() -> Publication:
    return Publication(
        version=7, previous_version=6, run_id="run-7",
        window_start="2025-08-01", window_end="2026-08-11",
        evidence={"frontier": "2026-08-11", "rows": 1234})


def _observation(*, positions=(), orders=(),
                 completeness=Completeness.COMPLETE) -> BrokerObservation:
    return BrokerObservation(
        observed_at=datetime(2026, 8, 12, 13, 31, tzinfo=timezone.utc),
        positions=tuple(positions), orders=tuple(orders),
        completeness=completeness)


def _position(security_id: str, ticker: str, quantity: str) -> BrokerPosition:
    return BrokerPosition(
        instrument=BrokerInstrument(
            security_id=security_id, symbol=ticker,
            broker_id=f"broker-{security_id}"),
        quantity=Decimal(quantity))


def _working_order(security_id: str, ticker: str, *, side: Side,
                   quantity: str, filled: str = "0") -> BrokerOrder:
    filled_quantity = Decimal(filled)
    return BrokerOrder(
        broker_order_id=f"order-{security_id}", client_key="sentinel-key",
        instrument=BrokerInstrument(
            security_id=security_id, symbol=ticker,
            broker_id=f"broker-{security_id}"),
        side=side, state=CommandState.PARTIALLY_FILLED,
        quantity=Decimal(quantity), filled_quantity=filled_quantity,
        filled_average_price=(
            Decimal("100") if filled_quantity > 0 else None))


def _build(state: SessionState, *, observation=None, marks=None,
           binding=None, account=None, rollout=None):
    return build_execution_plan(
        state=state, binding=binding or _binding(),
        publication=_publication(), account_snapshot=account or _account(),
        observation=observation or _observation(),
        marks=marks or {"sec-a": "100", DEFENSIVE_SECURITY_ID: "90"},
        tickers={"sec-a": "AAA", DEFENSIVE_SECURITY_ID: "BIL"},
        decision_session=DECISION_SESSION,
        effective_session=EFFECTIVE_SESSION,
        rollout_state=rollout)


def _controller_rollout() -> RolloutState:
    return RolloutState(
        RolloutMode.CONTROLLER, 4, certificate_sha256="a" * 64)


def test_shadow_target_aggregates_episodes_and_signed_pending_entries():
    state = _state(
        episodes=[_episode(0, "returning", "RET", 6),
                  _episode(1, "returning", "RET", 4),
                  _episode(2, "closing", "CLS", 5)],
        pending=[
            PendingOrder(
                operation=Operation.OPEN_SLOT_POSITION,
                security_id="returning", ticker="RET", slot_id=3, shares=2,
                signal_session="2026-08-11", reason="ENTRY"),
            PendingOrder(
                operation=Operation.CLOSE_POSITION,
                security_id="closing", ticker="CLS", slot_id=2, shares=5,
                signal_session="2026-08-11", reason="EXIT"),
        ])

    target = shadow_target(state)

    assert target.shares == {"returning": Decimal("12")}
    assert target.tickers == {"closing": "CLS", "returning": "RET"}
    assert target.held_shares == {
        "closing": Decimal("5"), "returning": Decimal("10")}
    assert target.pending_open_shares == {
        "returning": (Decimal("2"),)}
    assert target.pending_close_shares == {
        "closing": (Decimal("5"),)}


def test_decision_refuses_a_noncanonical_controller_snapshot():
    state = _state(episodes=[_episode(0, "sec-a", "AAA", 10)])
    state.controller = {}

    with pytest.raises(ValueError, match="controller state schema mismatch"):
        shadow_target(state)


def test_default_rollout_pins_exposure_to_one_and_keeps_wealth_core_cash():
    state = _state(episodes=[_episode(0, "sec-a", "AAA", 10)])

    result = _build(state)

    # Core weight is 10 * $100 / $2,000 = .5. The default rollout exposes one
    # times that shadow and does not sweep Wealth Core's own cash into BIL.
    assert result.plan.target_basket == {
        "sec-a": Decimal("50"), DEFENSIVE_SECURITY_ID: Decimal("0")}
    assert result.plan.cash_residual == Decimal("5000.0")
    assert result.plan.account_nav == Decimal("10000")
    assert result.plan.target_exposure == Decimal("1")
    assert result.plan.rollout_mode == "PINNED_1_00"
    assert result.plan.rollout_version == 1
    assert result.plan.unpriced_securities == ()
    assert result.plan.defensive_security == DEFENSIVE_SECURITY_ID
    assert result.target_tickers == {
        "sec-a": "AAA", DEFENSIVE_SECURITY_ID: "BIL"}


def test_explicit_controller_rollout_uses_controller_exposure_and_is_stamped():
    state = _state(episodes=[_episode(0, "sec-a", "AAA", 10)])

    result = _build(state, rollout=_controller_rollout())

    assert result.plan.target_basket == {
        "sec-a": Decimal("27"), DEFENSIVE_SECURITY_ID: Decimal("50")}
    assert result.plan.cash_residual == Decimal("2800.00")
    assert result.plan.target_exposure == Decimal("0.55")
    assert result.plan.rollout_mode == "CONTROLLER"
    assert result.plan.rollout_version == 4
    assert result.plan.rollout_certificate_sha256 == "a" * 64


def test_plan_carries_every_identity_and_has_a_restart_stable_id():
    state = _state(episodes=[_episode(0, "sec-a", "AAA", 10)])
    publication = _publication()

    first = _build(state)
    restarted = build_execution_plan(
        state=SessionState.from_dict(deepcopy(state.to_dict())),
        binding=_binding(), publication=publication,
        account_snapshot=_account(), observation=_observation(),
        marks={DEFENSIVE_SECURITY_ID: Decimal("90"), "sec-a": Decimal("100")},
        tickers={DEFENSIVE_SECURITY_ID: "BIL", "sec-a": "AAA"},
        decision_session=DECISION_SESSION,
        effective_session=EFFECTIVE_SESSION)

    assert restarted.plan == first.plan
    assert first.plan.plan_id == f"sentinel-{first.plan.fingerprint()}"
    assert first.plan.shadow_snapshot_hash == state.state_hash
    assert first.plan.publication_fingerprint == publication_fingerprint(
        publication)
    assert first.plan.deployment_id == "sentinel-paper"
    assert first.plan.broker == "alpaca"
    assert first.plan.broker_account_id == "paper-123"
    assert first.plan.takeover_epoch == 3
    assert len(first.plan.sentinel_transition_hash) == 64
    assert len(first.plan.strategy_fingerprint) == 64


def test_broker_reported_equity_cannot_change_decision_close_target():
    state = _state(
        episodes=[_episode(0, "sec-a", "AAA", 10)], equity="2000")
    observation = _observation(
        positions=[_position("sec-a", "AAA", "10")])

    first = _build(
        state, observation=observation,
        account=_account(equity="10000", cash="1000"))
    moved_after_hours = _build(
        state, observation=observation,
        account=_account(equity="12345", cash="1000"))

    assert first.plan.account_nav == Decimal("2000")
    assert moved_after_hours.plan.account_nav == Decimal("2000")
    assert moved_after_hours.plan.target_basket == first.plan.target_basket
    assert moved_after_hours.plan.plan_id == first.plan.plan_id


@pytest.mark.parametrize(
    ("exposure", "held", "orders", "expected"),
    [
        ("0", "10", (), "0"),
        ("0.55", "10", (), "5"),
        ("0.55", "6", (), "5"),
        ("0.55", "4", (), "4"),
        ("0.55", "4", (
            (Side.BUY, "5", "2"),), "5"),
        ("0.55", "10", (
            (Side.SELL, "4", "1"),), "5"),
    ])
def test_unpriced_core_caps_at_scaled_share_target_without_blocking_trims(
        exposure, held, orders, expected):
    state = _state(
        episodes=[_episode(0, "sec-a", "AAA", 10)],
        equity="2000", exposure=exposure, last_known={"sec-a": 100.0})
    working = [
        _working_order(
            "sec-a", "AAA", side=side, quantity=quantity, filled=filled)
        for side, quantity, filled in orders
    ]
    observation = _observation(
        positions=[_position("sec-a", "AAA", held)], orders=working)
    # Keep the decision-close live NAV at 2,000 so the unpriced share target is
    # exactly floor(10 * exposure). The broker M2M equity is deliberately a
    # different number and has no sizing authority.
    cash = Decimal("2000") - Decimal(held) * Decimal("100")

    result = _build(
        state, observation=observation,
        account=_account(equity="9999", cash=str(cash)),
        marks={DEFENSIVE_SECURITY_ID: "100"},
        rollout=_controller_rollout())

    assert result.plan.unpriced_securities == ("sec-a",)
    assert result.plan.target_basket.get("sec-a", Decimal(0)) == Decimal(expected)
    assert result.projection.quantities.get(
        "sec-a", Decimal(0)) == Decimal(expected)


def test_unpriced_wanted_bil_is_preserved_but_dropped_core_remains_zero():
    closing = PendingOrder(
        operation=Operation.CLOSE_POSITION,
        security_id="sec-a", ticker="AAA", slot_id=0, shares=10,
        signal_session="2026-08-11", reason="EXIT")
    state = _state(
        episodes=[_episode(0, "sec-a", "AAA", 10)], pending=[closing],
        exposure="0", last_known={
            "sec-a": 100.0, DEFENSIVE_SECURITY_ID: 90.0})
    observation = _observation(
        positions=[_position("sec-a", "AAA", "10"),
                   _position(DEFENSIVE_SECURITY_ID, "BIL", "8")],
        orders=[_working_order(
            DEFENSIVE_SECURITY_ID, "BIL", side=Side.BUY, quantity="3")])

    result = _build(
        state, observation=observation, marks={"sec-a": "100"},
        account=_account(equity="10000", cash="8280"),
        rollout=RolloutState(
            RolloutMode.CONTROLLER, 2, certificate_sha256="a" * 64))

    assert "sec-a" not in result.plan.target_basket
    assert result.plan.target_basket[DEFENSIVE_SECURITY_ID] == Decimal("11")
    assert result.plan.unpriced_securities == (DEFENSIVE_SECURITY_ID,)


def test_working_order_only_security_is_given_an_explicit_zero_target():
    state = _state(episodes=[_episode(0, "sec-a", "AAA", 10)])
    observation = _observation(
        orders=[_working_order(
            "orphan", "OLD", side=Side.SELL, quantity="2")])

    result = _build(state, observation=observation)

    assert result.plan.target_basket["orphan"] == Decimal(0)
    assert result.target_tickers["orphan"] == "OLD"


def test_plan_refuses_unowned_mismatched_or_incomplete_broker_evidence():
    state = _state(episodes=[_episode(0, "sec-a", "AAA", 10)])
    unowned = AccountBinding(
        deployment_id="sentinel-paper", broker="alpaca",
        broker_account_id="paper-123", takeover_epoch=3,
        ownership_state="LEGACY")

    with pytest.raises(AccountNotBound):
        _build(state, binding=unowned)
    with pytest.raises(AccountMismatch):
        _build(state, account=_account("different-paper-account"))
    with pytest.raises(IncompleteObservation):
        _build(state, observation=_observation(
            completeness=Completeness.PARTIAL))


def test_plan_refuses_an_effective_session_other_than_next_xnys():
    state = _state(episodes=[_episode(0, "sec-a", "AAA", 10)])

    with pytest.raises(ValueError, match="next XNYS session"):
        build_execution_plan(
            state=state, binding=_binding(), publication=_publication(),
            account_snapshot=_account(), observation=_observation(),
            marks={"sec-a": "100", DEFENSIVE_SECURITY_ID: "90"},
            tickers={"sec-a": "AAA", DEFENSIVE_SECURITY_ID: "BIL"},
            decision_session=DECISION_SESSION,
            effective_session=date(2026, 8, 13))


def test_publication_and_runtime_strategy_identity_are_complete():
    class Config:
        strategy_id = "sentinel-test"
        digest = "controller-rule"

    strategy = runtime_strategy_identity(Config())

    assert strategy["strategy"] == "sentinel-test"
    assert strategy["controller_rule_sha256"] == "controller-rule"
    assert len(strategy["wealth_core_source_sha256"]) == 64
    assert len(strategy["data_semantics_source_sha256"]) == 64
    assert publication_fingerprint(_publication()) == publication_fingerprint(
        deepcopy(_publication().to_dict()))


def test_data_semantics_identity_moves_when_only_a_decoder_source_moves(
        monkeypatch, tmp_path):
    facade = tmp_path / "facade.py"
    decoder = tmp_path / "decoder.py"
    facade.write_text("VALUE = 1\n")
    decoder.write_text("VALUE = 1\n")
    modules = {
        "test.facade": SimpleNamespace(__file__=str(facade)),
        "test.decoder": SimpleNamespace(__file__=str(decoder)),
    }
    monkeypatch.setattr(
        decision_module, "_DATA_SEMANTICS_MODULES", tuple(modules))
    monkeypatch.setattr(
        decision_module.importlib, "import_module", modules.__getitem__)

    before = data_semantics_source_identity()
    decoder.write_text("VALUE = 2\n")
    after = data_semantics_source_identity()

    assert before["schema"] == DATA_SEMANTICS_IDENTITY_SCHEMA
    assert before["sha256"] != after["sha256"]
    assert before["files"][0] == after["files"][0]
    assert before["files"][1]["sha256"] != after["files"][1]["sha256"]


def test_data_semantics_bundle_names_transitive_book_dependencies():
    required = {
        "sentinel.breadth.classifier",
        "sentinel.controller.machine",
        "sentinel.core.catchup",
        "sentinel.execution.target_reprojection",
        "sentinel.feed.actions_map",
        "sentinel.feed.domains",
        "sentinel.feed.staging",
        "sentinel.paper",
        "sentinel.regime.spy",
        "stock_strategy_shared.split_reconciliation",
        "stock_strategy_shared.terminal_coalescing",
        "stock_strategy_shared.wealth_core.sharadar_domains",
    }

    assert required <= set(decision_module._DATA_SEMANTICS_MODULES)  # noqa: SLF001


def test_concordance_identity_refuses_pinned_one_rollout():
    state = _state(episodes=[_episode(0, "sec-a", "AAA", 10)])
    state.strategy_identity["allocation_overlay"] = (
        "sentinel-concordance-simplified-ldrc")
    state.recent_leadership = {
        "version": 1, "selected_recent": [], "selected_close": [],
        "nav_history": [], "session_history": [], "last_session": None}
    state.ldrc = {
        "version": 3, "recovery_episode": False,
        "divergence_latched": False, "recovery_streak": 0,
        "previous_native_allocation": 1.0,
        "previous_desired_allocation": 1.0, "last_session": None}
    with pytest.raises(ValueError, match="PINNED_1_00 cannot override"):
        _build(state)
