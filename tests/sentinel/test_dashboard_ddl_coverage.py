"""Real predecessor upgrade and distinct post-failure physical-witness recovery."""
import asyncio
import copy
import inspect
import uuid
from datetime import timedelta

import psycopg
from psycopg import sql
import pytest
from pydantic import ValidationError

from sentinel import binding, mirror_projection, operational_ddl_epoch, operational_schema, schema
from sentinel.execution import evidence_projection as coverage, journal
from sentinel.execution.contract import BrokerAccountIdentity
from sentinel.execution.simulator import SimulatedBroker
from sentinel.feed import store
from sentinel.panel import review_schema, review_migration as migration
from sentinel.panel import review_coverage_recovery as recovery
from tests.support.postgres import _EphemeralPostgres

BASE = 'base-20261103T030000Z'
MARKER = 'sentinel-backup-20261103T030000Z-123'


@pytest.fixture(scope='module')
def pg():
    server = _EphemeralPostgres(); server.start()
    try:
        yield server
    finally:
        server.stop()


@pytest.fixture
def conn(pg, monkeypatch):
    name = 'dashboard_ddl_' + uuid.uuid4().hex
    with psycopg.connect(pg.sync_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
    c = store.connect(pg.sync_dsn.rsplit('/', 1)[0] + '/' + name)
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'private-dashboard-migration-' * 4)
    try:
        schema.ensure_schema(c); store.migrate_schema(c)
        binding.bind(c, deployment_id='fixture-paper', broker='alpaca', broker_account_id='PA-fixture')
        broker = SimulatedBroker(account=BrokerAccountIdentity(broker='alpaca', account_id='PA-fixture'))
        for _ in range(2):
            journal.record_observation(c, asyncio.run(broker.observe()))
            broker.now += timedelta(seconds=1)
        c.execute('CREATE TABLE sentinel_backup_recovery_markers ('
                  'marker text PRIMARY KEY,created_at timestamptz NOT NULL DEFAULT now())')
        c.execute('INSERT INTO sentinel_backup_recovery_markers(marker) VALUES(%s)', (MARKER,))
        c.commit(); operational_schema.install_quiescent(c)
        for producer in (journal.bootstrap_observation_integrity, mirror_projection.bootstrap_step):
            for _ in range(20):
                value = producer(c, limit=128); c.commit()
                if value['body']['stage'] == 'COMPLETE':
                    break
            else:
                raise AssertionError('private fixture bootstrap did not complete')
        assert c.execute('SELECT count(*) FROM sentinel_observations').fetchone()[0] == 2
        c.rollback()
        yield c
    finally:
        c.close()
        with psycopg.connect(pg.sync_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))


def prefixes(c):
    values = {domain: copy.deepcopy(coverage._authenticated(c, domain)) for domain in migration.DOMAINS}
    c.rollback()
    return values


def unchanged_body(before, after):
    assert before['inventory'] != after['inventory']
    assert {k: v for k, v in before.items() if k != 'inventory'} == {
        k: v for k, v in after.items() if k != 'inventory'}


def failed_install(c):
    """Execute the actual PR564 schema-creation sequence without its repair."""
    with operational_schema.migration_transaction(c):
        with operational_schema._financial_writer(c):
            review_schema.install(c)


def witness(c):
    class PausedRestore:
        # Only the external physical-recovery observations are substituted.
        # Catalogs, HMACs, rows, inventory and read-only SQL use real PostgreSQL.
        def __getattr__(self, key):
            return getattr(c, key)
        def execute(self, statement, *args):
            if statement in ('SELECT pg_is_in_recovery()', 'SELECT pg_get_wal_replay_pause_state()'):
                class Result:
                    def fetchone(self):
                        return (True,) if 'pg_is_in_recovery' in statement else ('paused',)
                return Result()
            return c.execute(statement, *args)
    value = recovery.snapshot(PausedRestore(), backup=BASE, marker=MARKER, metadata_sha256='a' * 64)
    assert c.execute('SHOW transaction_read_only').fetchone()[0] == 'on'
    c.rollback()
    return value


def apply(c, value):
    return recovery.apply(c, value, expected_backup=BASE, expected_account='PA-fixture',
                          expected_deployment='fixture-paper')


def test_populated_predecessor_upgrade_keeps_both_prefixes_and_runtime_integrity(conn):
    before = prefixes(conn); epoch = operational_ddl_epoch.current(conn); conn.rollback()
    review_schema.install_quiescent(conn)
    assert operational_ddl_epoch.current(conn) == (epoch[0], epoch[1] + 3)
    for domain in migration.DOMAINS:
        unchanged_body(before[domain], coverage.require_current(conn, domain))
    journal.require_observation_integrity(conn)
    conn.rollback()


def test_actual_old_installer_reproduces_production_failure_and_removal_control(conn, monkeypatch):
    monkeypatch.setattr(migration, 'install', review_schema.install)
    review_schema.install_quiescent(conn)
    def upgrade_acceptance():
        for domain in migration.DOMAINS:
            coverage.require_current(conn, domain)
        journal.require_observation_integrity(conn)
    # The real healthy-upgrade acceptance fails when the repair is removed.
    with pytest.raises(coverage.EvidenceCoverageRefused, match='BINDING_CHANGED'):
        upgrade_acceptance()


def test_existing_schema_is_idempotent_and_never_repairs_stale_prefix(conn):
    failed_install(conn); before = prefixes(conn)
    epoch = operational_ddl_epoch.current(conn); conn.rollback()
    review_schema.install_quiescent(conn)
    assert operational_ddl_epoch.current(conn) == epoch
    assert prefixes(conn) == before
    with pytest.raises(coverage.EvidenceCoverageRefused, match='BINDING_CHANGED'):
        coverage.require_current(conn, 'OBSERVATION')


def test_successful_upgrade_repeat_has_no_ddl_or_prefix_write(conn):
    review_schema.install_quiescent(conn); before = prefixes(conn)
    epoch = operational_ddl_epoch.current(conn); conn.rollback()
    review_schema.install_quiescent(conn)
    assert operational_ddl_epoch.current(conn) == epoch
    assert prefixes(conn) == before


def test_absent_coverage_stays_absent_and_does_not_gain_readiness(conn):
    conn.execute('DELETE FROM sentinel_execution_evidence_coverage'); conn.commit()
    review_schema.install_quiescent(conn)
    assert prefixes(conn) == {'OBSERVATION': None, 'MIRROR': None}
    with pytest.raises(coverage.EvidenceCoveragePending, match='BOOTSTRAP'):
        coverage.require_current(conn, 'OBSERVATION')


def test_preexisting_epoch_drift_refuses_and_rolls_back_schema(conn):
    conn.execute('CREATE TABLE unrelated_prior_ddl(id integer)'); conn.commit()
    with pytest.raises(coverage.EvidenceCoverageRefused, match='BINDING_CHANGED'):
        review_schema.install_quiescent(conn)
    assert not review_schema.require_schema(conn, allow_absent=True)


@pytest.mark.parametrize('remove_guard', [False, True])
def test_unexpected_ddl_is_atomic_and_removed_epoch_guard_is_killed(conn, monkeypatch, remove_guard):
    original = review_schema.install
    def extra(c):
        original(c); c.execute('CREATE TABLE unexpected_dashboard_ddl(id integer)')
    monkeypatch.setattr(review_schema, 'install', extra)
    if remove_guard:
        source = inspect.getsource(migration.install)
        needle = 'require(operational_ddl_epoch.current(conn) == (epoch[0], epoch[1] + DDL_ADVANCE),'
        assert source.count(needle) == 1
        namespace = {}
        exec(compile(source.replace(needle, 'require(True,'), 'removed-dashboard-epoch-guard', 'exec'),
             vars(migration), namespace)
        monkeypatch.setattr(migration, 'install', namespace['install'])
    def check():
        with pytest.raises(migration.ReviewMigrationRefused, match='DDL advance differs'):
            review_schema.install_quiescent(conn)
    if remove_guard:
        with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
            check()
    else:
        check()
        assert not review_schema.require_schema(conn, allow_absent=True)
        assert conn.execute("SELECT to_regclass('unexpected_dashboard_ddl')").fetchone()[0] is None


def test_distinct_physical_witness_recovers_only_the_real_failed_transition(conn):
    document = witness(conn); before = prefixes(conn)
    failed_install(conn)
    result = apply(conn, document)
    assert result['schema'] == 'sentinel.dashboard-ddl-coverage-transfer/1'
    assert result['operational_ready'] is False and result['broker_contacted'] is False
    for domain in migration.DOMAINS:
        unchanged_body(before[domain], coverage.require_current(conn, domain))
    conn.rollback()
    with pytest.raises(recovery.RecoveryRefused, match='prefix changed'):
        apply(conn, document)


@pytest.mark.parametrize('change', ['signature', 'purpose', 'contract', 'backup', 'account', 'head', 'extra_ddl'])
def test_recovery_refuses_wrong_or_changed_proof(conn, change):
    document = witness(conn); failed_install(conn)
    if change == 'signature': document['hmac_sha256'] = '0' * 64
    elif change == 'purpose': document['witness']['schema_version'] = 'sentinel.chain-progress-coverage-witness/1'
    elif change == 'contract': document['witness']['review_contract_sha256'] = 'b' * 64
    elif change == 'backup': document['witness']['backup'] = 'base-20261102T030000Z'
    elif change == 'account': document['witness']['binding'][2] = 'foreign'
    elif change == 'head': document['witness']['heads']['OBSERVATION'][1] += 1
    elif change == 'extra_ddl':
        conn.execute('CREATE TABLE extra_dashboard_ddl(id integer)'); conn.commit()
    if change not in {'signature', 'purpose', 'extra_ddl'}:
        document['hmac_sha256'] = recovery._sign(document['witness'])
    before = prefixes(conn)
    expected = {
        'signature': (recovery.RecoveryRefused, 'authentication failed'),
        'purpose': (ValidationError, 'schema_version'),
        'contract': (recovery.RecoveryRefused, 'migration contract changed'),
        'backup': (recovery.RecoveryRefused, 'backup confirmation differs'),
        'account': (recovery.RecoveryRefused, 'account confirmation differs'),
        'head': (recovery.RecoveryRefused, 'tracking head changed'),
        'extra_ddl': (recovery.RecoveryRefused, 'DDL advance is not the exact dashboard migration'),
    }[change]
    with pytest.raises(expected[0], match=expected[1]):
        apply(conn, document)
    conn.rollback()
    assert prefixes(conn) == before


@pytest.mark.parametrize('remove_guard', [False, True])
def test_recovery_independently_refuses_untracked_source_edit_and_removed_guard(conn, remove_guard):
    document = witness(conn); failed_install(conn)
    conn.execute("SET LOCAL session_replication_role='replica'")
    conn.execute("UPDATE sentinel_observations SET completeness='PARTIAL'")
    conn.commit()
    method = recovery.apply
    if remove_guard:
        source = inspect.getsource(method)
        needle = "_require(_source_digests(conn)==value['sources'], 'watched source rows changed')"
        assert source.count(needle) == 1
        namespace = {}
        exec(compile(source.replace(needle, "_require(True, 'watched source rows changed')"),
                     'removed-dashboard-source-proof', 'exec'), vars(recovery), namespace)
        method = namespace['apply']
    def check():
        with pytest.raises(recovery.RecoveryRefused, match='watched source rows changed'):
            method(conn, document, expected_backup=BASE, expected_account='PA-fixture',
                   expected_deployment='fixture-paper')
    if remove_guard:
        with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
            check()
    else:
        check()


def test_primary_database_cannot_issue_a_pre_ddl_restore_witness(conn):
    with pytest.raises(recovery.RecoveryRefused, match='paused isolated physical restore'):
        recovery.snapshot(conn, backup=BASE, marker=MARKER, metadata_sha256='a' * 64)


def test_actual_paused_physical_restore_issues_witness_and_primary_recovers(conn, pg):
    import os
    import shutil
    import tempfile
    import time
    from pathlib import Path
    from tests.support.postgres import _find_pg_bin, _as_pg_user, _run
    restored = _EphemeralPostgres()
    base = Path(tempfile.mkdtemp(prefix='dashboard_ddl_physical_', dir=Path(pg.datadir).parent))
    try:
        if os.geteuid() == 0:
            shutil.chown(base, user='postgres', group='postgres')
        result = _run(_as_pg_user([_find_pg_bin('pg_basebackup'), '-h', '127.0.0.1',
            '-p', str(pg.port), '-U', pg.user, '-D', str(base), '-Fp', '-Xs', '-c', 'fast']))
        assert result.returncode == 0, result.stderr
        target = Path(restored.datadir)
        shutil.copytree(base, target, dirs_exist_ok=True)
        with (target / 'postgresql.auto.conf').open('a') as stream:
            stream.write("\nrecovery_target='immediate'\nrecovery_target_action='pause'\nrestore_command='false'\n")
        (target / 'recovery.signal').touch()
        if os.geteuid() == 0:
            for item in [target, *target.rglob('*')]:
                shutil.chown(item, user='postgres', group='postgres')
        result = _run(_as_pg_user([_find_pg_bin('pg_ctl'), '-D', str(target),
            '-o', f'-p {restored.port} -h 127.0.0.1 -k {target}', '-l', str(target / 'restored.log'),
            '-w', '-t', '30', 'start']))
        assert result.returncode == 0, result.stderr
        restored._started = True
        dsn = restored.sync_dsn.rsplit('/', 1)[0] + '/' + conn.info.dbname
        with psycopg.connect(dsn, autocommit=True) as observed:
            deadline = time.monotonic() + 15
            while observed.execute('SELECT pg_get_wal_replay_pause_state()').fetchone()[0] != 'paused':
                assert time.monotonic() < deadline
                time.sleep(.1)
        with store.connect(dsn) as recovered:
            document = recovery.snapshot(recovered, backup=BASE, marker=MARKER, metadata_sha256='a' * 64)
            assert recovered.execute('SHOW transaction_read_only').fetchone()[0] == 'on'
            assert recovered.execute('SELECT pg_is_in_recovery()').fetchone()[0] is True
        before = prefixes(conn)
        failed_install(conn)
        result = apply(conn, document)
        assert result['broker_contacted'] is False and result['operational_ready'] is False
        for domain in migration.DOMAINS:
            unchanged_body(before[domain], coverage.require_current(conn, domain))
        conn.rollback()
    finally:
        restored.stop()
        assert base.name.startswith('dashboard_ddl_physical_')
        shutil.rmtree(base)


@pytest.mark.parametrize('remove_guard', [False, True])
def test_source_head_change_during_ddl_refuses_and_removed_guard_is_killed(conn, monkeypatch, remove_guard):
    original = review_schema.install
    def changed(c):
        original(c)
        c.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) "
                  "VALUES('broker-observation:v4:unexpected','2026-11-03','{}'::jsonb)")
    monkeypatch.setattr(review_schema, 'install', changed)
    if remove_guard:
        source = inspect.getsource(migration.install)
        needle = 'require(coverage.head(conn, domain, lock=True) == coordinates,'
        assert source.count(needle) == 1
        namespace = {}
        exec(compile(source.replace(needle, 'require(True,'), 'removed-dashboard-head-guard', 'exec'),
             vars(migration), namespace)
        monkeypatch.setattr(migration, 'install', namespace['install'])
    def check():
        with pytest.raises(migration.ReviewMigrationRefused, match='evidence head changed'):
            review_schema.install_quiescent(conn)
    if remove_guard:
        with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
            check()
    else:
        check()
        assert not review_schema.require_schema(conn, allow_absent=True)


@pytest.mark.parametrize('remove_guard', [False, True])
def test_concurrent_publication_boundary_ddl_is_blocked_and_removed_lock_is_killed(conn, monkeypatch, remove_guard):
    document = witness(conn); failed_install(conn)
    method = recovery.apply
    if remove_guard:
        source = inspect.getsource(method)
        needle = ' | set(operational_ddl_epoch.extension_tables)'
        assert source.count(needle) == 1
        namespace = {}
        exec(compile(source.replace(needle, ''), 'removed-dashboard-ddl-lock', 'exec'),
             vars(recovery), namespace)
        method = namespace['apply']
    original = coverage.write
    outcomes = []
    def racing(database, domain, **kwargs):
        if not outcomes:
            with psycopg.connect(conn.info.dsn, autocommit=True) as other:
                other.execute("SET lock_timeout='150ms'")
                try:
                    other.execute('CREATE TABLE concurrent_dashboard_ddl(id integer)')
                except psycopg.errors.LockNotAvailable:
                    outcomes.append('blocked')
                else:
                    outcomes.append('allowed')
        return original(database, domain, **kwargs)
    monkeypatch.setattr(coverage, 'write', racing)
    result = method(conn, document, expected_backup=BASE, expected_account='PA-fixture',
                    expected_deployment='fixture-paper')
    assert result['operational_ready'] is False
    def check():
        assert outcomes == ['blocked'], 'concurrent DDL crossed the exact epoch check'
    if remove_guard:
        with pytest.raises(AssertionError, match='concurrent DDL crossed'):
            check()
    else:
        check()
