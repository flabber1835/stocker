"""Identity reads belong to one synchronous classification, never permission."""
import asyncio
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from sentinel.execution import commands as commands, executor, journal
from sentinel.execution.contract import BrokerAccountIdentity, BrokerInstrument, BrokerObservation
from sentinel.execution.guarded import BrokerAuthorityRefused
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.reconcile import ReconciliationResult
from sentinel.execution.simulator import SimulatedBroker
from sentinel.execution.states import CommandState, RuntimeState


DEPLOYMENT = DeploymentIdentity('classification-test', 'sim', 'paper-account', 1)
DAY = date(2026, 10, 19)


@pytest.fixture
def classification(monkeypatch):
    """Canonical classification/delta/command logic; named DB/transport fixtures."""
    account = BrokerAccountIdentity('sim', 'paper-account')
    broker = SimulatedBroker(account=account)
    trace, authorizations, sent, outcomes = [], [], [], []
    def binding(_):
        trace.append('binding')
        return DEPLOYMENT
    monkeypatch.setattr(executor, '_binding', binding)
    async def identify():
        trace.append('identify')
        if outcomes:
            value = outcomes.pop(0)
            if isinstance(value, BaseException):
                raise value
            return value
        return broker.account
    monkeypatch.setattr(broker, 'identify_account', identify)
    observation = BrokerObservation(observed_at=datetime(2026, 10, 19, 13, 31, tzinfo=timezone.utc),
                                    account_identity=account)
    async def reconcile(**kwargs):
        return ReconciliationResult(runtime_state=RuntimeState.RUNNING, observation=observation)
    monkeypatch.setattr(executor.R, 'reconcile', reconcile)
    monkeypatch.setattr(journal, 'in_flight_commands', lambda *_: ())
    authorize = commands.authorize
    def checked(**kwargs):
        authorizations.append(kwargs)
        return authorize(**kwargs)
    monkeypatch.setattr(commands, 'authorize', checked)
    def command(*, delta, deployment, plan_id, instrument, **kwargs):
        return commands.build(delta=delta,
            identity=CommandIdentity(deployment=deployment, plan_id=plan_id, security_id=delta.security_id),
            instrument=instrument), False
    monkeypatch.setattr(executor, '_command_for_delta', command)
    async def send(conn, broker, command, **kwargs):
        sent.append(command)
        return replace(command, state=CommandState.ACKNOWLEDGED)
    monkeypatch.setattr(executor, '_persist_and_send', send)
    def run(*, size=3, zero=False, restricted=False, increase_authority=None):
        basket = {f'security-{i:02}': D(0 if zero else 1) for i in range(size)}
        instruments = {sid:BrokerInstrument(sid, sid, 'asset-'+sid) for sid in basket}
        plan = ExecutionPlan(plan_id='classification-plan', decision_session=DAY, effective_session=DAY,
            target_exposure=D(1), target_basket=basket, data_version=1)
        return asyncio.run(executor._execute_session_locked(
            broker=broker, conn=object(), deployment=DEPLOYMENT, plan=plan,
            instruments=instruments, today=DAY, actions=None, target_projection=None,
            min_increment=D(1), increase_authority=increase_authority,
            security_restrictions={sid:'restricted' for sid in basket} if restricted else None))
    return SimpleNamespace(run=run, broker=broker, trace=trace, authorizations=authorizations,
                           sent=sent, outcomes=outcomes, binding=binding)


def test_one_successful_identity_per_pass_preserves_every_candidate_authorization(classification):
    value = classification
    result = value.run(size=15)
    assert len(result.submitted) == 15
    assert value.trace.count('identify') == 2
    assert value.trace.count('binding') == len(value.authorizations) == 30
    assert value.trace[:2] == ['binding', 'identify']
    assert all(row['observation'] is value.authorizations[0]['observation'] for row in value.authorizations)


def test_failed_identity_read_refuses_one_candidate_then_retries(classification):
    value = classification
    value.outcomes.append(RuntimeError('temporary account endpoint failure'))
    result = value.run()
    assert set(result.refused) == {'security-00'}
    assert 'temporary account endpoint failure' in result.refused['security-00']
    assert [row.security_id for row in result.submitted] == ['security-01', 'security-02']
    assert value.trace.count('identify') == 3


@pytest.mark.parametrize('pass_index', [0, 1])
def test_authority_refusal_aborts_before_any_command(classification, pass_index):
    value = classification
    value.outcomes[:] = [value.broker.account] * pass_index + [BrokerAuthorityRefused('revoked')]
    with pytest.raises(BrokerAuthorityRefused, match='revoked'):
        value.run()
    assert not value.sent
    assert value.trace.count('identify') == pass_index + 1


def test_fresh_binding_is_read_and_compared_for_every_candidate(classification, monkeypatch):
    value = classification
    calls = []
    def binding(conn):
        calls.append(1)
        current = value.binding(conn)
        return replace(current, broker_account_id='different-account') if len(calls) == 2 else current
    monkeypatch.setattr(executor, '_binding', binding)
    result = value.run()
    assert set(result.refused) == {'security-01'}
    assert 'account binding mismatch' in result.refused['security-01']
    assert [row.security_id for row in result.submitted] == ['security-00', 'security-02']
    assert len(calls) == len(value.authorizations) == 5
    assert value.trace.count('identify') == 2


def test_mismatched_identified_account_never_creates_permission(classification):
    value = classification
    value.broker.account = BrokerAccountIdentity('sim', 'different-account')
    result = value.run()
    assert set(result.refused) == {'security-00', 'security-01', 'security-02'}
    assert all('account binding mismatch' in reason for reason in result.refused.values())
    assert not value.sent and value.trace.count('identify') == 1


def test_final_pass_reads_identity_again_after_preflight(classification):
    value = classification
    async def change_account(observation):
        value.broker.account = BrokerAccountIdentity('sim', 'changed-after-preflight')
    result = value.run(increase_authority=change_account)
    assert not value.sent
    assert len(result.refused) == 3 and value.trace.count('identify') == 2


@pytest.mark.parametrize('skip', ['zero', 'restricted'])
def test_empty_classification_never_identifies_account(classification, skip):
    value = classification
    result = value.run(**{skip:True})
    assert not result.submitted and not value.authorizations
    assert value.trace == []


def test_first_binding_failure_still_precedes_any_identity_read(classification, monkeypatch):
    value = classification
    calls = []
    def binding(conn):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError('binding temporarily unavailable')
        return value.binding(conn)
    monkeypatch.setattr(executor, '_binding', binding)
    result = value.run()
    assert set(result.refused) == {'security-00'}
    assert [row.security_id for row in result.submitted] == ['security-01', 'security-02']
    assert len(calls) == 5 and value.trace.count('identify') == 2
