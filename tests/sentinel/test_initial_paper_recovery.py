"""Actual PostgreSQL, guarded read-only broker, atomicity and refusal cases."""
import asyncio
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sentinel import binding, empty_account
from sentinel.automation import store
from sentinel.execution import alpaca, initial_paper_recovery as recovery
from sentinel.execution.contract import (BrokerAccountIdentity, Completeness, IncompleteObservation,
    BrokerPosition, BrokerOrder, BrokerInstrument, Side)
from sentinel.execution.states import CommandState
from sentinel.execution.guarded import GuardedExecutionBroker, ExecutionBrokerGuard, PaperPreparationGrant
from sentinel.execution.simulator import SimulatedBroker
from sentinel.paper.model import PaperActivationRefused
from tests.sentinel.test_issue282_restore_upgrade_fence import conn, pg, ACCOUNT_NUMBER


@pytest.fixture
def appliance(conn, monkeypatch):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'isolated-initial-paper-recovery-key-'*2)
    sid = conn.execute('SELECT (pg_control_system()).system_identifier::text').fetchone()[0]
    conn.rollback()
    request = dict(system_identifier=sid, actor='owner', reason='explicit unchanged paper appliance',
                   same_host_confirmed=True, retain_current_paper_credentials=True)
    inner = SimulatedBroker(account=BrokerAccountIdentity('alpaca', ACCOUNT_NUMBER),
                            cash=Decimal('50000'), equity=Decimal('50000'), now=datetime.now(timezone.utc))
    checks = []
    async def check(*args):
        checks.append(args)
    grant = PaperPreparationGrant(expected_account=ACCOUNT_NUMBER, decision_session=date.today())
    broker = GuardedExecutionBroker(inner=inner, grant=grant,
        guard=ExecutionBrokerGuard(before_read=check, after_read=check, before_mutation=check))
    return request, inner, broker, grant, checks


def invoke(conn, appliance, authority=lambda: 'a'*64):
    request, _, broker, grant, _ = appliance
    return asyncio.run(recovery.authorize(conn, broker=broker, grant=grant,
        request=request, fresh_authority=authority))


def anchor_rows(conn):
    value = conn.execute('SELECT cursor_name,state FROM sentinel_processed_sessions WHERE cursor_name=ANY(%s) ORDER BY cursor_name',
                        ([alpaca._DB_CURSOR, recovery.CURSOR],)).fetchall()
    conn.rollback()
    return value


def test_explicit_initial_recovery_retains_binding_keys_and_zero_transport(conn, appliance):
    before = binding.require(conn)
    receipt = invoke(conn, appliance)
    assert binding.require(conn) == before
    assert receipt['credential_policy'] == 'RETAINED_CURRENT_PAPER' and receipt['authority_effect'] == 'NONE'
    assert receipt['broker_mutations'] == 0 and not receipt['resumed']
    assert len(anchor_rows(conn)) == 2 and alpaca.upgrade_restore_reason(conn) == ''
    assert appliance[1].calls.count('account_snapshot') == 2
    assert appliance[1].calls.count('list_orders') == 4
    assert len(appliance[4]) == 8
    assert not store.load_control(conn).enabled and store.load_control(conn).kill_switch_engaged
    assert conn.execute('SELECT COUNT(*) FROM sentinel_commands').fetchone()[0] == 0
    conn.rollback()


def test_lost_acknowledgement_resumes_exact_authenticated_anchor_without_new_reads(conn, appliance):
    original = invoke(conn, appliance)
    calls = list(appliance[1].calls)
    before = anchor_rows(conn)
    resumed = invoke(conn, appliance)
    assert resumed == dict(original, resumed=True)
    assert before == anchor_rows(conn)
    assert appliance[1].calls == calls


@pytest.mark.parametrize('defect', ['broker', 'cluster', 'epoch', 'timeline', 'enabled', 'lease', 'unknown', 'no-backups', 'existing-anchor'])
def test_local_refusals_precede_broker_and_leave_no_recovery_receipt(conn, appliance, monkeypatch, defect):
    request, inner, _, _, _ = appliance
    if defect == 'broker':
        conn.execute("UPDATE sentinel_account_binding SET broker='sim' WHERE id=1"); conn.commit()
    elif defect == 'cluster': request['system_identifier'] = '123456789'
    elif defect == 'epoch':
        conn.execute('UPDATE sentinel_account_binding SET takeover_epoch=2 WHERE id=1'); conn.commit()
    elif defect == 'timeline':
        original = alpaca.database_incarnation
        def changed(*args, **kwargs):
            prior, current, bound = original(*args, **kwargs)
            return prior, dict(current, timeline_id=2), bound
        monkeypatch.setattr(alpaca, 'database_incarnation', changed)
    elif defect == 'enabled':
        from tests.sentinel.test_automation_store import identity
        store.activate(conn, binding=identity(), actor='test', reason='live control')
    elif defect == 'lease':
        conn.execute("UPDATE sentinel_automation_lease SET holder_id='foreign',fence_token=1,control_generation=1,acquired_at=NOW(),heartbeat_at=NOW(),expires_at=NOW()+INTERVAL '1 minute' WHERE id=1"); conn.commit()
    elif defect == 'unknown':
        conn.execute("INSERT INTO sentinel_commands(client_key,plan_id,security_id,deployment_id,broker,broker_account_id,takeover_epoch,symbol,side,quantity,state) VALUES('unknown','p','s','nas-1','alpaca',%s,1,'AAA','BUY',1,'UNKNOWN')", (ACCOUNT_NUMBER,)); conn.commit()
    elif defect == 'no-backups':
        conn.execute('DELETE FROM sentinel_backup_recovery_markers'); conn.commit()
    elif defect == 'existing-anchor': alpaca.database_incarnation(conn)
    before = anchor_rows(conn)
    with pytest.raises(PaperActivationRefused): invoke(conn, appliance)
    assert anchor_rows(conn) == before and not inner.calls


@pytest.mark.parametrize('defect', ['partial', 'position', 'order', 'cash', 'blocked', 'wrong-account', 'stale', 'unstable', 'revoked'])
def test_broker_and_fresh_authority_refusals_never_write_anchor(conn, appliance, defect):
    _, inner, broker, _, _ = appliance
    observed = broker.observe
    instrument = BrokerInstrument(security_id='s', symbol='AAA', broker_id='asset')
    async def observe():
        value = await observed()
        if defect == 'partial': return replace(value, completeness=Completeness.PARTIAL)
        if defect == 'position': return replace(value, positions=(BrokerPosition(instrument, Decimal(1)),))
        if defect == 'order': return replace(value, orders=(BrokerOrder('foreign', None, instrument, Side.BUY, CommandState.ACKNOWLEDGED, Decimal(1)),))
        return value
    broker.observe = observe
    if defect == 'cash': inner.cash = Decimal('40000')
    elif defect == 'blocked': inner.trading_blocked = True
    elif defect == 'wrong-account': inner.account = BrokerAccountIdentity('alpaca', 'OTHER')
    elif defect == 'stale': inner.now -= timedelta(minutes=2)
    elif defect == 'unstable':
        account = broker.account_snapshot
        count = [0]
        async def snapshot():
            count[0] += 1
            value = await account()
            return value if count[0] == 1 else replace(value, equity=value.equity+1)
        broker.account_snapshot = snapshot
    generation = [0]
    def authority():
        generation[0] += 1
        return ('b' if defect == 'revoked' and generation[0] > 1 else 'a')*64
    with pytest.raises((PaperActivationRefused, empty_account.EmptyAccountRefused, IncompleteObservation)):
        invoke(conn, appliance, authority)
    assert not anchor_rows(conn)
    assert not any(name in inner.calls for name in ('submit', 'cancel', 'recent_fills'))


def test_second_insert_failure_rolls_back_anchor_atomically(conn, appliance):
    class Failing:
        def __getattr__(self, name): return getattr(conn, name)
        def execute(self, sql, params=None):
            if sql.startswith('INSERT INTO sentinel_processed_sessions') and params[0] == recovery.CURSOR:
                raise RuntimeError('injected second insert failure')
            return conn.execute(sql, params)
    with pytest.raises(RuntimeError, match='second insert'):
        invoke(Failing(), appliance)
    assert not anchor_rows(conn)


def test_lost_receipt_claim_refuses_and_rolls_back_anchor(conn, appliance):
    from types import SimpleNamespace
    class LostClaim:
        def __getattr__(self, name): return getattr(conn, name)
        def execute(self, sql, params=None):
            if sql.startswith('INSERT INTO sentinel_processed_sessions') and params[0] == recovery.CURSOR:
                return SimpleNamespace(rowcount=0)
            return conn.execute(sql, params)
    with pytest.raises(PaperActivationRefused, match='atomic anchor claim'):
        invoke(LostClaim(), appliance)
    assert not anchor_rows(conn)


def test_declared_database_recovery_refuses_before_broker(conn, appliance):
    from types import SimpleNamespace
    class Restoring:
        def __getattr__(self, name): return getattr(conn, name)
        def execute(self, sql, params=None):
            if sql == 'SELECT pg_is_in_recovery()':
                return SimpleNamespace(fetchone=lambda: (True,))
            return conn.execute(sql, params)
    with pytest.raises(PaperActivationRefused, match='not_restoring'):
        invoke(Restoring(), appliance)
    assert not appliance[1].calls and not anchor_rows(conn)


def test_unwrapped_broker_or_wrong_read_grant_refuses_without_contact(conn, appliance):
    request, inner, broker, grant, _ = appliance
    with pytest.raises(PaperActivationRefused, match='guarded read broker'):
        asyncio.run(recovery.authorize(conn, broker=inner, grant=grant, request=request,
                    fresh_authority=lambda: 'a'*64))
    with pytest.raises(PaperActivationRefused, match='matching guarded read broker'):
        asyncio.run(recovery.authorize(conn, broker=broker,
                    grant=PaperPreparationGrant('OTHER', date.today()), request=request,
                    fresh_authority=lambda: 'a'*64))
    assert not inner.calls and not anchor_rows(conn)


@pytest.mark.parametrize('defect', ['signature', 'scope', 'missing-anchor'])
def test_unverifiable_resumption_refuses(conn, appliance, defect):
    invoke(conn, appliance)
    if defect == 'signature':
        conn.execute("UPDATE sentinel_processed_sessions SET state=jsonb_set(state,'{hmac_sha256}','\"bad\"') WHERE cursor_name=%s", (recovery.CURSOR,))
    elif defect == 'scope': appliance[0]['reason'] = 'different operation'
    else: conn.execute('DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s', (alpaca._DB_CURSOR,))
    conn.commit()
    with pytest.raises(PaperActivationRefused): invoke(conn, appliance)


@pytest.mark.parametrize('defect,guard', [
    ('unknown', 'never_traded=counts == (0, 0)'),
    ('broker', "paper_binding=bound.broker == 'alpaca'"),
    ('cluster', "original_cluster=current['system_identifier'] == request.system_identifier"),
    ('timeline', "original_timeline=current['timeline_id'] == 1"),
    ('enabled', 'killed=not control.enabled and control.kill_switch_engaged'),
    ('lease', 'no_live_lease=lease is False')])
def test_removed_local_scope_guard_is_detected(conn, appliance, monkeypatch, defect, guard):
    import inspect
    source = inspect.getsource(recovery._local).replace(guard, guard.split('=')[0]+'=True')
    scope = dict(vars(recovery)); exec(source, scope)
    monkeypatch.setattr(recovery, '_local', scope['_local'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_local_refusals_precede_broker_and_leave_no_recovery_receipt(conn, appliance, monkeypatch, defect)


def test_removed_final_fresh_authority_guard_is_detected(conn, appliance, monkeypatch):
    import inspect
    source = inspect.getsource(recovery.authorize).replace('or fresh_authority() != certificate', 'or False')
    scope = dict(vars(recovery)); exec(source, scope)
    monkeypatch.setattr(recovery, 'authorize', scope['authorize'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_broker_and_fresh_authority_refusals_never_write_anchor(conn, appliance, 'revoked')


def test_removed_atomic_receipt_claim_guard_is_detected(conn, appliance, monkeypatch):
    import inspect
    source = inspect.getsource(recovery.authorize).replace('if result.rowcount != 1:', 'if False:')
    scope = dict(vars(recovery)); exec(source, scope)
    monkeypatch.setattr(recovery, 'authorize', scope['authorize'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_lost_receipt_claim_refuses_and_rolls_back_anchor(conn, appliance)


def test_removed_not_restoring_guard_is_detected(conn, appliance, monkeypatch):
    import inspect
    source = inspect.getsource(recovery._local).replace('not_restoring=recovering is False', 'not_restoring=True')
    scope = dict(vars(recovery)); exec(source, scope)
    monkeypatch.setattr(recovery, '_local', scope['_local'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_declared_database_recovery_refuses_before_broker(conn, appliance)


@pytest.mark.parametrize('defect,condition', [('cash', 'if account.cash != account.equity:'),
                                            ('stale', 'if not -5 <= age <= 30:')])
def test_removed_fresh_empty_account_guard_is_detected(conn, appliance, monkeypatch, defect, condition):
    import inspect
    source = inspect.getsource(recovery._fresh_empty).replace(condition, 'if False:')
    scope = dict(vars(recovery)); exec(source, scope)
    monkeypatch.setattr(recovery, '_fresh_empty', scope['_fresh_empty'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_broker_and_fresh_authority_refusals_never_write_anchor(conn, appliance, defect)


def test_removed_guarded_read_broker_requirement_is_detected(conn, appliance, monkeypatch):
    import inspect
    source = inspect.getsource(recovery.authorize).replace(
        'if not isinstance(broker, GuardedExecutionBroker) or broker.grant != grant:', 'if False:')
    scope = dict(vars(recovery)); exec(source, scope)
    monkeypatch.setattr(recovery, 'authorize', scope['authorize'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_unwrapped_broker_or_wrong_read_grant_refuses_without_contact(conn, appliance)


def test_removed_canonical_writer_boundary_is_detected(conn, appliance, monkeypatch):
    from contextlib import nullcontext
    monkeypatch.setattr(recovery.journal, 'writer_lock', lambda *a, **k: nullcontext())
    with pytest.raises(AssertionError): test_second_insert_failure_rolls_back_anchor_atomically(conn, appliance)


def test_removed_explicit_confirmation_guard_is_detected(appliance, monkeypatch):
    import inspect
    source = inspect.getsource(recovery.Request).replace('if value is not True:', 'if False:')
    scope = dict(vars(recovery)); exec(source, scope)
    monkeypatch.setattr(recovery, 'Request', scope['Request'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_confirmation_schema_requires_literal_true_and_exact_fields(appliance)


def test_confirmation_schema_requires_literal_true_and_exact_fields(appliance):
    for changes in ({'same_host_confirmed': False}, {'same_host_confirmed': 1},
                    {'retain_current_paper_credentials': False}, {'actor': ' '},
                    {'system_identifier': 1234567}, {'extra': True}):
        with pytest.raises(ValueError): recovery.Request.model_validate(dict(appliance[0], **changes))
