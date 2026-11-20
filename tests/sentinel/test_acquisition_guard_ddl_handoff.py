"""Exercise retained financial evidence through the real feed migration entry."""
import pytest

from sentinel import deployment_fence, operational_ddl_epoch as epoch, operational_ddl_handoff as handoff
from sentinel.operational_schema import OperationalSchemaRefused
from sentinel.execution import evidence_projection as coverage, journal
from sentinel.feed import acquisition_guard_migration as guards, runtime_schema, store
from tests.sentinel.test_dashboard_ddl_coverage import conn, pg, prefixes, unchanged_body
from tests.support import coverage_feed_ddl


def predecessor(connection):
    coverage_feed_ddl.install(connection, coverage_feed_ddl.catalog.POST_COMPACTION)


pytestmark = pytest.mark.parametrize('conn', [predecessor], indirect=True)


def test_guard_upgrade_and_second_install_preserve_authenticated_prefixes(conn):
    guards.require_predecessor(conn)
    initial = prefixes(conn)
    before = epoch.current(conn)
    binding = coverage.binding(conn)
    heads = {d: coverage.head(conn, d) for d in handoff.DOMAINS}
    store.migrate_schema(conn)
    guards.require_successor(conn)
    assert epoch.current(conn) == (before[0], before[1]+4)
    assert coverage.binding(conn) == binding
    for domain in handoff.DOMAINS:
        unchanged_body(initial[domain], coverage.require_current(conn, domain))
        assert coverage.head(conn, domain) == heads[domain]
    first = prefixes(conn)
    store.migrate_schema(conn)
    assert epoch.current(conn) == (before[0], before[1]+4)
    assert prefixes(conn) == first


def test_partial_and_absent_proofs_retain_their_own_state(conn):
    conn.execute('DELETE FROM sentinel_execution_evidence_coverage')
    conn.commit()
    partial = journal.bootstrap_observation_integrity(conn, limit=1)
    conn.commit()
    assert partial['body']['stage'] != 'COMPLETE'
    assert coverage.load(conn, 'MIRROR') is None
    store.migrate_schema(conn)
    unchanged_body(partial, coverage.load(conn, 'OBSERVATION'))
    assert coverage.load(conn, 'MIRROR') is None
    with pytest.raises(coverage.EvidenceCoveragePending):
        coverage.require_current(conn, 'OBSERVATION')


def test_original_full_replay_reproduces_the_stale_proofs_and_no_automatic_repair(conn):
    initial = prefixes(conn)
    before = epoch.current(conn)
    for statement in runtime_schema.DDL:
        conn.execute(statement)
    conn.commit()
    assert epoch.current(conn) == (before[0], before[1]+67)
    guards.require_successor(conn)
    for domain in handoff.DOMAINS:
        with pytest.raises(coverage.EvidenceCoverageRefused, match='EVIDENCE_COVERAGE_BINDING_CHANGED'):
            coverage.require_current(conn, domain)
    with pytest.raises(coverage.EvidenceCoverageRefused, match='EVIDENCE_COVERAGE_BINDING_CHANGED'):
        store.migrate_schema(conn)
    assert prefixes(conn) == initial


@pytest.mark.parametrize('fault', ['unfenced', 'stale_predecessor', 'bad_hmac', 'changed_binding', 'unknown_function',
                                   'writer_busy', 'extra_ddl', 'second_domain_failure'])
def test_guard_upgrade_refusals_are_atomic(conn, monkeypatch, fault):
    initial = prefixes(conn)
    if fault == 'unfenced':
        conn.execute('UPDATE sentinel_automation_control SET kill_switch_engaged=false WHERE id=1')
        conn.commit()
    elif fault == 'stale_predecessor':
        conn.execute('CREATE TABLE public.unrelated_ddl(x integer)')
        conn.commit()
    elif fault == 'bad_hmac':
        conn.execute("UPDATE sentinel_execution_evidence_coverage SET hmac_sha256=repeat('0',64) WHERE domain='MIRROR'")
        conn.commit()
    elif fault == 'changed_binding':
        conn.execute("UPDATE sentinel_account_binding SET established_at=established_at+interval '1 microsecond' WHERE id=1")
        conn.commit()
    elif fault == 'unknown_function':
        conn.execute('CREATE FUNCTION sentinel_acquisition_retention_locks() RETURNS void LANGUAGE sql AS $$ SELECT $$')
        for domain, payload in initial.items():
            coverage.write(conn, domain, through=payload['through'], body=payload['body'])
        conn.commit()
        with pytest.raises(runtime_schema.FeedSchemaRefused, match='unexpected acquisition function'):
            guards.require_predecessor(conn)
    elif fault == 'extra_ddl':
        apply = guards._apply_guard_ddl
        def extra(connection):
            apply(connection)
            connection.execute('CREATE TABLE public.unexpected_extra_upgrade(x integer)')
        monkeypatch.setattr(guards, '_apply_guard_ddl', extra)
    elif fault == 'second_domain_failure':
        write = coverage.write
        def reject_second(connection, domain, **kwargs):
            if domain == 'MIRROR':
                raise coverage.EvidenceCoverageRefused('fixture second domain refused')
            return write(connection, domain, **kwargs)
        monkeypatch.setattr(coverage, 'write', reject_second)
    rows = list(conn.execute('SELECT domain,payload,hmac_sha256 FROM sentinel_execution_evidence_coverage ORDER BY domain'))
    before = epoch.current(conn)
    conn.rollback()
    with store.connect(conn.info.dsn) as peer:
        if fault == 'writer_busy':
            peer.execute('SELECT pg_advisory_xact_lock(%s)', (journal.WRITER_LOCK_KEY,))
        failures = {
            'unfenced': (deployment_fence.DeploymentFenceRefused, 'durable kill'),
            'stale_predecessor': (coverage.EvidenceCoverageRefused, 'BINDING_CHANGED'),
            'bad_hmac': (coverage.EvidenceCoverageRefused, 'AUTHENTICATION_FAILED'),
            'changed_binding': (coverage.EvidenceCoverageRefused, 'EVIDENCE_COVERAGE_BINDING_CHANGED'),
            'unknown_function': (runtime_schema.FeedSchemaRefused, 'unexpected acquisition function'),
            'writer_busy': (OperationalSchemaRefused, 'FINANCIAL_WRITER_BUSY'),
            'extra_ddl': (runtime_schema.FeedSchemaRefused, 'DDL advance differs'),
            'second_domain_failure': (coverage.EvidenceCoverageRefused, 'fixture second domain refused'),
        }
        error, reason = failures[fault]
        with pytest.raises(error, match=reason):
            store.migrate_schema(conn)
    assert epoch.current(conn) == before
    assert list(conn.execute('SELECT domain,payload,hmac_sha256 FROM sentinel_execution_evidence_coverage ORDER BY domain')) == rows
    assert conn.execute("SELECT to_regprocedure('public.sentinel_acquisition_binding_insert_guard()')").fetchone() == (None,)
    assert conn.execute("SELECT to_regclass('public.unexpected_extra_upgrade')").fetchone() == (None,)
