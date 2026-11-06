"""A confirmed native dividend can anchor a future plan, never an old one."""
import ast
import asyncio
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import inspect
import json
import textwrap

import pytest

from sentinel import binding
from sentinel import backup_runtime_authority
from sentinel.automation import store
from sentinel.automation.model import ControlBinding
from sentinel.execution import broker_cash, journal
from sentinel.execution.commands import Command
from sentinel.execution.contract import BrokerAccountIdentity, BrokerAccountSnapshot, BrokerInstrument, BrokerObservation, Completeness, Side
from sentinel.execution.guarded import GuardedExecutionBroker, PaperPreparationGrant
from sentinel.execution.identity import CommandIdentity
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.states import CommandState
from sentinel.paper import cash_retirement as retirement
from sentinel.paper.cash import _cash_authority_or_refuse
from sentinel.paper.model import PaperActivationRefused
from tests.sentinel.test_paper_current_cash_acceptance import conn, pg, selected, ACCOUNT_NUMBER
from tests.sentinel.test_operational_catalog_integration import cluster, conn as qualified_catalog_conn

NOW = datetime(2026, 11, 6, 22, tzinfo=timezone.utc)
DECISION = date(2026, 11, 6)
NATIVE_ID = '22222222-2222-2222-2222-222222222222'
IDENTITY = BrokerAccountIdentity('alpaca', ACCOUNT_NUMBER)


@pytest.fixture
def context(conn, monkeypatch):
    return retirement_context(conn, monkeypatch)


def retirement_context(conn, monkeypatch):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'private-retirement-test-key-not-production')
    bound = binding.require(conn)
    old = ExecutionPlan('legacy-cash-plan', date(2026, 11, 5), DECISION, Decimal(0),
        deployment_id=bound.deployment_id, broker=bound.broker,
        broker_account_id=bound.broker_account_id, takeover_epoch=bound.takeover_epoch,
        account_cash=Decimal('11079.88'), account_nav=Decimal('30000'))
    journal.save_plan(conn, old)
    wrapped, http = selected()
    grant = PaperPreparationGrant(ACCOUNT_NUMBER, DECISION)
    broker = GuardedExecutionBroker(inner=wrapped._inner, grant=grant, guard=wrapped.guard)
    activity = asyncio.run(broker_cash.ingest_account_cash(conn, broker_adapter=broker,
        broker='alpaca', account_id=ACCOUNT_NUMBER, through=NOW))
    conn.commit()
    request = retirement.Request(plan_id=old.plan_id, plan_fingerprint=old.fingerprint(),
        native_activity_id=NATIVE_ID, observed_cash='11155.77', actor='operator',
        reason='Native dividend posted after the legacy cash observation',
        confirm_prospective_retirement=True)
    return dict(request=request, plan=old, binding=bound, grant=grant, broker=broker,
        decision_session=DECISION, account=BrokerAccountSnapshot(identity=IDENTITY,
            equity=Decimal('30000'), cash=Decimal('11155.77'), multiplier=Decimal(1), status='ACTIVE'),
        observation=BrokerObservation(observed_at=NOW, account_identity=IDENTITY),
        activity_state=activity, observed_at=NOW, now=NOW, certificate_sha256='a' * 64)


def qualify(conn, context, **changes):
    return retirement.qualify(conn, **dict(context, **changes))


def successor(conn, context):
    value = replace(context['plan'], plan_id='future-cash-plan', decision_session=DECISION,
        effective_session=date(2026, 11, 9), account_cash=context['account'].cash)
    journal.adopt_current_plan(conn, value, commit=False)
    broker_cash.record_plan_baseline(conn, plan_id=value.plan_id, decision_session=DECISION,
        activity_state=context['activity_state'])
    return value


def developer_transaction_fixture(monkeypatch, tmp_path):
    # This case isolates SQL atomicity. It makes no deployed-backup claim;
    # the real required-media refusal has its own oracle immediately below.
    monkeypatch.setattr(backup_runtime_authority, 'POLICY_MARKER', tmp_path / 'developer-no-media')


def test_retirement_writer_retains_production_backup_gate(conn, context, monkeypatch):
    monkeypatch.setenv(backup_runtime_authority.AUTHORITY_ENV, 'REQUIRED_V1')
    with pytest.raises(backup_runtime_authority.BackupRuntimeRefused):
        with journal.writer_lock(conn):
            pytest.fail('retirement entered the writer without required backup media')


def test_future_anchor_preserves_legacy_plan_and_missing_cash_boundary(conn, context, monkeypatch, tmp_path):
    developer_transaction_fixture(monkeypatch, tmp_path)
    with journal.writer_lock(conn):
        prepared = qualify(conn, context)
        new = successor(conn, context)
        receipt = retirement.record(conn, prepared=prepared, successor=new)
        conn.commit()
    old = journal.load_plan(conn, context['plan'].plan_id)
    assert old.account_cash == Decimal('11079.88')
    assert old.fingerprint() == context['plan'].fingerprint()
    assert old.superseded_by == new.plan_id
    assert broker_cash.load_plan_baseline(conn, plan_id=old.plan_id) is None
    assert receipt['historical_cash_interval'] == 'UNVERIFIED'
    assert receipt['broker_mutations'] == 0
    assert not journal.load_commands(conn, context['binding'].identity)
    _cash_authority_or_refuse(conn, plan=new, deployment=context['binding'].identity,
        account=context['account'], observation=context['observation'], activity_state=context['activity_state'])
    with pytest.raises(PaperActivationRefused, match='cannot be backfilled'):
        _cash_authority_or_refuse(conn, plan=old, deployment=context['binding'].identity,
            account=context['account'], observation=context['observation'],
            activity_state=context['activity_state'], permit_new_activity=True)
    assert retirement.pending_request(conn, context['request'], new, decision_session=DECISION) is None
    retirement.verify_retirements(conn)


def test_retirement_preserves_qualified_catalog_and_shadow_revision(qualified_catalog_conn, monkeypatch, tmp_path):
    from sentinel import operational_catalog, operational_schema
    from sentinel.panel import operational_schema as panel_schema

    # Operational extensions own persistent functions as well as tables. Keep
    # their committed installation in a disposable database, outside the shared
    # legacy table-reset fixture used by the remaining retirement cases.
    conn = qualified_catalog_conn
    binding.bind(conn, deployment_id='cash-acceptance', broker='alpaca', broker_account_id=ACCOUNT_NUMBER)
    conn.execute("UPDATE sentinel_account_binding SET established_at='2026-02-12T00:00:00Z' WHERE id=1")
    conn.commit()
    context = retirement_context(conn, monkeypatch)
    developer_transaction_fixture(monkeypatch, tmp_path)
    operational_schema.install_quiescent(conn)
    assert operational_catalog.require_extension(conn, panel_schema.__name__)
    conn.rollback()
    with journal.writer_lock(conn):
        prepared = qualify(conn, context)
        new = successor(conn, context)
        revisions = lambda: dict(conn.execute(
            'SELECT scope,revision FROM sentinel_operational_read_revisions').fetchall())
        before = revisions()
        retirement.record(conn, prepared=prepared, successor=new)
        after = revisions()
        assert after['PAPER'] == before['PAPER'] + 2
        assert after['SHADOW'] == before['SHADOW']
        retirement.verify_retirements(conn)
        # Unknown metadata must still invalidate financial shadow subjects.
        conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) "
                     "VALUES ('unrecognized-financial-input','2026-11-06','{}')")
        assert revisions()['SHADOW'] == after['SHADOW'] + 1
        conn.commit()
    assert operational_catalog.require_extension(conn, panel_schema.__name__)


@pytest.mark.parametrize('state', list(CommandState))
def test_any_legacy_command_refuses_retirement_even_terminal(conn, context, state):
    command = Command(CommandIdentity(context['binding'].identity, context['plan'].plan_id, 'SEC-X'),
        BrokerInstrument('SEC-X', 'X', 'asset-X'), Side.BUY, Decimal(1), state=state)
    journal.save_command(conn, command)
    with pytest.raises(PaperActivationRefused, match='dispatched intent'):
        qualify(conn, context)


def test_unknown_on_another_plan_refuses(conn, context):
    command = Command(CommandIdentity(context['binding'].identity, 'another', 'SEC-X'),
        BrokerInstrument('SEC-X', 'X', 'asset-X'), Side.BUY, Decimal(1), state=CommandState.UNKNOWN)
    journal.save_command(conn, command)
    with pytest.raises(PaperActivationRefused, match='dispatched intent'):
        qualify(conn, context)


@pytest.mark.parametrize('change', ['same_decision', 'late_open', 'stale', 'future_clock', 'wrong_cash',
    'wrong_account', 'wrong_plan', 'wrong_fingerprint', 'no_source', 'old_source', 'incomplete_book'])
def test_negative_evidence_never_anchors(conn, context, change):
    altered = dict(context)
    if change == 'same_decision': altered['decision_session'] = context['plan'].decision_session
    if change == 'late_open': altered['now'] = datetime(2026, 11, 9, 14, 30, tzinfo=timezone.utc)
    if change == 'stale': altered['now'] = NOW + timedelta(seconds=31)
    if change == 'future_clock': altered['now'] = NOW - timedelta(seconds=1)
    if change == 'wrong_cash': altered['account'] = replace(context['account'], cash=Decimal('11155.78'))
    if change == 'wrong_account': altered['account'] = replace(context['account'], identity=BrokerAccountIdentity('alpaca', 'OTHER'))
    if change == 'wrong_plan': altered['request'] = context['request'].model_copy(update={'plan_id': 'another'})
    if change == 'wrong_fingerprint': altered['request'] = context['request'].model_copy(update={'plan_fingerprint': 'b' * 64})
    if change == 'no_source': altered['activity_state'] = None
    if change == 'old_source': altered['activity_state'] = replace(context['activity_state'], activity_identity_scheme=None)
    if change == 'incomplete_book': altered['observation'] = replace(context['observation'], completeness=Completeness.PARTIAL)
    with pytest.raises(PaperActivationRefused):
        qualify(conn, altered)
    assert conn.execute('SELECT COUNT(*) FROM sentinel_processed_sessions WHERE cursor_name LIKE %s',
        (retirement.PREFIX + '%',)).fetchone()[0] == 0


@pytest.mark.parametrize('sql', [
    'UPDATE sentinel_automation_control SET enabled=true',
    'UPDATE sentinel_automation_control SET kill_switch_engaged=false',
    "UPDATE sentinel_automation_lease SET holder_id='live',control_generation=1,acquired_at=clock_timestamp(),heartbeat_at=clock_timestamp(),expires_at=clock_timestamp()+interval '1 minute'",
    "UPDATE sentinel_cash_flows SET detail=replace(detail,'type=DIV','type=FEE')",
    "UPDATE sentinel_cash_flows SET amount=amount+0.01",
    "UPDATE sentinel_cash_flows SET session='2026-11-09'",
])
def test_fence_and_native_dividend_guards(conn, context, sql):
    if sql.startswith('UPDATE sentinel_automation_control'):
        bound = context['binding']
        control_binding = ControlBinding(deployment_id=bound.deployment_id,
            broker=bound.broker, broker_account_id=bound.broker_account_id,
            takeover_epoch=bound.takeover_epoch, certificate_sha256='a' * 64,
            rollout_mode='CONTROLLER', rollout_version=1, config_sha256='b' * 64)
        store.activate(conn, binding=control_binding, actor='test', reason='real enabled control')
        if 'kill_switch_engaged=false' in sql:
            store.release_kill(conn, expected_binding=control_binding, actor='test', reason='real released control')
    else:
        conn.execute(sql)
    with pytest.raises(PaperActivationRefused): qualify(conn, context)


def test_failed_adoption_rolls_back_both_receipt_and_reference_claim(conn, context, monkeypatch, tmp_path):
    developer_transaction_fixture(monkeypatch, tmp_path)
    with pytest.raises(RuntimeError, match='crash before adoption commit'):
        with journal.writer_lock(conn):
            prepared = qualify(conn, context)
            new = successor(conn, context)
            retirement.record(conn, prepared=prepared, successor=new)
            raise RuntimeError('crash before adoption commit')
    assert journal.latest_plan(conn).plan_id == context['plan'].plan_id
    assert broker_cash.load_plan_baseline(conn, plan_id='future-cash-plan') is None
    assert conn.execute('SELECT COUNT(*) FROM sentinel_processed_sessions WHERE cursor_name LIKE %s',
        (retirement.PREFIX + '%',)).fetchone()[0] == 0


def test_control_change_after_qualification_refuses_atomic_anchor(conn, context, monkeypatch, tmp_path):
    developer_transaction_fixture(monkeypatch, tmp_path)
    prepared = qualify(conn, context)
    bound = context['binding']
    control_binding = ControlBinding(deployment_id=bound.deployment_id, broker=bound.broker,
        broker_account_id=bound.broker_account_id, takeover_epoch=bound.takeover_epoch,
        certificate_sha256='a' * 64, rollout_mode='CONTROLLER', rollout_version=1,
        config_sha256='b' * 64)
    store.activate(conn, binding=control_binding, actor='test', reason='intervening control change')
    store.deactivate(conn, actor='test', reason='returned to killed but a different generation')
    with pytest.raises(PaperActivationRefused, match='writer fence'):
        with journal.writer_lock(conn):
            new = successor(conn, context)
            retirement.record(conn, prepared=prepared, successor=new)
    assert journal.latest_plan(conn).plan_id == context['plan'].plan_id
    assert broker_cash.load_plan_baseline(conn, plan_id='future-cash-plan') is None


def test_removed_final_fence_recheck_is_detected(conn, context, monkeypatch, tmp_path):
    tree = ast.parse(textwrap.dedent(inspect.getsource(retirement.record)))
    matches = [n for n in ast.walk(tree) if isinstance(n, ast.If)
        and 'control.generation' in ast.unparse(n.test)]
    assert len(matches) == 1
    matches[0].test = ast.Constant(False)
    ast.fix_missing_locations(tree)
    namespace = {}
    exec(compile(tree, '<removed-retirement-final-fence>', 'exec'), vars(retirement), namespace)
    monkeypatch.setattr(retirement, 'record', namespace['record'])
    with pytest.raises(pytest.fail.Exception):
        test_control_change_after_qualification_refuses_atomic_anchor(conn, context, monkeypatch, tmp_path)


@pytest.mark.parametrize('mutation', ['hmac', 'native_claim', 'baseline', 'predecessor', 'native_flow'])
def test_receipt_restart_and_restore_refuse_missing_or_changed_evidence(conn, context, mutation):
    prepared = qualify(conn, context)
    new = successor(conn, context)
    retirement.record(conn, prepared=prepared, successor=new)
    conn.commit()
    if mutation == 'hmac':
        conn.execute("UPDATE sentinel_processed_sessions SET state=jsonb_set(state,'{hmac_sha256}',to_jsonb(%s::text)) WHERE cursor_name=%s",
                     ('0' * 64, retirement.PREFIX + context['plan'].plan_id))
    if mutation == 'native_claim':
        conn.execute('DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s',
                     (retirement._claim(context['request'], context['binding'].to_dict()),))
    if mutation == 'baseline':
        conn.execute('DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s',
                     (broker_cash.PLAN_BASELINE_PREFIX + new.plan_id,))
    if mutation == 'predecessor':
        conn.execute("UPDATE sentinel_execution_plans SET superseded_by='wrong' WHERE plan_id=%s", (context['plan'].plan_id,))
    if mutation == 'native_flow':
        conn.execute('DELETE FROM sentinel_cash_flows')
    with pytest.raises(PaperActivationRefused): retirement.pending_request(conn, context['request'], new, decision_session=DECISION)
    with pytest.raises(PaperActivationRefused): retirement.verify_retirements(conn)


def test_native_dividend_cannot_be_consumed_by_another_retirement(conn, context):
    prepared = qualify(conn, context)
    new = successor(conn, context)
    retirement.record(conn, prepared=prepared, successor=new)
    conn.commit()
    with pytest.raises(PaperActivationRefused, match='already consumed'):
        qualify(conn, context)


@pytest.mark.parametrize('value', [False, 1, 'true'])
def test_request_requires_boolean_confirmation(context, value):
    raw = dict(context['request'].model_dump(), confirm_prospective_retirement=value)
    with pytest.raises(ValueError): retirement.Request.model_validate(raw)


@pytest.mark.parametrize('guard', ['commands', 'exact_dividend', 'native_claim'])
def test_policy_oracles_detect_removed_guard(conn, context, monkeypatch, guard):
    tree = ast.parse(textwrap.dedent(inspect.getsource(retirement.qualify)))
    needles = {'commands': 'baseline-free plan', 'exact_dividend': 'confirmed native settled',
               'native_claim': 'already consumed'}
    matches = [n for n in ast.walk(tree) if isinstance(n, ast.If)
        and any(isinstance(x, ast.Constant) and isinstance(x.value, str)
            and needles[guard] in x.value for statement in n.body for x in ast.walk(statement))]
    assert len(matches) == 1
    matches[0].test = ast.Constant(False)
    ast.fix_missing_locations(tree)
    namespace = {}
    exec(compile(tree, '<removed-cash-retirement-guard>', 'exec'), vars(retirement), namespace)
    monkeypatch.setattr(retirement, 'qualify', namespace['qualify'])
    with pytest.raises(pytest.fail.Exception):
        if guard == 'commands': test_any_legacy_command_refuses_retirement_even_terminal(conn, context, CommandState.UNKNOWN)
        elif guard == 'exact_dividend': test_fence_and_native_dividend_guards(conn, context, "UPDATE sentinel_cash_flows SET detail=replace(detail,'type=DIV','type=FEE')")
        else: test_native_dividend_cannot_be_consumed_by_another_retirement(conn, context)
