"""Fresh authority reads cannot publish through their caller's revision lock."""
from decimal import Decimal
from types import SimpleNamespace

import psycopg
import pytest

from sentinel import binding, operational_schema
from sentinel.authority import AuthorityRefused
from sentinel.automation import store
from sentinel.automation.model import ControlBinding, StaleLeaderRefused
from sentinel.execution import authority_gate, journal
from sentinel.execution.contract import BrokerAccountIdentity, BrokerAccountSnapshot
from sentinel.execution.guarded import AutomationExecutionGrant, BrokerOperation
from sentinel.feed import store as feed_store
from tests.sentinel.test_operational_catalog_integration import cluster, conn  # noqa: F401


@pytest.fixture
def guarded_writer(conn, monkeypatch):
    operational_schema.install_quiescent(conn)
    bound = binding.bind(conn, deployment_id='readonly-authority', broker='alpaca',
        broker_account_id='PRIVATE-PAPER')
    control = ControlBinding(deployment_id=bound.deployment_id, broker=bound.broker,
        broker_account_id=bound.broker_account_id, takeover_epoch=bound.takeover_epoch,
        certificate_sha256='a' * 64, rollout_mode='PINNED_1_00', rollout_version=1,
        config_sha256='b' * 64)
    store.activate(conn, binding=control, actor='fixture', reason='private authority reader')
    store.release_kill(conn, expected_binding=control, actor='fixture', reason='private authority reader')
    permit = store.acquire_lease(conn, holder_id='readonly-holder', lease_seconds=120)
    grant = AutomationExecutionGrant(operation_scope='RECOVER', cycle_id='private-cycle',
        control_generation=permit.control_generation, holder_id=permit.holder_id,
        fence_token=permit.fence_token, broker_account_id=bound.broker_account_id,
        takeover_epoch=bound.takeover_epoch, rollout_mode=control.rollout_mode,
        rollout_version=control.rollout_version, certificate_sha256=control.certificate_sha256)
    monkeypatch.setattr(authority_gate, 'load_rollout_state', lambda c: SimpleNamespace(mode=control.rollout_mode))
    monkeypatch.setattr(authority_gate.feed_inputs, 'require_current', lambda c: SimpleNamespace(version=1))
    checks = []
    def validate(fresh, current_grant, operation, result):
        store.require_leader(fresh, permit)
        assert current_grant == grant
        checks.append(operation)
    def certificate(fresh, **kwargs):
        return SimpleNamespace(certificate_sha256=grant.certificate_sha256)
    arguments = dict(connection_factory=lambda: feed_store.connect(conn.info.dsn,
        connect_timeout=2, statement_timeout_ms=250),
        paper_base_url='https://paper-api.alpaca.markets', runtime_identity=lambda: {},
        strategy_identity=lambda: {}, validate_grant=validate, authority_check=certificate)
    with journal.writer_lock(conn, recovery_only=True):
        conn.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) "
            "VALUES ('broker-cash-activity:v1:alpaca:PRIVATE-PAPER','2026-11-06','{}')")
        yield conn, grant, arguments, checks
        conn.rollback()


def test_real_revision_lock_does_not_block_fresh_checks_or_publish_evidence(guarded_writer):
    conn, grant, arguments, checks = guarded_writer
    check = authority_gate.build_fresh_execution_check(**arguments, publish_operational_evidence=False)
    snapshot = BrokerAccountSnapshot(identity=BrokerAccountIdentity('alpaca', 'PRIVATE-PAPER'),
        equity=Decimal(100), cash=Decimal(100), multiplier=Decimal(1), status='ACTIVE')
    for result in (None, snapshot):
        check(grant, BrokerOperation.ACCOUNT_SNAPSHOT, result)
    assert checks == [BrokerOperation.ACCOUNT_SNAPSHOT] * 2
    assert conn.execute('SELECT count(*) FROM sentinel_broker_account_evidence').fetchone() == (0,)
    # Re-enable exactly the old publisher: the same real revision lock must
    # produce the original timeout, proving this case exercises the conflict.
    old = authority_gate.build_fresh_execution_check(**arguments, publish_operational_evidence=True)
    with pytest.raises(psycopg.errors.QueryCanceled, match='sentinel_operational_read_revisions'):
        old(grant, BrokerOperation.IDENTIFY_ACCOUNT, None)


def test_callback_pass_renews_its_clock_under_the_paper_revision_lock(guarded_writer, monkeypatch):
    from contextlib import closing
    from tests.sentinel.test_automation_runtime import config, production

    conn, grant, _, _ = guarded_writer
    conn.rollback()
    permit = store.acquire_lease(conn, holder_id=grant.holder_id, lease_seconds=120)
    runtime = production(config())
    runtime.holder_id = permit.holder_id
    cycle = SimpleNamespace(cycle_id=grant.cycle_id, control_generation=permit.control_generation,
        certificate_sha256=grant.certificate_sha256, rollout_mode=grant.rollout_mode,
        rollout_version=grant.rollout_version)
    context = SimpleNamespace(permit=permit, cycle=cycle, require_active=lambda: None)

    def validate(fresh, current_permit):
        store.require_leader(fresh, current_permit)
        return store.load_control(fresh), SimpleNamespace(certificate_sha256=grant.certificate_sha256)

    monkeypatch.setattr(runtime, '_validate_control_authority', validate)
    monkeypatch.setattr(store, 'load_cycle', lambda fresh, cycle_id: cycle)
    evidence = "SELECT authority_detail,authority_checked_at,revision FROM sentinel_automation_control " \
        "JOIN sentinel_operational_read_revisions ON scope='PAPER' WHERE id=1"
    with closing(feed_store.connect(conn.info.dsn, statement_timeout_ms=250)) as observer:
        runtime._assert_cycle_authority(observer, context, operation_scope='RECOVER')
        original_detail, original_clock, original_revision = observer.execute(evidence).fetchone()
        conn.execute("SELECT revision FROM sentinel_operational_read_revisions "
                     "WHERE scope='PAPER' FOR NO KEY UPDATE").fetchone()
        runtime._assert_control_authority(observer, permit, require_publication=True)
        detail, checked_at, revision = observer.execute(evidence).fetchone()
        assert detail == original_detail and revision == original_revision
        assert checked_at > original_clock

        # The original different PASS wording must time out at the exact row.
        with pytest.raises(psycopg.errors.QueryCanceled, match='sentinel_operational_read_revisions'):
            store.record_authority_verdict(observer, verdict='PASS',
                detail=f'signed certificate {grant.certificate_sha256} verified for automation cycle {cycle.cycle_id}',
                holder_id=permit.holder_id, fence_token=permit.fence_token,
                control_generation=permit.control_generation)
        conn.rollback()
        store.engage_kill(conn, actor='fixture', reason='revoke callback authority')
        with pytest.raises(StaleLeaderRefused):
            runtime._assert_control_authority(observer, permit, require_publication=True)


def test_readonly_check_still_refuses_a_fresh_kill(guarded_writer):
    conn, grant, arguments, _ = guarded_writer
    check = authority_gate.build_fresh_execution_check(**arguments, publish_operational_evidence=False)
    check(grant, BrokerOperation.IDENTIFY_ACCOUNT, None)
    conn.rollback()
    store.engage_kill(conn, actor='fixture', reason='revoke between native reads')
    with pytest.raises(StaleLeaderRefused):
        check(grant, BrokerOperation.IDENTIFY_ACCOUNT, None)


def test_authority_connection_is_really_readonly_and_errors_are_not_permission(guarded_writer):
    _, grant, arguments, _ = guarded_writer
    def unexpected_write(fresh, **kwargs):
        assert fresh.execute('SHOW transaction_read_only').fetchone() == ('on',)
        fresh.execute("UPDATE sentinel_automation_control SET authority_detail='forbidden'")
    check = authority_gate.build_fresh_execution_check(**dict(arguments,
        authority_check=unexpected_write), publish_operational_evidence=False)
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        check(grant, BrokerOperation.IDENTIFY_ACCOUNT, None)


def test_readonly_guard_still_requires_fresh_mutation_backup(guarded_writer, monkeypatch):
    _, grant, arguments, checks = guarded_writer
    def refused(fresh, **kwargs):
        assert fresh.execute('SHOW transaction_read_only').fetchone() == ('on',)
        assert kwargs == {'operation': 'broker cancel mutation', 'allow_continuity': True}
        raise authority_gate.backup_runtime_authority.BackupRuntimeRefused('required media refused')
    monkeypatch.setattr(authority_gate.backup_runtime_authority, 'require', refused)
    check = authority_gate.build_fresh_execution_check(**arguments, publish_operational_evidence=False)
    with pytest.raises(authority_gate.backup_runtime_authority.BackupRuntimeRefused, match='required media'):
        check(grant, BrokerOperation.CANCEL, None)
    assert not checks


def test_readonly_guard_does_not_reuse_a_revoked_certificate(guarded_writer):
    _, grant, arguments, _ = guarded_writer
    def revoked(fresh, **kwargs):
        raise AuthorityRefused('fresh certificate revoked')
    check = authority_gate.build_fresh_execution_check(**dict(arguments,
        authority_check=revoked, safety_authority_check=revoked), publish_operational_evidence=False)
    with pytest.raises(AuthorityRefused, match='fresh certificate revoked'):
        check(grant, BrokerOperation.IDENTIFY_ACCOUNT, None)


def test_readonly_publication_option_cannot_configure_live():
    with pytest.raises(AuthorityRefused, match='PAPER only'):
        authority_gate.build_fresh_execution_check(connection_factory=lambda: None,
            paper_base_url='https://api.alpaca.markets', runtime_identity=lambda: {},
            strategy_identity=lambda: {}, validate_grant=lambda *args: None,
            publish_operational_evidence=False)
