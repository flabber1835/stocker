"""Identity reads belong to one synchronous classification, never permission."""
import asyncio
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal as D
from types import SimpleNamespace

import pytest
import psycopg

from sentinel import backup_runtime_authority, binding
from sentinel.config import SentinelConfig, build_execution_broker
from sentinel.execution import commands as commands, executor, journal
from sentinel.execution.contract import BrokerAccountIdentity, BrokerInstrument, BrokerObservation
from sentinel.execution.guarded import BrokerAuthorityRefused
from sentinel.execution.identity import CommandIdentity, DeploymentIdentity
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.reconcile import ReconciliationResult
from sentinel.execution.simulator import SimulatedBroker
from sentinel.execution.states import CommandState, RuntimeState
from live_authority_fixtures import live_fixture
from tests.sentinel.test_binding_and_handover import conn, pg  # noqa: F401
from tests.sentinel.test_issue_183_alpaca_hardening import Httpx
from tests.sentinel.test_url_selected_transport import LIVE, PAPER


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
    assert value.trace == ['binding', 'identify'] * 2
    candidates = [f'security-{i:02}' for i in range(15)]
    assert [row['delta'].security_id for row in value.authorizations] == candidates * 2
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


def test_changed_binding_at_final_pass_refuses_every_candidate(classification, monkeypatch):
    value = classification
    calls = []
    def binding(conn):
        calls.append(1)
        current = value.binding(conn)
        return replace(current, broker_account_id='different-account') if len(calls) == 2 else current
    monkeypatch.setattr(executor, '_binding', binding)
    result = value.run()
    assert set(result.refused) == {'security-00', 'security-01', 'security-02'}
    assert all('account binding mismatch' in reason for reason in result.refused.values())
    assert not result.submitted and not value.sent
    assert len(value.authorizations) == 6
    assert value.trace == ['binding', 'identify'] * 2


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
    assert len(calls) == 3 and value.trace == ['binding', 'identify'] * 2


@pytest.mark.parametrize('base_url', [PAPER, LIVE])
def test_native_account_change_after_preflight_refuses_before_journaling_or_post(conn, monkeypatch, base_url):
    # The ephemeral server has no external backup. The production advisory lock
    # and the two independent writers below remain part of the test.
    monkeypatch.setattr(backup_runtime_authority, 'require', lambda *_a, **_k: None)
    signed = live_fixture() if base_url == LIVE else None
    account = signed.subject.account_id if signed else 'private-paper-account'
    namespace = 'alpaca-live' if signed else 'alpaca'
    owned = binding.bind(conn, deployment_id='private-native-open', broker=namespace, broker_account_id=account)
    account_key = 'id' if signed else 'account_number'
    http = Httpx(routes={'/v2/account': {account_key: account}})
    raw = build_execution_broker(SentinelConfig.from_env({
        'ALPACA_BASE_URL': base_url, 'ALPACA_API_KEY': 'fixture', 'ALPACA_SECRET_KEY': 'fixture'}),
        resolve_security_id=lambda symbol, *_: symbol, live_admission=signed.admission if signed else None)
    raw._http_provider = lambda: http
    basket = {'SENTINEL:BIL': D(2)}
    plan = ExecutionPlan('private-native-open', DAY, DAY, D(0), target_basket=basket, data_version=1,
        deployment_id=owned.deployment_id, broker=namespace, broker_account_id=account, takeover_epoch=1)
    executor.adopt_plan(conn, plan)
    observation = BrokerObservation(observed_at=datetime(2026, 10, 19, 13, 31, tzinfo=timezone.utc),
                                    account_identity=BrokerAccountIdentity(namespace, account))
    # Supply a clean flat book so the test can change the real native account response
    # at the precise boundary between candidate classification and final authorization.
    async def reconcile(**_):
        return ReconciliationResult(runtime_state=RuntimeState.RUNNING, observation=observation)
    monkeypatch.setattr(executor.R, 'reconcile', reconcile)

    with psycopg.connect(conn.info.dsn) as contender:
        async def change_native_account(_):
            assert [call[:2] for call in http.calls] == [('GET', '/v2/account')]
            with pytest.raises(journal.WriterLockUnavailable):
                binding.adopt_restored(contender, expected_account=account, observed=observation.account_identity)
            http.routes['/v2/account'] = {account_key: '00000000-0000-4000-8000-000000000002'}

        outcome = asyncio.run(executor.execute_session(broker=raw, conn=conn, deployment=owned.identity,
            plan=plan, today=DAY, instruments={'SENTINEL:BIL': BrokerInstrument('SENTINEL:BIL', 'BIL', 'asset-bil')},
            increase_authority=change_native_account))
        assert set(outcome.refused) == set(basket)
        assert 'account binding mismatch' in outcome.refused['SENTINEL:BIL']
        assert not outcome.submitted and not journal.load_commands(conn, owned.identity)
        assert [call[:2] for call in http.calls] == [('GET', '/v2/account')] * 2
        assert binding.require(conn).identity == owned.identity
        adopted = binding.adopt_restored(contender, expected_account=account, observed=observation.account_identity)
        assert adopted.takeover_epoch == owned.takeover_epoch + 1
