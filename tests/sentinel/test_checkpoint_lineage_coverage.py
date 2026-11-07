"""Populated pre-index upgrade keeps signed prefixes across exact owned DDL."""
from contextlib import contextmanager
import copy
import inspect

import psycopg
import pytest

from sentinel import checkpoint_lineage_access as access
from sentinel import operational_ddl_epoch, operational_ddl_handoff as handoff, operational_schema
from sentinel.execution import evidence_projection as coverage, journal
from tests.sentinel.test_dashboard_ddl_coverage import conn, pg, prefixes, unchanged_body  # noqa: F401


@pytest.fixture(autouse=True)
def preindex_registry(monkeypatch):
    # The imported fixture makes real observations and COMPLETE prefixes. Only
    # predecessor installation lacks the newly introduced access-path component.
    selected = operational_schema.ACCESS_PATH_COMPONENTS
    monkeypatch.setattr(operational_schema, 'ACCESS_PATH_COMPONENTS', ())
    return selected


@pytest.fixture
def predecessor(conn, preindex_registry, monkeypatch):
    monkeypatch.setattr(operational_schema, 'ACCESS_PATH_COMPONENTS', preindex_registry)
    assert access.require_schema(conn, allow_absent=True) is False
    original = copy.deepcopy(operational_schema.installation(conn, required=True))
    for domain in handoff.DOMAINS:
        coverage.require_current(conn, domain)
    conn.rollback()
    return original


def current(c):
    for domain in handoff.DOMAINS:
        coverage.require_current(c, domain)
    journal.require_observation_integrity(c)


def generic_step(c, callback, *, advance=1):
    with operational_schema.migration_transaction(c):
        with operational_schema._financial_writer(c):
            with handoff.transfer(c, expected_advance=advance,
                    label='checkpoint lineage migration', refusal=access.AccessPathRefused):
                callback(c)


def test_populated_complete_preindex_upgrade_preserves_sources_and_prefixes(conn, predecessor):
    before = prefixes(conn)
    epoch = operational_ddl_epoch.current(conn)
    heads = {domain:coverage.head(conn, domain) for domain in handoff.DOMAINS}
    rows = conn.execute('SELECT cursor_name,session,state,updated_at FROM '
                        'sentinel_processed_sessions ORDER BY cursor_name').fetchall()
    conn.rollback()
    assert operational_schema.install_quiescent(conn) == predecessor
    assert operational_ddl_epoch.current(conn) == (epoch[0], epoch[1]+2)
    assert {domain:coverage.head(conn, domain) for domain in handoff.DOMAINS} == heads
    for domain in handoff.DOMAINS:
        unchanged_body(before[domain], coverage.require_current(conn, domain))
    assert conn.execute('SELECT cursor_name,session,state,updated_at FROM '
        'sentinel_processed_sessions WHERE cursor_name<>%s ORDER BY cursor_name',
        (access.CURSOR,)).fetchall() == rows
    assert operational_schema.installation(conn) == predecessor
    current(conn)
    print('PG16_CHECKPOINT_HANDOFF_ACTUAL_EPOCH_ADVANCE=2', flush=True)


def test_removed_handoff_reproduces_binding_changed_on_real_complete_prefixes(conn, predecessor, monkeypatch):
    @contextmanager
    def removed(*_args, **_kwargs):
        yield
    monkeypatch.setattr(handoff, 'transfer', removed)
    operational_schema.install_quiescent(conn)
    assert access.require_schema(conn)
    with pytest.raises(coverage.EvidenceCoverageRefused, match='BINDING_CHANGED'):
        current(conn)


@pytest.mark.parametrize('state', ['absent','pending'])
def test_absent_and_real_pending_prefixes_never_gain_readiness(conn, predecessor, state):
    if state == 'absent':
        conn.execute('DELETE FROM sentinel_execution_evidence_coverage')
    else:
        conn.execute("DELETE FROM sentinel_execution_evidence_coverage WHERE domain='OBSERVATION'")
        pending = journal.bootstrap_observation_integrity(conn, limit=1)
        assert pending['body']['stage'] != 'COMPLETE'
    conn.commit()
    before = prefixes(conn)
    operational_schema.install_quiescent(conn)
    for domain, payload in before.items():
        after = coverage.load(conn, domain)
        if payload is None:
            assert after is None
        else:
            unchanged_body(payload, after)
    with pytest.raises(coverage.EvidenceCoveragePending):
        coverage.require_current(conn, 'OBSERVATION')


def test_stale_prefix_refuses_before_new_ddl_and_is_not_repaired(conn, predecessor):
    conn.execute('CREATE TABLE prior_unowned_ddl(id integer)');conn.commit()
    before = prefixes(conn)
    with pytest.raises(coverage.EvidenceCoverageRefused, match='BINDING_CHANGED'):
        operational_schema.install_quiescent(conn)
    assert access.require_schema(conn, allow_absent=True) is False
    assert prefixes(conn) == before


def test_already_installed_component_never_rebinds_stale_coverage(conn, predecessor):
    operational_schema.install_quiescent(conn)
    conn.execute('CREATE TABLE later_unowned_ddl(id integer)');conn.commit()
    before = prefixes(conn)
    epoch = operational_ddl_epoch.current(conn);conn.rollback()
    operational_schema.install_quiescent(conn)
    assert operational_ddl_epoch.current(conn) == epoch
    assert prefixes(conn) == before
    with pytest.raises(coverage.EvidenceCoverageRefused, match='BINDING_CHANGED'):
        current(conn)


def test_caller_failure_rolls_back_ddl_marker_and_transferred_signatures(conn, predecessor, monkeypatch):
    before = prefixes(conn)
    epoch = operational_ddl_epoch.current(conn);conn.rollback()
    real = operational_schema._install_access_paths
    def late_failure(*args, **kwargs):
        real(*args, **kwargs)
        raise RuntimeError('private qualification failure after actual handoff')
    monkeypatch.setattr(operational_schema, '_install_access_paths', late_failure)
    with pytest.raises(RuntimeError, match='after actual handoff'):
        operational_schema.install_quiescent(conn)
    assert access.require_schema(conn, allow_absent=True) is False
    assert operational_ddl_epoch.current(conn) == epoch
    assert prefixes(conn) == before
    current(conn)


@pytest.mark.parametrize('remove_guard', [False,True])
@pytest.mark.parametrize('drift', ['epoch','head','source','prefix'])
def test_generic_drift_guards_and_executed_removals(conn, predecessor, monkeypatch, drift, remove_guard):
    suffix = {'epoch':'DDL advance differs','head':'evidence head changed',
              'source':'source inventory changed','prefix':'authenticated prefix changed'}[drift]
    before = prefixes(conn)
    def change(c):
        if drift == 'source':
            c.execute('ALTER TABLE sentinel_processed_sessions SET UNLOGGED')
            return
        c.execute('CREATE TABLE planned_owned_ddl(id integer)')
        if drift == 'epoch':
            c.execute('CREATE TABLE unplanned_ddl(id integer)')
        elif drift == 'head':
            c.execute("INSERT INTO sentinel_processed_sessions(cursor_name,session,state) "
                      "VALUES('broker-observation:v4:unexpected','2026-11-06','{}'::jsonb)")
        else:
            old = before['OBSERVATION']
            coverage.write(c, 'OBSERVATION', through=old['through'],
                           body={**old['body'],'private_drift':True})
    if remove_guard:
        real = handoff._require
        def missing(value, reason, refusal):
            if not reason.endswith(suffix):
                real(value, reason, refusal)
        monkeypatch.setattr(handoff, '_require', missing)
    def check():
        with pytest.raises(access.AccessPathRefused, match=suffix):
            generic_step(conn, change)
    if remove_guard:
        with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
            check()
    else:
        check()
        assert prefixes(conn) == before
        current(conn)


@pytest.mark.parametrize('remove_guard', [False,True])
def test_rebound_fields_guard_and_executed_removal(conn, predecessor, monkeypatch, remove_guard):
    real_write = coverage.write
    def changed(c, domain, **kwargs):
        return real_write(c, domain, through=kwargs['through'],
                          body={**kwargs['body'],'private_drift':True})
    monkeypatch.setattr(coverage, 'write', changed)
    if remove_guard:
        real = handoff._require
        monkeypatch.setattr(handoff, '_require', lambda value,reason,refusal:
            None if reason.endswith('changed prefix content') else real(value,reason,refusal))
    def check():
        with pytest.raises(access.AccessPathRefused, match='changed prefix content'):
            generic_step(conn, lambda c:c.execute('CREATE TABLE planned_owned_ddl(id integer)'))
    if remove_guard:
        with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
            check()
    else:
        check()
        current(conn)


@pytest.mark.parametrize('remove_lock', [False,True])
def test_epoch_relation_lock_blocks_concurrent_ddl_and_removal_is_killed(conn, predecessor, monkeypatch, remove_lock):
    if remove_lock:
        source = inspect.getsource(handoff.transfer.__wrapped__)
        needle = 'sql.Identifier(name) for name in sorted(names)'
        assert source.count(needle) == 1
        namespace = {}
        exec(compile(source.replace(needle,
            'sql.Identifier(name) for name in sorted(names - operational_ddl_epoch.extension_tables)'),
            'removed-epoch-relation-lock','exec'),vars(handoff),namespace)
        monkeypatch.setattr(handoff, 'transfer', namespace['transfer'])
    outcomes = []
    def planned(c):
        # Race before our first DDL's event-trigger UPDATE owns the epoch row.
        # After that UPDATE the row lock alone would hide a missing SHARE lock.
        with psycopg.connect(conn.info.dsn,autocommit=True) as other:
            other.execute("SET lock_timeout='150ms'")
            try:
                other.execute('CREATE TABLE concurrent_unowned_ddl(id integer)')
            except psycopg.errors.LockNotAvailable:
                outcomes.append('blocked')
            else:
                outcomes.append('allowed')
        c.execute('CREATE TABLE planned_owned_ddl(id integer)')
    if remove_lock:
        # The independent epoch guard still refuses the now-observed extra DDL.
        with pytest.raises(access.AccessPathRefused,match='DDL advance differs'):
            generic_step(conn,planned)
        with pytest.raises(AssertionError,match='concurrent DDL crossed'):
            assert outcomes == ['blocked'], 'concurrent DDL crossed the exact epoch boundary'
    else:
        generic_step(conn,planned)
        assert outcomes == ['blocked']
        current(conn)
