"""Audit-only witnesses of the pinned production cash-capability boundary.

These assert observed baseline behavior, not remediation acceptance. No broker
transport, production credentials, or production state are used.
"""
import asyncio
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal as D
from types import SimpleNamespace

import pytest
from sentinel import schema
from sentinel.feed import store
from sentinel.execution import alpaca, journal
from sentinel.execution.contract import BrokerAccountIdentity, BrokerAccountSnapshot, BrokerObservation, Completeness
from sentinel.execution.guarded import GuardedExecutionBroker, ExecutionBrokerGuard, PaperPreparationGrant
from sentinel.execution.identity import DeploymentIdentity
from sentinel.execution.plan import ExecutionPlan
from sentinel.paper.cash import _broker_cash_state_or_refuse, _cash_authority_or_refuse
from sentinel.paper.model import PaperActivationRefused, PaperRetryableRefused
from tests.support.postgres import _EphemeralPostgres

DEPLOY = DeploymentIdentity('audit399', 'alpaca', 'AUDIT-CASH', 1)
NOW = datetime(2026, 9, 17, 14, 0, tzinfo=timezone.utc)

@pytest.fixture(scope='module')
def pg():
    p = _EphemeralPostgres()
    p.start()
    yield p
    p.stop()

@pytest.fixture
def conn(pg):
    c = store.connect(pg.sync_dsn)
    schema.ensure_schema(c)
    yield c
    c.close()

async def no_op(*args):
    pass

def broker():
    def forbidden_transport():
        raise AssertionError('no broker transport is permitted in this witness')
    inner = alpaca.AlpacaExecutionBroker(api_key='AUDIT-ONLY', secret_key='AUDIT-ONLY',
        base_url='https://paper-api.alpaca.markets', http_provider=forbidden_transport)
    return GuardedExecutionBroker(inner=inner,
        grant=PaperPreparationGrant(expected_account='AUDIT-CASH', decision_session=NOW.date()),
        guard=ExecutionBrokerGuard(no_op, no_op, no_op))

def plan(pid):
    return ExecutionPlan(plan_id=pid, decision_session=NOW.date(), effective_session=NOW.date(),
        target_exposure=D(0), target_basket={}, data_version=1, deployment_id=DEPLOY.deployment_id,
        broker=DEPLOY.broker, broker_account_id=DEPLOY.broker_account_id, takeover_epoch=1,
        account_nav=D(1000), account_cash=D(1000), cash_residual=D(1000))

def evidence(cash):
    identity = BrokerAccountIdentity(broker='alpaca', account_id='AUDIT-CASH')
    account = BrokerAccountSnapshot(identity=identity, equity=cash, cash=cash,
        buying_power=cash, multiplier=D(1), status='ACTIVE')
    observation = BrokerObservation(orders=(), positions=(), observed_at=NOW,
        completeness=Completeness.COMPLETE, account_identity=identity)
    return account, observation

def test_real_adapter_keeps_cash_and_close_authority_quarantined():
    b = broker()
    assert not b.supports_account_cash_activities
    assert not b.supports_account_close_valuation
    assert not b.supports_account_fill_interval_evidence
    state = asyncio.run(_broker_cash_state_or_refuse(None, broker=b,
        binding=SimpleNamespace(broker='alpaca', broker_account_id='AUDIT-CASH'), through=NOW))
    assert state is None

@pytest.mark.parametrize('event,amount', [('dividend', '25'), ('fee','-2'), ('interest','5'),
    ('deposit','100'), ('withdrawal','-100'), ('cash_in_lieu','3')])
def test_non_fill_cash_blocks_next_plan_and_survives_reload(conn, pg, event, amount):
    p = plan('cash-' + event)
    journal.save_plan(conn, p)
    actual_cash = D(1000) + D(amount)  # independent account cash identity
    account, observation = evidence(actual_cash)
    for c in [conn, store.connect(pg.sync_dsn)]:
        try:
            loaded = journal.load_plan(c, p.plan_id)
            with pytest.raises(PaperActivationRefused, match='not explained'):
                _cash_authority_or_refuse(c, plan=loaded, deployment=DEPLOY,
                    account=account, observation=observation, activity_state=None,
                    permit_new_activity=True)
            assert journal.load_plan(c, p.plan_id).account_cash == D(1000)
        finally:
            if c is not conn:
                c.close()
    print(event, 'oracle_cash=', actual_cash, 'production=PaperActivationRefused after reload')

def test_account_endpoint_grace_expires_and_cannot_explain_cash_event(conn, pg):
    p = plan('cash-endpoint-grace')
    journal.save_plan(conn, p)
    account, observation = evidence(D(1025))
    with pytest.raises(PaperRetryableRefused):
        _cash_authority_or_refuse(conn, plan=p, deployment=DEPLOY, account=account,
            observation=observation, endpoint_lag_observed_at=NOW)
    restarted = store.connect(pg.sync_dsn)
    try:
        with pytest.raises(PaperActivationRefused, match='not explained'):
            _cash_authority_or_refuse(restarted, plan=journal.load_plan(restarted,p.plan_id),
                deployment=DEPLOY, account=account, observation=observation,
                endpoint_lag_observed_at=NOW+timedelta(seconds=121))
    finally:
        restarted.close()
