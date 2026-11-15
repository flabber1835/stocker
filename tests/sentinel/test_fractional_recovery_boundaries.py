"""Recover independently actionable PAPER work from durable evidence."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta, timezone
from decimal import Decimal as D
from types import SimpleNamespace

import psycopg
import pytest

from sentinel import automation_runtime, binding, dual_plan_authority, informational_paper_mirror, schema
from sentinel.authority import RolloutMode, RolloutState
from sentinel.core.decision import DEFENSIVE_SECURITY_ID, build_execution_plan
from sentinel.execution import executor, fractional_progress, fractional_sizing, held_targets
from sentinel.execution import journal, opening_sizing, protected_limits, target_reprojection
from sentinel.execution.guarded import OrderEvidenceNotReady
from sentinel.execution.market_buy_policy import MarketBuyPolicy
from sentinel.execution.simulator import SimulatedBroker
from sentinel.execution.states import CommandState as S
from sentinel.feed import calendar
from stock_strategy_shared.wealth_core.state import PortfolioState
from tests.sentinel import test_automation_runtime as runtime_fixtures
from tests.sentinel.test_fractional_continuity import owned_plan
from tests.sentinel.test_fractional_execution import AAA, DEPLOY, cmd, dollars, native_fills, observation
from tests.sentinel.test_fractional_flow import DollarBroker, fractional_environment
from tests.sentinel.test_limit_day_sizing import references
from tests.sentinel.test_market_day_execution import DEPLOYMENT, market_instruments, wrapper
from tests.sentinel.test_order_terms_schema import database, pg
from tests.sentinel.test_production_decision import _account, _binding, _episode, _observation, _publication
from tests.v5.test_opening import base, case


SID = AAA.security_id
ROLLOUT = RolloutState(RolloutMode.CONTROLLER, 1, "a" * 64)


def project(conn, state, plan, *, prices=None):
    initial = base(state, plan)
    projected = fractional_sizing.resolve(state, plan, initial,
        references(plan, initial, prices=prices), MarketBuyPolicy(True),
        baseline={"through_event_seq": 0, "commands": [], "holdings": {}}, retained_targets={})
    journal.save_plan(conn, plan)
    target_reprojection.record_projection(conn, projected)
    return projected


def record_authority(conn, state, plan, *, basis=None):
    authority = dual_plan_authority.build_authority(plan=plan,
        shadow_result=SimpleNamespace(state=state, record_sha256="a" * 64,
                                      runtime_authority_sha256="b" * 64),
        publication={}, account_snapshot=_account(), observation=_observation(),
        marks={SID: D(100)}, tickers={SID: AAA.symbol}, held_share_targets=basis,
        market_buy_policy_sha256=MarketBuyPolicy(True).fingerprint() if basis is not None else None)
    dual_plan_authority.record_authority(conn, authority)


def after_opening(state, plan):
    successor = deepcopy(state)
    successor.last_processed_session = plan.effective_session.isoformat()
    successor.owned_impairment["last_session"] = successor.last_processed_session
    successor.last_decision["session"] = successor.last_processed_session
    portfolio = PortfolioState.from_dict(successor.wealth_core)
    episode = _episode(0, SID, AAA.symbol, 50)
    episode.signal_date = plan.decision_session.isoformat()
    episode.entry_date = successor.last_processed_session
    portfolio.episodes[0] = episode
    portfolio.slots[0].occupied_by = SID
    portfolio.slots[0].release_reservation()
    successor.wealth_core = portfolio.to_dict()
    successor.pending = []
    return successor


@pytest.mark.parametrize("status,shares,price", [(S.FILLED, 9, 112), (S.CANCELLED, 8, 126)])
def test_exact_whole_market_overrun_keeps_owned_shares_and_clears_buy_authority(
        database, status, shares, price):
    schema.ensure_schema(database)
    before, raw = case(entries=1)
    plan = owned_plan(raw, account_nav=D(20000))
    projection = project(database, before, plan)
    command = cmd(qty="9", filled=str(shares), state=status)
    command = replace(command, identity=replace(command.identity, plan_id=plan.plan_id),
        broker_order_id="whole-market", filled_average_price=D(price))
    journal.save_command(database, command)
    pending = fractional_progress.evidence(database, projection=projection, deployment=DEPLOY)
    assert "FILL_PRINCIPAL_PENDING" in pending["blocked"][SID]
    native_fills(database, command)
    witness = fractional_progress.evidence(database, projection=projection, deployment=DEPLOY)
    assert witness["budget_overruns"] == {SID: "8"}
    assert witness["targets"] == {SID: str(shares)}
    assert not witness["remaining_dollars"]
    fractional_progress.require_completed(witness)
    record_authority(database, before, plan)
    after = after_opening(before, plan)
    account = SimpleNamespace(**DEPLOY.to_dict(), identity=DEPLOY)
    basis = held_targets.build_basis(database, previous=plan, state=after, binding=account, rollout=ROLLOUT)
    assert basis["targets"] == {SID: str(shares)}
    assert basis["budget_overruns"] == {SID: "8"}
    assert not basis["purchase_budgets"]
    after.last_decision["target_core_exposure"] = 0.0
    reduction = held_targets.build_basis(database, previous=plan, state=after, binding=account,
                                        rollout=ROLLOUT)
    assert not reduction["targets"] and not reduction["purchase_budgets"]


@pytest.mark.parametrize("closed", [False, True])
def test_carry_only_crash_recovers_inside_original_window(database, pg, monkeypatch, closed):
    t = runtime_fixtures
    schema.ensure_schema(database)
    before, raw = case(entries=1)
    first = owned_plan(raw, account_nav=D(20000))
    project(database, before, first)
    record_authority(database, before, first)
    after = after_opening(before, first)
    account = SimpleNamespace(**DEPLOY.to_dict(), identity=DEPLOY)
    basis = held_targets.build_basis(database, previous=first, state=after,
                                    binding=account, rollout=ROLLOUT)
    assert basis["purchase_budgets"] == {SID: "1000"}
    close = first.effective_session
    effective = date.fromisoformat(calendar.next_session(close.isoformat()))
    successor = owned_plan(build_execution_plan(after, _binding(), _publication(), _account(),
        _observation(), {SID: D(100)}, {SID: AAA.symbol}, close, effective,
        defensive_security=None, rollout_state=ROLLOUT, retained_targets={SID: D(0)},
        fractional_sizing=True).plan)
    assert not successor.opening_intents and successor.target_basket == {SID: D(0)}
    journal.save_plan(database, successor)
    record_authority(database, after, successor, basis=basis)

    cfg = t.config()
    context = t.context(cfg, state=t.CycleState.RECONCILING, plan=successor)
    cycle = context.cycle.model_copy(update={**DEPLOY.to_dict(),
        "decision_session": close, "effective_session": effective})
    context = context.model_copy(update={"cycle": cycle})
    runtime = t.production(cfg)
    runtime._dual_run_enabled = True
    t.install_runtime_seams(monkeypatch, runtime, database, context, SimulatedBroker())
    monkeypatch.setattr(runtime, "connect", lambda: psycopg.connect(pg.sync_dsn))
    monkeypatch.setattr(automation_runtime, "require_observation_integrity", lambda _: None)
    monkeypatch.setattr(automation_runtime.schema, "require_runtime_schema", lambda _: None)
    now = cycle.execution_close_at if closed else cycle.execute_at + timedelta(seconds=5)
    monkeypatch.setattr(automation_runtime, "_now_utc", lambda: now)
    monkeypatch.setattr(automation_runtime.feed_inputs, "require_current", lambda _: SimpleNamespace(version=7))
    monkeypatch.setattr(automation_runtime.feed_inputs, "frontier", lambda _: close.isoformat())
    monkeypatch.setattr(runtime, "_require_dual_plan_shadow_match",
        lambda *args, **kwargs: {"sizing_authority_sha256": "d" * 64, "shadow_record_sha256": "e" * 64})
    monkeypatch.setattr(informational_paper_mirror, "require_transport_permitted",
                        lambda *args, **kwargs: None)

    def unstamped(*args, **kwargs):
        raise informational_paper_mirror.InformationalPaperMirrorUnstamped("crash before projection")

    async def clean(**kwargs):
        return t.reconciliation(observation())

    monkeypatch.setattr(informational_paper_mirror, "require_pending_for_plan", unstamped)
    monkeypatch.setattr(automation_runtime.paper, "recover_automated_paper_cycle", clean)
    result = asyncio.run(runtime.recover(context))
    assert result.disposition is (t.ExecuteDisposition.SUPERSEDED if closed else
                                  t.ExecuteDisposition.READY_TO_EXECUTE)
    assert result.failure_code == ("EXECUTION_WINDOW_CLOSED" if closed else "OPENING_SIZING_REQUIRED")
    assert target_reprojection.load_projection(database, plan_id=successor.plan_id) is None
    next_basis = held_targets.build_basis(database, previous=successor, state=after,
                                         binding=account, rollout=ROLLOUT)
    assert next_basis["purchase_budgets"] == {SID: "1000"}
    assert held_targets.verify_basis(database, basis=next_basis, state=after,
        binding=account, rollout=ROLLOUT) == {SID: D(0)}
    unsent = dollars()
    planned = replace(unsent, identity=replace(unsent.identity, plan_id=successor.plan_id),
                      broker_order_id=None)
    journal.save_command(database, planned)
    assert opening_sizing.requires_initial_projection(database, plan=successor, deployment=DEPLOY)
    journal.save_command(database, replace(planned, state=S.SEND_PENDING), previous=S.PLANNED)
    with pytest.raises(target_reprojection.TargetProjectionRefused, match="projection is absent"):
        opening_sizing.requires_initial_projection(database, plan=successor, deployment=DEPLOY)


def test_unavailable_raw_reference_waits_without_blocking_healthy_recovery(database):
    schema.ensure_schema(database)
    state, raw = case(entries=2)
    plan = owned_plan(raw, account_nav=D(20000))
    projection = project(database, state, plan, prices={SID: D(100)})
    assert projection.opening_sizing["blocked"] == {"SEC-BBB": "REFERENCE_UNAVAILABLE"}
    kwargs = dict(plan=plan, effective_session=plan.effective_session,
                  minimum_quantity_increment=D("0.000000001"))
    actionable = automation_runtime._actionable_projection_deltas(
        database, **kwargs, observation=observation())
    assert [(delta.security_id, delta.notional) for delta in actionable] == [(SID, D(999))]
    command = dollars(filled="9.99", state=S.FILLED)
    command = replace(command, identity=replace(command.identity, plan_id=plan.plan_id))
    journal.save_command(database, command)
    native_fills(database, command)
    with pytest.raises(protected_limits.ProtectedReferenceUnavailable, match="SEC-BBB"):
        automation_runtime._actionable_projection_deltas(database, **kwargs, observation=observation("9.99"))


def test_unprojected_defensive_carry_requires_sizing_at_zero_core_exposure(database):
    schema.ensure_schema(database)
    before, raw = case(entries=0, exposure="0")
    sid = DEFENSIVE_SECURITY_ID

    def defensive_plan(state, decision, effective, *, retained_targets=None):
        return owned_plan(build_execution_plan(state, _binding(), _publication(),
            _account(equity="20000"), _observation(), {sid: D(100)}, {sid: "BIL"},
            decision, effective, rollout_state=ROLLOUT, retained_targets=retained_targets,
            fractional_sizing=True).plan)

    first = defensive_plan(before, raw.decision_session, raw.effective_session)
    projection = project(database, before, first)
    assert projection.opening_sizing["purchases"][sid] == {
        "budget": "20000", "origin": "ALLOCATION_CHANGE"}
    record_authority(database, before, first)
    close = raw.effective_session
    after = deepcopy(before)
    after.last_processed_session = close.isoformat()
    after.owned_impairment["last_session"] = after.last_processed_session
    after.last_decision["session"] = after.last_processed_session
    account = SimpleNamespace(**DEPLOY.to_dict(), identity=DEPLOY)
    basis = held_targets.build_basis(database, previous=first, state=after,
                                    binding=account, rollout=ROLLOUT)
    assert basis["targets"] == {sid: "0"} and basis["purchase_budgets"] == {sid: "20000"}
    successor = defensive_plan(after, close, date.fromisoformat(calendar.next_session(close.isoformat())),
                               retained_targets={sid: D(0)})
    assert not successor.opening_intents and successor.target_exposure == 0
    assert successor.target_basket == {sid: D(0)}
    journal.save_plan(database, successor)
    record_authority(database, after, successor, basis=basis)
    assert opening_sizing.requires_initial_projection(database, plan=successor, deployment=DEPLOY)


@pytest.mark.parametrize("cash,ambiguous", [(4000, False), (6000, True)])
def test_shortfall_leaves_exact_unsent_intent_and_funds_next_candidate(
        database, cash, ambiguous):
    schema.ensure_schema(database)
    binding.bind(database, deployment_id=DEPLOYMENT.deployment_id, broker=DEPLOYMENT.broker,
                 broker_account_id=DEPLOYMENT.broker_account_id)
    state, raw = case(entries=2)
    state.pending[1]["intended_dollars"] = 3000.0
    plan = replace(raw, **DEPLOYMENT.to_dict(), shadow_snapshot_hash=state.state_hash,
        opening_intents=(raw.opening_intents[0], replace(raw.opening_intents[1], intended_dollars=D(3000))))
    plan = replace(plan, plan_id="sentinel-" + plan.fingerprint())
    projection = project(database, state, plan)
    opened, _ = calendar.session_window(plan.effective_session)
    database.execute("UPDATE sentinel_account_binding SET established_at=%s", (opened,))
    database.commit()
    inner = DollarBroker(cash=D(cash))
    inner.now = opened.astimezone(timezone.utc) + timedelta(seconds=61)
    funding_checks, reservations, final_issuer_checks = [], [], []

    async def funding(**kwargs):
        funding_checks.append(kwargs)
        if ambiguous:
            raise OrderEvidenceNotReady("quote evidence unavailable")

    def reserve(*, security_id, reserve, **kwargs):
        if reserve:
            reservations.append(security_id)
        return SimpleNamespace(allowed=True)

    def final_issuer(*, instrument, **kwargs):
        final_issuer_checks.append(instrument.security_id)
        return SimpleNamespace(allowed=True)

    broker = wrapper(inner, funding=funding, issuer_check=final_issuer)

    async def execute():
        with journal.writer_lock(database, recovery_only=True):
            return await executor._execute_session_locked(broker=broker, conn=database,
                deployment=DEPLOYMENT, plan=plan, instruments=market_instruments(),
                today=plan.effective_session, actions=lambda *args: D(1),
                target_projection=projection, min_increment=D("0.000000001"),
                buy_admission=reserve)

    result = asyncio.run(execute())
    commands = journal.load_commands(database, DEPLOYMENT, plan_id=plan.plan_id)
    first = next(c for c in commands if c.security_id == SID)
    assert first.state is S.PLANNED and first.notional == 4999
    assert not any(call == "submit:" + first.client_key for call in inner.calls)
    if ambiguous:
        assert not result.submitted and reservations == [SID]
        assert [proof["notional"] for proof in funding_checks] == [D(4999)]
        return
    second, = result.submitted
    assert second.security_id == "SEC-BBB" and second.notional == 2999
    assert second.state is S.ACKNOWLEDGED and result.deferred == (SID,)
    assert reservations == [SID, "SEC-BBB"] and final_issuer_checks == ["SEC-BBB"]
    proof, = funding_checks
    assert proof["notional"] == D(2999) and proof["account"].cash == D(cash)
