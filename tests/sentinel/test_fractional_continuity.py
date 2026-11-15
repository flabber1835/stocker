"""Fractional execution evidence survives the boundaries between plans."""
import asyncio
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal as D
from fractions import Fraction
import json
from types import SimpleNamespace

import pytest

from sentinel import dual_plan_authority, schema
from sentinel.authority import RolloutMode, RolloutState
from sentinel.automation_runtime import _actionable_projection_deltas
from sentinel.execution import fractional_progress, fractional_sizing, held_targets, journal
from sentinel.execution import protected_limits, reconcile, target_reprojection
from sentinel.execution.contract import BrokerInstrument
from sentinel.execution.market_buy_policy import MarketBuyPolicy
from sentinel.execution.states import CommandState as S
from sentinel.feed import calendar
from sentinel.paper import targets
from tests.sentinel.test_fractional_execution import cmd, dollars, native_fills, observation, AAA, DEPLOY, NOW
from tests.sentinel.test_fractional_flow import DollarBroker, fractional_environment
from tests.sentinel.test_journal_and_reconcile import conn
from tests.sentinel.test_limit_day_sizing import ReferenceConnection, references, source_fixture
from tests.sentinel.test_order_terms_schema import database, pg
from tests.v5.test_opening import base, case


def owned_plan(original, **changes):
    plan = replace(original, deployment_id=DEPLOY.deployment_id, broker=DEPLOY.broker,
        broker_account_id=DEPLOY.broker_account_id, takeover_epoch=DEPLOY.takeover_epoch, **changes)
    return replace(plan, plan_id="sentinel-" + plan.fingerprint())


def test_filled_and_zero_fill_legs_carry_without_changing_their_projection(database, monkeypatch):
    schema.ensure_schema(database)
    before, raw = case(entries=2)
    plan = owned_plan(raw)
    initial = base(before, plan)
    projection = fractional_sizing.resolve(before, plan, initial, references(plan, initial),
        MarketBuyPolicy(True), baseline={"through_event_seq": 0, "commands": [], "holdings": {}},
        retained_targets={})
    journal.save_plan(database, plan)
    target_reprojection.record_projection(database, projection)
    purchase = dollars(filled="4.999", notional="4999", state=S.FILLED)
    filled = replace(purchase, identity=replace(purchase.identity, plan_id=plan.plan_id),
        filled_average_price=D(1000))
    journal.save_command(database, filled)
    native_fills(database, filled)
    monkeypatch.setattr(dual_plan_authority, "load_authority", lambda *_args, **_kwargs: {
        "plan_fingerprint": plan.fingerprint(), "shadow_state": before.to_dict(),
        "authority_sha256": "a" * 64})
    after, _ = case(entries=2)
    after.last_processed_session = plan.effective_session.isoformat()
    binding = SimpleNamespace(**DEPLOY.to_dict(), identity=DEPLOY)
    result = held_targets.build_basis(database, previous=plan, state=after, binding=binding,
        rollout=RolloutState(RolloutMode.CONTROLLER, 1, "a" * 64))
    assert result["targets"] == {"SEC-AAA": "4.999", "SEC-BBB": "0"}
    assert result["purchase_budgets"] == {"SEC-BBB": "5000"}
    assert target_reprojection.load_projection(database, plan_id=plan.plan_id) == projection


def test_partial_whole_fallback_carries_acquired_shares_and_original_dollars(database, monkeypatch):
    schema.ensure_schema(database)
    before, raw = case(entries=1)
    plan = owned_plan(raw, account_nav=D("20000"))
    initial = base(before, plan)
    projection = fractional_sizing.resolve(before, plan, initial, references(plan, initial),
        MarketBuyPolicy(True), baseline={"through_event_seq": 0, "commands": [], "holdings": {}},
        retained_targets={})
    journal.save_plan(database, plan)
    target_reprojection.record_projection(database, projection)
    partial = cmd(qty="9", filled="4", state=S.CANCELLED)
    partial = replace(partial, identity=replace(partial.identity, plan_id=plan.plan_id),
                      broker_order_id="whole-native", filled_average_price=D("120"))
    journal.save_command(database, partial)
    native_fills(database, partial)
    monkeypatch.setattr(dual_plan_authority, "load_authority", lambda *_args, **_kwargs: {
        "plan_fingerprint": plan.fingerprint(), "shadow_state": before.to_dict(),
        "authority_sha256": "a" * 64})
    after, _ = case(entries=1)
    after.last_processed_session = plan.effective_session.isoformat()
    authority = dict(state=after, binding=SimpleNamespace(**DEPLOY.to_dict(), identity=DEPLOY),
                     rollout=RolloutState(RolloutMode.CONTROLLER, 1, "a" * 64))
    archived = held_targets.build_basis(database, previous=plan, legacy_fractional=True, **authority)
    assert archived["targets"] == {AAA.security_id: "9"} and not archived["purchase_budgets"]
    assert held_targets.verify_basis(database, basis=archived, **authority) == {AAA.security_id: D(9)}
    current = held_targets.build_basis(database, previous=plan, **authority)
    retained = held_targets.verify_basis(database, basis=current, **authority)
    assert retained == {AAA.security_id: D(4)}
    successor = fractional_sizing.allocate(raw_targets={}, retained=retained,
        baseline={"holdings": {AAA.security_id: "4"}}, carry=current["purchase_budgets"],
        prices={AAA.security_id: D(150)}, intents=[], nav=D(20000), exposure=D(1), shadow_equity=D(100000))
    assert successor[1] == {AAA.security_id: {"budget": "519", "origin": "CONTINUING"}}


def test_zero_share_continuation_includes_native_reference_and_can_resolve(database, monkeypatch):
    schema.ensure_schema(database)
    state, raw = case(entries=0)
    plan = owned_plan(raw, target_basket={AAA.security_id: D(0)})
    journal.save_plan(database, plan)
    database.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES (%s,%s,%s::jsonb)",
        (dual_plan_authority.CURSOR_PREFIX + plan.plan_id, plan.decision_session,
         json.dumps({"held_share_targets": {"purchase_budgets": {AAA.security_id: "1000"}}})))
    monkeypatch.setattr(held_targets, "plan_sizing", lambda *_args, **_kwargs: ({AAA.security_id: D(0)}, ()))
    source_fixture(monkeypatch, plan)
    readonly = ReferenceConnection([(AAA.security_id, AAA.symbol, 100)])
    read_refs = protected_limits.build_references
    monkeypatch.setattr(protected_limits, "build_references",
        lambda _conn, **kw: read_refs(readonly, **kw))
    binding = SimpleNamespace(identity=DEPLOY)
    no_actions = lambda sid: None
    broker = DollarBroker()
    assert AAA.security_id in targets._preopen_active_security_ids(
        conn=database, plan=plan, commands=(), actions=no_actions)
    projected = targets._target_projection_or_refuse(database, state=state, plan=plan,
        binding=binding, broker=broker, through=plan.effective_session, actions=no_actions,
        target_actions=no_actions)
    assert projected.target_basket[AAA.security_id] == 0
    assert projected.opening_sizing["purchases"][AAA.security_id] == {"budget": "1000", "origin": "CONTINUING"}
    assert projected.opening_sizing["references"]["provider_asset_ids"][AAA.security_id] == "asset-a"

    from sentinel.execution import feed_inputs
    monkeypatch.setattr(feed_inputs, "metadata", lambda _conn: {})
    async def resolve_instrument(*, security_id, symbol):
        return BrokerInstrument(security_id, symbol, "asset-a")
    broker.resolve_instrument = resolve_instrument
    mapped = asyncio.run(targets._instrument_map(database, broker, state, plan,
        observation(), target_basket=projected.target_basket))
    assert mapped[AAA.security_id].broker_id == "asset-a"


def split_event(sid, symbol, when, numerator, denominator):
    value = D(numerator) / D(denominator)
    return reconcile.CorporateActionEvent(
        security_id=sid, ticker=symbol, session=when, action="split", value=value,
        contraticker=None, source_row_id=f"split-{when}", reason="authenticated scalar action",
        canonical_multiplier=value, canonical_numerator=numerator, canonical_denominator=denominator)


@pytest.mark.parametrize(("observed", "foreign"), [("0.033333333", ()), ("1", ()), ("7", ("SEC-AAA",))])
def test_repeating_split_entitlement_is_scoped_and_never_guesses_foreign_units(conn, observed, foreign):
    sid = AAA.security_id
    event = split_event(sid, AAA.symbol, date(2026, 8, 13), 1, 30)
    actions = reconcile.CorpusActionLookup(NOW.date(), {sid: ((event.session, event.canonical_multiplier),)},
                                            scalar_events=(event,))
    purchase = dollars(filled="1", state=S.FILLED)
    journal.save_command(conn, purchase)
    conn.execute("UPDATE sentinel_commands SET created_at=%s WHERE client_key=%s", (NOW, purchase.client_key))
    conn.commit()
    broker = DollarBroker()
    broker.now = calendar.session_window(event.session)[0] + timedelta(minutes=1)
    broker.seed_position(AAA, observed)
    result = asyncio.run(reconcile.reconcile(broker=broker, conn=conn, binding=None,
        deployment=DEPLOY, actions=actions))
    assert result.expected == {sid: Fraction(1, 30)}
    assert result.foreign_positions == foreign
    assert result.transport_ready == (not foreign)
    assert "1/30" in result.restricted_securities[sid] and not result.clean


def test_exact_target_survives_projection_and_later_becomes_tradable(database):
    schema.ensure_schema(database)
    state, raw = case(entries=0)
    sid = AAA.security_id
    plan = owned_plan(raw, target_basket={sid: D(1)})
    event = split_event(sid, AAA.symbol, plan.effective_session, 1, 30)
    before = target_reprojection.project_target(plan, through_session=event.session,
        action_multipliers={sid: event.canonical_multiplier}, action_evidence=(event.to_dict(),),
        minimum_quantity_increment=D("0.000000001"), fractional_entitlements={})
    projection = fractional_sizing.resolve(state, plan, before, references(plan, before), MarketBuyPolicy(True),
        baseline={"through_event_seq": 0, "commands": [], "holdings": {},
                  "pending_entitlements": {sid: "1/30"}}, retained_targets={sid: D(1)})
    target_reprojection.record_projection(database, projection)
    loaded = target_reprojection.load_projection(database, plan_id=plan.plan_id)
    assert loaded.pending_share_targets == {sid: "1/30"}
    assert projection.target_basket[sid] == 0
    assert fractional_progress.delta(database, projection=loaded, deployment=DEPLOY,
        security_id=sid, observation=observation("0.033333333")).classification.value == "NONE"
    followup = split_event(sid, AAA.symbol, date(2026, 8, 13), 30, 1)
    restored = target_reprojection.project_target(replace(plan, target_basket={sid: D(0)}),
        through_session=followup.session, action_multipliers={sid: D(30)}, action_evidence=(followup.to_dict(),),
        minimum_quantity_increment=D("0.000000001"), fractional_entitlements={sid: Fraction(1, 30)})
    assert restored.target_basket == {sid: D(1)} and not restored.pending_share_targets


def test_recovery_cannot_finish_a_dust_exit(database):
    schema.ensure_schema(database)
    state, raw = case(entries=0)
    plan = owned_plan(raw, target_basket={AAA.security_id: D(0)})
    initial = base(state, plan)
    projection = fractional_sizing.resolve(state, plan, initial, references(plan, initial),
        MarketBuyPolicy(True), baseline={"through_event_seq": 0, "commands": [],
        "holdings": {AAA.security_id: "0.0000000001"}}, retained_targets={})
    target_reprojection.record_projection(database, projection)
    with pytest.raises(target_reprojection.TargetProjectionRefused, match="DUST_RESIDUAL"):
        _actionable_projection_deltas(database, plan=plan, effective_session=plan.effective_session,
            observation=observation("0.0000000001"), minimum_quantity_increment=D("0.000000001"))
