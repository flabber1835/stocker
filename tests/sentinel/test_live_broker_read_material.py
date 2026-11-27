"""A real LIVE guard, private PostgreSQL, file-backed test signatures and an in-memory HTTP venue."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
import psycopg

from sentinel import binding, schema, trading
from sentinel.automation import store
from sentinel.automation.env_config import config_from_env
from sentinel.automation.model import ControlBinding, CycleState
from sentinel.authority import live_runtime
from sentinel.config import SentinelConfig, build_execution_broker
from sentinel.execution import authority_gate, feed_inputs, journal
from sentinel.execution.guarded import AutomationExecutionGrant, BrokerAuthorityRefused
from sentinel.execution.plan import ExecutionPlan
from sentinel.execution.states import CommandState
from sentinel.feed import broker_read_material, normalized_layout, operational_snapshot, rolling_store
from tests.sentinel.live_order_fixtures import command
from tests.sentinel.test_automation_store import cycle_spec
from tests.sentinel.test_issue_183_alpaca_hardening import Httpx, Response
from tests.sentinel.test_live_runtime_authority import runtime_fixture
from tests.sentinel.test_publication_read_cost import alpaca_path, conn as empty_feed, pg, published  # noqa: F401


@pytest.fixture
def conn(empty_feed):
    schema.ensure_schema(empty_feed)
    return empty_feed


@pytest.mark.parametrize('original', ['on', 'off'])
def test_live_proof_restores_the_same_sessions_original_privileges(pg, original):
    with psycopg.connect(pg.sync_dsn) as reader:
        reader.execute("SELECT set_config('default_transaction_read_only',%s,false)", (original,))
        reader.commit()
        with authority_gate._read_only_proof(reader, resume_evidence=True):
            for _ in range(2):
                with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
                    reader.execute('CREATE TABLE private_unexpected_write (i int)')
                reader.rollback()
        assert reader.execute('SHOW transaction_read_only').fetchone()[0] == original


@pytest.fixture
def opening(conn, published, monkeypatch, tmp_path):
    monkeypatch.setenv('ALPACA_BASE_URL', 'https://api.alpaca.markets')
    monkeypatch.delenv('SENTINEL_PAPER_BUY_POLICY', raising=False)
    monkeypatch.delenv('SENTINEL_PAPER_BUY_CAP_BPS', raising=False)
    with monkeypatch.context() as signing:
        signed = runtime_fixture(tmp_path, signing)
    for name, value in signed.env.items():
        monkeypatch.setenv(name, value)
    subject = signed.subject
    binding.bind(conn, deployment_id=subject.deployment_id, broker='alpaca-live', broker_account_id=subject.account_id)
    monkeypatch.setattr(trading.identity, 'rehearsal_identity', lambda: signed.runtime)
    monkeypatch.setattr(trading, '_strategy', lambda: signed.strategy)
    config = config_from_env()
    admission = trading._admission(conn, subject.base_url, config.fingerprint)
    cert = live_runtime.require_current_live_authority(conn, base_url=subject.base_url, runtime_identity=signed.runtime,
        strategy_identity=signed.strategy, required_operation='AUTOMATION', automation_config_sha256=config.fingerprint)
    control_binding = ControlBinding(deployment_id=subject.deployment_id, broker='alpaca-live',
        broker_account_id=subject.account_id, takeover_epoch=subject.takeover_epoch,
        certificate_sha256=cert.sha256, config_sha256=config.fingerprint, rollout_mode='PINNED_1_00', rollout_version=1)
    store.activate(conn, binding=control_binding, actor='test', reason='private signed account')
    control = store.release_kill(conn, expected_binding=control_binding, actor='test', reason='private opening')
    permit = store.acquire_lease(conn, holder_id='private-reader', lease_seconds=120)
    pub = feed_inputs.require_current(conn)
    spec = cycle_spec(control, config, session=str(pub.window_end))
    cycle = store.create_cycle(conn, permit=permit, spec=spec, now=spec.prepare_at)
    plan = ExecutionPlan('plan', spec.decision_session, spec.effective_session, Decimal(1), data_version=pub.version,
        deployment_id=subject.deployment_id, broker='alpaca-live', broker_account_id=subject.account_id, takeover_epoch=1)
    journal.adopt_current_plan(conn, plan)
    for state in (CycleState.PREPARING, CycleState.PLAN_READY, CycleState.EXECUTING):
        store.transition_cycle(conn, permit=permit, cycle_id=cycle.cycle_id, to_state=state,
                               plan_id=plan.plan_id, plan_fingerprint=plan.fingerprint())
    grant = AutomationExecutionGrant('EXECUTE', cycle.cycle_id, permit.control_generation, permit.holder_id,
        permit.fence_token, subject.account_id, 1, control_binding.rollout_mode, 1, cert.sha256,
        config_sha256=config.fingerprint)
    # This test starts with prepared strategy economics and an open session. The
    # grant, account binding, fence, native adapter, signatures and publication run normally.
    monkeypatch.setattr(trading, '_shadow', lambda *_a, **_k: SimpleNamespace(session=str(pub.window_end),
                                                                                state=SimpleNamespace(data_version=pub.version)))
    monkeypatch.setattr(trading, '_readiness_or_refuse', lambda *_a, **_k: None)
    monkeypatch.setattr(trading.dual_plan_authority, 'rederive_plan', lambda *_a, **_k: {'state_sha256': 'a' * 64})
    monkeypatch.setattr(trading, '_assert_plan_authorities', lambda *_a, **_k: None)
    monkeypatch.setattr(trading.calendar, 'session_window', lambda _day: (signed.now - timedelta(minutes=1),
                                                                          signed.now + timedelta(hours=2)))
    monkeypatch.setattr(authority_gate.backup_runtime_authority, 'require', lambda *_a, **_k: {
        'enabled': True, 'backup_state': 'CURRENT', 'independent_archive_current': True})
    owned = replace(command(signed), state=CommandState.ACKNOWLEDGED, broker_order_id='private-native-order')
    journal.save_command(conn, owned)
    account = dict(id=subject.account_id, status='ACTIVE', cash='1000', buying_power='1000', equity='1000',
                   multiplier='1', trading_blocked=False, account_blocked=False, trade_suspended_by_user=False)
    http = Httpx(routes={'/v2/account': account})
    async def delete(_client, url, headers):
        http.calls.append(('DELETE', url))
        return Response(status_code=204)
    monkeypatch.setattr(http.AsyncClient, 'delete', delete, raising=False)
    raw = build_execution_broker(SentinelConfig.from_env({'ALPACA_BASE_URL': subject.base_url,
        'ALPACA_API_KEY': 'offline-test-key', 'ALPACA_SECRET_KEY': 'offline-test-secret'}),
        resolve_security_id=lambda symbol, *_a: symbol, live_admission=admission)
    raw._http_provider = lambda: http
    checks, writes, scans, bound_calls, manifest_calls = [], [], [], [], []
    validate, verdict, headers = trading._validate_grant, store.record_authority_verdict, normalized_layout._candidate_headers
    def checked(reader, active, op, result, **kwargs):
        checks.append((reader.info.backend_pid, reader.execute('SHOW transaction_read_only').fetchone()[0], op.value))
        return validate(reader, active, op, result, **kwargs)
    def recorded(writer, **kwargs):
        writes.append((writer.info.backend_pid, writer.execute('SHOW transaction_read_only').fetchone()[0], kwargs['verdict']))
        return verdict(writer, **kwargs)
    def counted(reader, candidate):
        scans.append(candidate)
        return headers(reader, candidate)
    bound_reader, manifest_reader = operational_snapshot._bound_and_manifest, rolling_store.manifest
    def bound_material(reader, pub):
        bound_calls.append(reader.info.backend_pid)
        return bound_reader(reader, pub)
    def manifest(reader, candidate_id):
        manifest_calls.append(reader.info.backend_pid)
        return manifest_reader(reader, candidate_id)
    monkeypatch.setattr(trading, '_validate_grant', checked)
    monkeypatch.setattr(store, 'record_authority_verdict', recorded)
    with journal.writer_lock(conn), feed_inputs.pinned(conn, commit=False):
        wrapped = trading._guard(conn, raw, base_url=subject.base_url, grant=grant, observation_id='prepared',
            starting_cash='1000', plan=plan, clock=lambda: signed.now, automation_config_sha256=config.fingerprint)
        monkeypatch.setattr(normalized_layout, '_candidate_headers', counted)
        monkeypatch.setattr(operational_snapshot, '_bound_and_manifest', bound_material)
        monkeypatch.setattr(rolling_store, 'manifest', manifest)
        yield SimpleNamespace(broker=wrapped, http=http, owned=owned, account=account, scans=scans, checks=checks,
                              writes=writes, signed=signed, candidate=published['candidate_id'],
                              bound_calls=bound_calls, manifest_calls=manifest_calls)


def test_signed_live_read_reuses_only_market_data_and_owned_cancel_checks_again(conn, opening, monkeypatch):
    for _ in range(2):
        assert asyncio.run(opening.broker.account_snapshot()).identity.account_id == opening.signed.subject.account_id
    assert len(opening.checks) == len(opening.writes) == 4
    assert [(pid, mode) for pid, mode, _ in opening.checks] == [(pid, 'on') for pid, _, _ in opening.writes]
    assert all(mode == 'off' and verdict == 'PASS' for _, mode, verdict in opening.writes)
    assert len({pid for pid, _, _ in opening.checks}) == 4
    assert set(opening.bound_calls) == {pid for pid, _, _ in opening.checks}
    assert len(opening.bound_calls) > len(opening.checks)
    assert opening.manifest_calls == [opening.checks[0][0]]
    assert opening.scans == [opening.candidate]
    assert conn.execute('SELECT count(*) FROM sentinel_broker_account_evidence').fetchone()[0] == 2
    response = asyncio.run(opening.broker.cancel(opening.owned.broker_order_id))
    assert response.state is CommandState.ACKNOWLEDGED
    assert [call[0] for call in opening.http.calls] == ['GET', 'GET', 'DELETE']
    assert [(mode, op) for _, mode, op in opening.checks[-2:]] == [('off', 'cancel'), ('off', 'cancel')]
    assert len(opening.scans) > 1
    # Removing only the material scope repeats full native header validation on one GET.
    opening.scans.clear()
    enter = broker_read_material.ReadScope.enter
    monkeypatch.setattr(broker_read_material.ReadScope, 'enter', lambda scope, _grant: enter(scope, None))
    assert asyncio.run(opening.broker.account_snapshot()).identity.account_id == opening.signed.subject.account_id
    assert len(opening.scans) > 1


def test_signed_live_mutation_rechecks_control_after_entering_the_native_client(conn, opening, monkeypatch):
    asyncio.run(opening.broker.account_snapshot())
    async def withdraw_at_http_entry(client):
        store.engage_kill(conn, actor='test', reason='after cancel approval, before native HTTP')
        return client
    monkeypatch.setattr(opening.http.AsyncClient, '__aenter__', withdraw_at_http_entry)
    with pytest.raises(BrokerAuthorityRefused):
        asyncio.run(opening.broker.cancel(opening.owned.broker_order_id))
    assert [call[0] for call in opening.http.calls] == ['GET']


@pytest.mark.parametrize('withdraw', ['kill', 'lease'])
def test_live_read_withdrawn_at_verdict_rolls_back_snapshot(conn, opening, monkeypatch, withdraw):
    record = authority_gate.operational_evidence.record_account_snapshot
    def lost_fence(writer, snapshot):
        # The guard has already checked both signed permissions and the result account.
        if withdraw == 'kill':
            store.engage_kill(conn, actor='test', reason='before native result is released')
        else:
            conn.execute("UPDATE sentinel_automation_lease SET expires_at=clock_timestamp()-interval '1 second'")
            conn.commit()
        record(writer, snapshot)
    monkeypatch.setattr(authority_gate.operational_evidence, 'record_account_snapshot', lost_fence)
    with pytest.raises(BrokerAuthorityRefused, match='fence'):
        asyncio.run(opening.broker.account_snapshot())
    assert conn.execute('SELECT count(*) FROM sentinel_broker_account_evidence').fetchone()[0] == 0
    with pytest.raises(BrokerAuthorityRefused):
        asyncio.run(opening.broker.cancel(opening.owned.broker_order_id))
    assert [call[0] for call in opening.http.calls] == ['GET']


def test_changed_source_between_signed_read_checks_discards_result(conn, opening):
    from sentinel.feed.rolling_contract import canonical_json, digest
    def substitute(_params):
        conn.execute("SET LOCAL session_replication_role='replica'")
        layout = conn.execute('SELECT layout FROM sentinel_candidate_layouts WHERE candidate_id=%s',
                              (opening.candidate,)).fetchone()[0]
        layout['unrecognized'] = True
        conn.execute('UPDATE sentinel_candidate_layouts SET layout=%s::jsonb,canonical_layout=%s,layout_sha256=%s '
                     'WHERE candidate_id=%s', (canonical_json(layout), canonical_json(layout), digest(layout), opening.candidate))
        conn.commit()
        return opening.account
    opening.http.routes['/v2/account'] = substitute
    with pytest.raises(BrokerAuthorityRefused, match='NORMALIZED_LAYOUT_BINDING_CHANGED'):
        asyncio.run(opening.broker.account_snapshot())
    assert opening.writes[-1][1:] == ('off', 'FAIL')
    assert store.load_control(conn).authority_verdict == 'FAIL'
    assert conn.execute('SELECT count(*) FROM sentinel_broker_account_evidence').fetchone()[0] == 0
    with pytest.raises(BrokerAuthorityRefused):
        asyncio.run(opening.broker.cancel(opening.owned.broker_order_id))
    assert [call[0] for call in opening.http.calls] == ['GET']
