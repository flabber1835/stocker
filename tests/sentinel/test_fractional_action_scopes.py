"""Corporate-action evidence scopes share restrictions and market funding."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal as D

import pytest

from sentinel import binding, schema
from sentinel.core.decision import DEFENSIVE_SECURITY_ID
from sentinel.execution import executor, fractional_sizing, journal, reconcile, target_reprojection
from sentinel.execution.commands import Command
from sentinel.execution.contract import BrokerInstrument, Side
from sentinel.execution.identity import CommandIdentity
from sentinel.execution.market_buy_policy import MarketBuyPolicy
from sentinel.execution.states import CommandState as S, RuntimeState
from sentinel.feed import calendar
from sentinel.paper.cash import _cash_authority_or_refuse
from sentinel.paper.model import PaperActivationRefused
from sentinel.paper.reconciliation_evidence import _settled_account_evidence_bracket
from tests.sentinel.test_fractional_continuity import split_event
from tests.sentinel.test_fractional_execution import AAA, DEPLOY, NOW, dollars
from tests.sentinel.test_fractional_flow import DollarBroker, fractional_environment
from tests.sentinel.test_journal_and_reconcile import conn
from tests.sentinel.test_limit_day_sizing import references
from tests.sentinel.test_market_day_execution import DEPLOYMENT, wrapper
from tests.sentinel.test_order_terms_schema import database, pg
from tests.v5.test_opening import case


@pytest.mark.parametrize("event_sid,before_ownership,observed,restricted", [
    ("SEC-RETIRED", False, "1", False),
    (AAA.security_id, True, "1", False),
    (AAA.security_id, False, "1", True),
    (None, False, "1", True),
    ("SEC-RETIRED", False, "7", False),
    (AAA.security_id, False, "7", True),
])
def test_material_action_needs_owned_identity_and_does_not_explain_quantity(
        conn, event_sid, before_ownership, observed, restricted):
    event_day = NOW.date() + timedelta(days=-1 if before_ownership else 1)
    event = reconcile.CorporateActionEvent(
        event_sid, AAA.symbol, event_day, "merger", None, None,
        "published-merger", "unsupported share action")
    actions = reconcile.CorpusActionLookup(
        NOW.date() - timedelta(days=7), {},
        unsupported_events=(event,) if event_sid else (),
        unresolved_events=(event,) if event_sid is None else ())
    purchase = dollars(filled="1", state=S.FILLED)
    journal.save_command(conn, purchase)
    conn.execute("UPDATE sentinel_commands SET created_at=%s WHERE client_key=%s", (NOW, purchase.client_key))
    conn.commit()
    broker = DollarBroker()
    broker.now = calendar.session_window(NOW.date() + timedelta(days=1))[0] + timedelta(minutes=1)
    broker.seed_position(AAA, observed)
    result = asyncio.run(reconcile.reconcile(
        broker=broker, conn=conn, binding=None, deployment=DEPLOY, actions=actions))
    assert result.restricted_securities.keys() == ({AAA.security_id} if restricted else set())
    if observed == "1":
        assert result.transport_ready and result.clean is not restricted
    else:
        assert result.runtime_state is RuntimeState.FOREIGN_ACTIVITY
        assert result.foreign_positions == (AAA.security_id,) and not result.transport_ready


@pytest.mark.parametrize("exit_position,fail_cash", [(False, False), (True, False), (False, True)])
def test_scoped_market_funding_preserves_cash_and_reduction_barriers(database, exit_position, fail_cash):
    async def run():
        schema.ensure_schema(database)
        bound = binding.bind(database, deployment_id=DEPLOYMENT.deployment_id, broker=DEPLOYMENT.broker,
                             broker_account_id=DEPLOYMENT.broker_account_id)
        state, original = case(entries=0, sale=True)
        plan = replace(original, deployment_id=DEPLOYMENT.deployment_id, broker=DEPLOYMENT.broker,
                       broker_account_id=DEPLOYMENT.broker_account_id, takeover_epoch=1,
                       target_basket={"SEC-X": D(0 if exit_position else 1), DEFENSIVE_SECURITY_ID: D(1)})
        plan = replace(plan, plan_id="sentinel-" + plan.fingerprint())
        core = BrokerInstrument("SEC-X", "X", "sim-asset-SEC-X")
        sleeve = BrokerInstrument(DEFENSIVE_SECURITY_ID, "BIL", "sim-asset-" + DEFENSIVE_SECURITY_ID)
        event = split_event(core.security_id, core.symbol, plan.effective_session, 1, 2)
        actions = reconcile.CorpusActionLookup(
            plan.decision_session - timedelta(days=7),
            {core.security_id: ((event.session, event.canonical_multiplier),)}, scalar_events=(event,))
        raw = target_reprojection.project_target(plan, through_session=plan.effective_session,
            action_multipliers={core.security_id: event.canonical_multiplier}, action_evidence=(event.to_dict(),),
            minimum_quantity_increment=D("0.000000001"), fractional_entitlements={})
        retained = {} if exit_position else {core.security_id: D(1)}
        projection = fractional_sizing.resolve(state, plan, raw, references(plan, raw), MarketBuyPolicy(True),
            baseline={"through_event_seq": 0, "commands": [], "holdings": {core.security_id: "0.5"}},
            retained_targets=retained)
        journal.save_plan(database, plan)
        target_reprojection.record_projection(database, projection)
        own = Command(CommandIdentity(DEPLOYMENT, "prior", core.security_id), core, Side.BUY, D(1),
                      filled_quantity=D(1), filled_average_price=D(100), state=S.FILLED,
                      broker_order_id="prior-buy")
        journal.save_command(database, own)
        prior_open, _ = calendar.session_window(plan.decision_session)
        opened, _ = calendar.session_window(plan.effective_session)
        database.execute("UPDATE sentinel_commands SET created_at=%s WHERE client_key=%s", (prior_open, own.client_key))
        database.execute("UPDATE sentinel_account_binding SET established_at=%s", (opened,))
        database.commit()
        cash = plan.account_cash - (D(2) if fail_cash else D(0))
        inner = DollarBroker(cash=cash, buying_power=cash)
        inner.now = opened + timedelta(seconds=60)
        inner.seed_position(core, "1")  # broker still reports pre-split units
        broker = wrapper(inner)
        funding_reads = []

        async def funding(initial):
            funding_reads.append(initial)
            evidence = dict(conn=database, broker=broker, binding=bound, expected_account=DEPLOYMENT.broker_account_id,
                            deployment=DEPLOYMENT, initial_result=initial, actions=actions,
                            dual_mode=True, clock=lambda: inner.now)
            with pytest.raises(PaperActivationRefused, match="clean reconciliation"):
                await _settled_account_evidence_bracket(**evidence)
            rec, account, activity, *_ = await _settled_account_evidence_bracket(**evidence, allow_restrictions=True)
            assert rec.transport_ready and not rec.clean
            _cash_authority_or_refuse(database, plan=plan, deployment=DEPLOYMENT,
                account=account, observation=rec.observation, activity_state=activity)

        async def execute():
            return await executor._execute_session_locked(broker=broker, conn=database, deployment=DEPLOYMENT,
                plan=plan, instruments={core.security_id: core, sleeve.security_id: sleeve}, today=plan.effective_session,
                actions=actions, target_projection=projection, min_increment=D("0.000000001"),
                informational_current_book=True, increase_reconciliation_authority=funding)

        with journal.writer_lock(database, recovery_only=True):
            if fail_cash:
                with pytest.raises(PaperActivationRefused, match="is not explained by plan baseline"):
                    await execute()
                assert len(funding_reads) == 1 and not inner.dollars
                return
            result = await execute()
        assert result.reconciliation.expected[core.security_id] == D("0.5")
        assert core.security_id in result.restricted_securities
        if exit_position:
            assert not funding_reads and not result.submitted and not inner.dollars
            assert core.security_id in result.deferred and sleeve.security_id in result.deferred
            assert "restricted reductions" in result.detail
        else:
            assert len(funding_reads) == 1, result.to_dict()
            command, = result.submitted
            assert command.security_id == sleeve.security_id and command.side is Side.BUY
            assert command.quantity is None and command.notional == inner.dollars[command.client_key]

    asyncio.run(run())
