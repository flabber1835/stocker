"""Replay the original protected #612 -> #613 installation on a physical database."""
import copy
from dataclasses import replace

import pytest

from sentinel import acquisition_coverage_recovery as recovery
from sentinel import operational_ddl_epoch, schema
from sentinel.execution import evidence_projection as coverage
from sentinel.feed import acquisition_guard_migration as guards, runtime_schema
from tests.sentinel.test_dashboard_ddl_coverage import BASE, MARKER, conn, pg, prefixes, unchanged_body
from tests.support import coverage_feed_ddl as archive
from tests.support.postgres import paused_physical_restore


def released_predecessor(database):
    archive.install(database, archive.catalog.POST_COMPACTION)


def replay_original_install(database, *, tamper_catalog):
    # Actual protected merge eb71429da. Preserve the original fallback's full
    # SQL sequence after future installers cease to replay these 339 statements.
    statements = list(runtime_schema.DDL)
    assert len(statements) == 339
    assert coverage.digest(statements) == '10c9b99e796d5177d093f8cfe3305d371accdd8e813979c80c866a83d82231ec'
    schema.ensure_schema(database)
    with pytest.raises(runtime_schema.FeedSchemaRefused):
        runtime_schema.require_feed_schema(database)
    database.rollback()
    with database.cursor() as cur:
        cur.execute('SELECT pg_try_advisory_xact_lock(%s,%s)', runtime_schema._SCHEMA_LOCK)
        assert cur.fetchone() == (True,)
        changed = False
        for statement in statements:
            if tamper_catalog and statement.startswith(
                    'CREATE OR REPLACE FUNCTION sentinel_acquisition_binding_insert_guard()'):
                statement = statement.replace('LANGUAGE plpgsql', 'SECURITY DEFINER LANGUAGE plpgsql')
                changed = True
            cur.execute(statement)
        assert changed == tamper_catalog
        runtime_schema._validate_catalog(schema._read_runtime_catalog(cur))
        runtime_schema._validate_views(cur)
    database.commit()


def apply(database, document, **overrides):
    args = dict(expected_backup=BASE, expected_account='PA-fixture', expected_deployment='fixture-paper')
    return recovery.apply(database, document, **(args | overrides))


def test_snapshot_rejects_a_primary(conn):
    with pytest.raises(recovery.shared.RecoveryRefused, match='paused isolated physical restore'):
        recovery.snapshot(conn, backup=BASE, marker=MARKER, metadata_sha256='a' * 64)
    conn.rollback()


@pytest.mark.parametrize('conn', [released_predecessor], indirect=True)
@pytest.mark.parametrize('fault', [None, 'command_bytes', 'function_security', 'extra_ddl'])
def test_paused_physical_release_upgrade(conn, pg, monkeypatch, fault):
    # Bring this database to the already audited incident epoch *before* it
    # signs its population. The subsequent 67 events must come from #613.
    guards.require_predecessor(conn)
    incarnation, start = operational_ddl_epoch.current(conn)
    previous_guard = archive.price_delete_guard(archive.catalog.POST_COMPACTION)
    for _ in range(recovery.BEFORE_EPOCH - start):
        conn.execute(previous_guard)
    conn.execute("""INSERT INTO sentinel_commands(client_key,plan_id,security_id,revision,
        deployment_id,broker,broker_account_id,takeover_epoch,symbol,side,quantity,state,detail)
        VALUES ('historical','previous','old',1,'fixture-paper','alpaca','PA-fixture',1,
                'STOCK','BUY',2,'FILLED','previous execution')""")
    for domain in recovery.DOMAINS:
        previous = coverage._authenticated(conn, domain)
        coverage.write(conn, domain, through=previous['through'], body=previous['body'])
    conn.commit()
    before = prefixes(conn)
    with paused_physical_restore(pg, conn.info.dbname) as restored:
        system = recovery._system(restored)
        end = restored.execute('SELECT pg_last_wal_replay_lsn()::text').fetchone()[0]
        restored.rollback()
        selected = recovery.PhysicalBackup(BASE, MARKER, 'a' * 64, system, end)
        with monkeypatch.context() as wrong:
            wrong.setattr(recovery, 'BACKUP', replace(selected, replay_end_lsn='0/0'))
            with pytest.raises(recovery.shared.RecoveryRefused, match='backup or replay point'):
                recovery.snapshot(restored, backup=BASE, marker=MARKER, metadata_sha256='a' * 64)
        restored.rollback()
        monkeypatch.setattr(recovery, 'BACKUP', selected)
        document = recovery.snapshot(restored, backup=BASE, marker=MARKER, metadata_sha256='a' * 64)
    assert document['witness']['ddl'] == [incarnation, recovery.BEFORE_EPOCH]
    assert recovery.EXTRA_SOURCES <= document['witness']['sources'].keys()
    replay_original_install(conn, tamper_catalog=(fault == 'function_security'))
    assert operational_ddl_epoch.current(conn) == (incarnation, recovery.AFTER_EPOCH)
    assert recovery.AFTER_EPOCH - recovery.BEFORE_EPOCH == 67
    for domain in recovery.DOMAINS:
        with pytest.raises(coverage.EvidenceCoverageRefused, match='BINDING_CHANGED'):
            coverage.require_current(conn, domain)
    conn.rollback()

    if fault == 'command_bytes':
        conn.execute("UPDATE sentinel_commands SET detail='changed economics evidence'")
        conn.commit()
        with pytest.raises(recovery.shared.RecoveryRefused, match='source rows changed in sentinel_commands'):
            apply(conn, document)
    elif fault == 'function_security':
        with pytest.raises(runtime_schema.FeedSchemaRefused, match='functions differ'):
            apply(conn, document)
    elif fault == 'extra_ddl':
        conn.execute('CREATE TABLE public.unrelated_migration(id int)')
        conn.commit()
        with pytest.raises(recovery.shared.RecoveryRefused, match='DDL advance'):
            apply(conn, document)
    else:
        with pytest.raises(recovery.shared.RecoveryRefused, match='account confirmation differs'):
            apply(conn, document, expected_account='other')
        altered = copy.deepcopy(document)
        altered['witness']['metadata_sha256'] = 'b' * 64
        with pytest.raises(recovery.shared.RecoveryRefused, match='authentication failed'):
            apply(conn, altered)
        # A valid HMAC for another backup still carries no authority for this transition.
        altered['hmac_sha256'] = recovery._sign(altered['witness'])
        with pytest.raises(recovery.shared.RecoveryRefused, match='backup or replay point'):
            apply(conn, altered)
        with monkeypatch.context() as interrupted:
            original = coverage.write
            def fail_second(database, domain, **kwargs):
                if domain == 'MIRROR':
                    raise RuntimeError('simulated second transfer failure')
                return original(database, domain, **kwargs)
            interrupted.setattr(coverage, 'write', fail_second)
            with pytest.raises(RuntimeError, match='simulated second transfer failure'):
                apply(conn, document)
        assert prefixes(conn) == before
        receipt = apply(conn, document)
        assert receipt['schema'] == recovery.RESULT_SCHEMA
        assert receipt['witness_content_sha256'] == coverage.digest(document)
        assert receipt['broker_contacted'] is False and receipt['operational_ready'] is False
        for domain in recovery.DOMAINS:
            current = coverage.require_current(conn, domain)
            unchanged_body(before[domain], current)
            assert receipt['prefixes'][domain] == recovery.shared._prefix_digest(current)
        assert conn.execute('SELECT enabled,kill_switch_engaged FROM sentinel_automation_control').fetchone() == (
            False, True)
        assert conn.execute('SELECT detail FROM sentinel_commands').fetchone() == ('previous execution',)
        conn.rollback()
        with pytest.raises(recovery.shared.RecoveryRefused, match='old authenticated prefix changed'):
            apply(conn, document)
        return
    assert prefixes(conn) == before
