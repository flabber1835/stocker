"""Recover the original audited compaction on an isolated PostgreSQL cluster."""
import copy
import hashlib

import pytest

from sentinel import backup_compaction_coverage_recovery as recovery, operational_ddl_epoch
from sentinel.execution import evidence_projection as coverage
from sentinel.feed import acquisition_part_schema, retention_schema, store
from tests.sentinel.test_dashboard_ddl_coverage import BASE, MARKER, conn, pg, prefixes, unchanged_body
from tests.support.postgres import paused_physical_restore


@pytest.mark.parametrize('fault', [None, 'changed_command', 'extra_ddl'])
def test_physical_backup_proves_the_exact_compaction_and_installation(conn, pg, monkeypatch, fault):
    previous_ddl = next(statement for statement in acquisition_part_schema.DDL
                        if statement.startswith('CREATE OR REPLACE FUNCTION sentinel_acquisition_price_delete_guard'))
    assert hashlib.sha256(' '.join(previous_ddl.split('$$')[1].split()).encode()).hexdigest() == (
        recovery.PREDECESSOR_GUARD_SHA256)
    conn.execute(previous_ddl)
    # Seed the already-certified incident epoch before signing the old prefixes.
    incarnation, epoch = operational_ddl_epoch.current(conn)
    for _ in range(recovery.BEFORE_EPOCH - epoch):
        conn.execute(previous_ddl)
    conn.execute("""INSERT INTO sentinel_commands(client_key,plan_id,security_id,revision,
        deployment_id,broker,broker_account_id,takeover_epoch,symbol,side,quantity,state,detail)
        VALUES ('old-key','old-plan','old-security',3,'fixture-paper','alpaca','PA-fixture',1,
                'OLD','BUY',7,'FILLED','original command')""")
    for domain in recovery.DOMAINS:
        old = coverage._authenticated(conn, domain)
        coverage.write(conn, domain, through=old['through'], body=old['body'])
    conn.commit()
    old_prefixes = prefixes(conn)
    with paused_physical_restore(pg, conn.info.dbname) as restored:
        replay_end = restored.execute('SELECT pg_last_wal_replay_lsn()::text').fetchone()[0]
        restored.rollback()
        monkeypatch.setattr(recovery, 'PRE_COMPACTION_BASE', BASE)
        with pytest.raises(recovery.shared.RecoveryRefused, match='wrong compaction replay point'):
            recovery.snapshot(restored, backup=BASE, marker=MARKER, metadata_sha256='a' * 64)
        restored.rollback()
        monkeypatch.setattr(recovery, 'PRE_COMPACTION_REPLAY_END', replay_end)
        document = recovery.snapshot(restored, backup=BASE, marker=MARKER, metadata_sha256='a' * 64)
    assert document['witness']['ddl'] == [incarnation, recovery.BEFORE_EPOCH]

    for _ in range(134):
        conn.execute(retention_schema.ACQUISITION_PRICE_DELETE_GUARD)
        conn.execute(previous_ddl)
    conn.commit()
    assert operational_ddl_epoch.current(conn) == (incarnation, 410)
    conn.rollback()
    store.migrate_schema(conn)
    assert operational_ddl_epoch.current(conn) == (incarnation, recovery.AFTER_EPOCH)
    for domain in recovery.DOMAINS:
        with pytest.raises(coverage.EvidenceCoverageRefused, match='BINDING_CHANGED'):
            coverage.require_current(conn, domain)
    conn.rollback()

    def apply(witness):
        return recovery.apply(conn, witness, expected_backup=BASE, expected_account='PA-fixture',
                              expected_deployment='fixture-paper')

    tampered = copy.deepcopy(document)
    tampered['witness']['metadata_sha256'] = 'b' * 64
    with pytest.raises(recovery.shared.RecoveryRefused, match='authentication failed'):
        apply(tampered)

    if fault:
        if fault == 'changed_command':
            conn.execute("UPDATE sentinel_commands SET detail='tampered command'")
        else:
            conn.execute('CREATE TABLE public.extra_compaction_ddl(id int)')
        conn.commit()
        expected = 'watched source rows changed' if fault == 'changed_command' else 'DDL advance'
        with pytest.raises(recovery.shared.RecoveryRefused, match=expected):
            apply(document)
        conn.rollback()
        assert prefixes(conn) == old_prefixes
        return

    result = apply(document)
    assert result['operational_ready'] is False and result['broker_contacted'] is False
    for domain in recovery.DOMAINS:
        unchanged_body(old_prefixes[domain], coverage.require_current(conn, domain))
    assert conn.execute('SELECT enabled,kill_switch_engaged FROM sentinel_automation_control').fetchone() == (
        False, True)
    assert conn.execute('SELECT detail FROM sentinel_commands').fetchone() == ('original command',)
    conn.rollback()
    with pytest.raises(recovery.shared.RecoveryRefused, match='old authenticated prefix changed'):
        apply(document)
