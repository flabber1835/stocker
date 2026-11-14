"""Eligibility changes and corporate actions do not change ownership intent."""
import asyncio
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from sentinel import schema
from sentinel.execution import commands, fractional_orders, fractional_progress, journal
from sentinel.execution.contract import BrokerAssetRules, Side
from sentinel.execution.guarded import OrderEvidenceNotReady
from sentinel.execution.reconcile import CorpusActionLookup
from sentinel.execution.states import CommandState as S
from sentinel.execution.target_reprojection import TargetProjectionRefused
from tests.sentinel.test_order_terms_schema import pg, database
from tests.sentinel.test_fractional_flow import DollarBroker, fractional_environment
from tests.sentinel.test_fractional_execution import (
    AAA, DEPLOY, NOW, cmd, observation, projection,
)
from tests.sentinel.test_market_day_execution import wrapper, set_clock, market_instruments
from tests.sentinel.test_limit_day_transport import broker_for
from tests.sentinel.test_issue_183_alpaca_hardening import INSTRUMENT, run
from sentinel.execution.alpaca_asset_id import AssetIdAlpacaExecutionBroker


@pytest.mark.parametrize("flag", [False, True])
def test_native_eligibility_is_an_explicit_current_boolean(flag):
    broker, http = broker_for(AssetIdAlpacaExecutionBroker, routes={"/v2/assets/" + INSTRUMENT.broker_id: {
        "id": INSTRUMENT.broker_id, "symbol": INSTRUMENT.symbol,
        "status": "active", "tradable": True, "fractionable": flag}})
    rules = run(broker.asset_rules(instrument=INSTRUMENT))
    assert rules.instrument == INSTRUMENT and rules.fractionable is flag
    assert http.calls[0][1].endswith(INSTRUMENT.broker_id)


@pytest.mark.parametrize("flag", [None, "false", "true", 0, 1])
def test_missing_or_malformed_eligibility_never_becomes_whole_fallback(flag):
    from sentinel.execution.alpaca import MalformedBrokerPayload
    broker, _ = broker_for(AssetIdAlpacaExecutionBroker, routes={"/v2/assets/" + INSTRUMENT.broker_id: {
        "id": INSTRUMENT.broker_id, "symbol": INSTRUMENT.symbol,
        "status": "active", "tradable": True, "fractionable": flag}})
    with pytest.raises(MalformedBrokerPayload, match="rules"):
        run(broker.asset_rules(instrument=INSTRUMENT))


def test_unsellable_fraction_is_explicit_and_whole_part_can_reduce(database):
    schema.ensure_schema(database)
    inner = DollarBroker()
    inner.fractionable = False
    security = market_instruments()["SEC-AAA"]
    # The owned sell denomination depends on current rules, not on how it was bought.
    delta = commands.compute_delta(security_id=AAA.security_id, desired=D(0),
        observation=observation("2.123456789"), min_increment=D("0.000000001"))
    chosen, residual = asyncio.run(fractional_orders.choose(inner, conn=database,
        deployment=DEPLOY, projection=projection(), delta=delta, instrument=security))
    assert chosen.side is Side.SELL and chosen.quantity == 2
    assert residual == "FRACTIONAL_SELL_RESIDUAL: 0.123456789"
    dust = commands.compute_delta(security_id=AAA.security_id, desired=D(0),
        observation=observation("0.123456789"), min_increment=D("0.000000001"))
    with pytest.raises(OrderEvidenceNotReady, match="FRACTIONAL_SELL_RESIDUAL"):
        asyncio.run(fractional_orders.choose(inner, conn=database,
            deployment=DEPLOY, projection=projection(), delta=dust, instrument=security))
    inner.fractionable = True
    exact, residual = asyncio.run(fractional_orders.choose(inner, conn=database,
        deployment=DEPLOY, projection=projection(), delta=delta, instrument=security))
    assert exact.quantity == D("2.123456789") and residual is None


def test_whole_market_fallback_uses_quote_and_later_eligibility_does_not_top_up(database):
    schema.ensure_schema(database)
    inner = DollarBroker()
    inner.fractionable = False
    set_clock(inner, 60)
    security = market_instruments()["SEC-AAA"]
    allocation = replace(projection(), through_session=inner.now.date())
    delta = fractional_progress.delta(database, projection=allocation, deployment=DEPLOY,
        security_id=AAA.security_id, observation=observation())
    chosen, residual = asyncio.run(fractional_orders.choose(inner, conn=database,
        deployment=DEPLOY, projection=allocation, delta=delta, instrument=security))
    # $999 principal / ($100 ask plus 1% buffer) funds nine whole shares.
    assert chosen.notional is None and chosen.quantity == 9 and residual is None
    outcome = asyncio.run(wrapper(inner).submit(client_key="fallback", instrument=security,
        side=Side.BUY, quantity=chosen.quantity))
    assert outcome.state is S.ACKNOWLEDGED and not inner.dollars
    journal.save_command(database, replace(cmd(qty="9", filled="9", state=S.FILLED),
        filled_average_price=D(100)))
    inner.fractionable = True
    completed = fractional_progress.derive(database, projection=allocation, deployment=DEPLOY)
    assert completed.targets[AAA.security_id] == 9 and not completed.budgets
    assert fractional_progress.delta(database, projection=allocation, deployment=DEPLOY,
        security_id=AAA.security_id, observation=observation("9")).classification is commands.DeltaClass.NONE


def test_eligibility_evidence_expiring_during_authority_checks_prevents_post():
    inner = DollarBroker()
    set_clock(inner, 60)
    async def delayed_authority(*args):
        inner.now += timedelta(seconds=31)
    with pytest.raises(OrderEvidenceNotReady, match="stale"):
        asyncio.run(wrapper(inner, before_mutation=delayed_authority).submit(
            client_key="expire", instrument=market_instruments()["SEC-AAA"],
            side=Side.BUY, quantity=None, notional=D(100)))
    assert not inner.dollars


def test_recovery_does_not_age_the_frozen_baseline_through_a_later_split(database):
    schema.ensure_schema(database)
    previous = replace(cmd(plan="previous", qty="1.25", filled="1.25", state=S.FILLED),
                       filled_average_price=D(100), created_at=NOW - timedelta(days=2))
    journal.save_command(database, previous)
    database.execute("UPDATE sentinel_commands SET created_at=%s WHERE client_key=%s",
                     (previous.created_at, previous.client_key))
    database.commit()
    plan = SimpleNamespace(plan_id="plan-1", effective_session=date(2026, 8, 12))
    initial = CorpusActionLookup(date(2026, 8, 10), {AAA.security_id: ((date(2026, 8, 12), D(2)),)})
    saved = fractional_progress.baseline(database, deployment=DEPLOY, plan=plan, actions=initial)
    assert saved["holdings"][AAA.security_id] == "2.5"
    later = replace(initial, events={AAA.security_id: (
        (date(2026, 8, 12), D(2)), (date(2026, 8, 13), D(3)))})
    assert fractional_progress.baseline(database, deployment=DEPLOY, plan=plan,
        actions=later, saved=saved) == saved
    from sentinel.paper.targets import _post_projection_action_multipliers
    assert _post_projection_action_multipliers(projection(), later) == {AAA.security_id: D(3)}


@pytest.mark.parametrize("shares", ["72", "72.123456789"])
def test_unchanged_episode_keeps_acquired_whole_or_fractional_shares(shares):
    from tests.sentinel.test_persistent_account_share_targets import state, build, carry, SID
    from sentinel.execution.target_reprojection import project_target
    before, after = state(), state(equity="60000", session="2026-08-12")
    previous = build(before).plan
    acquired = replace(project_target(previous, through_session=previous.effective_session,
        action_multipliers={}, minimum_quantity_increment=D("0.000000001")), target_basket={SID: D(shares)})
    targets = carry(previous, before, after, acquired)
    assert targets[SID] == D(shares)
    assert build(after, targets=targets, price="45.92").plan.target_basket[SID] == D(shares)


def test_unfulfilled_dollars_cannot_claim_completion():
    witness = {"blocked": {}, "remaining_dollars": {"SEC-A": "2"}}
    with pytest.raises(TargetProjectionRefused, match="unfulfilled"):
        fractional_progress.require_completed(witness)
    fractional_progress.require_completed({"blocked": {}, "remaining_dollars": {"SEC-A": "1.99"}})
    with pytest.raises(TargetProjectionRefused):
        fractional_progress.require_completed({"blocked": {"SEC-A": "FILL_PRINCIPAL_PENDING"}, "remaining_dollars": {}})
