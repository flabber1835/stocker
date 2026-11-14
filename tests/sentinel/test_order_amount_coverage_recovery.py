"""Qualify the original failure and fixed installer with a populated v2 database."""
import asyncio
from contextlib import nullcontext
import uuid

import psycopg
from psycopg import sql

import pytest

from sentinel import binding, mirror_projection, operational_ddl_epoch, operational_ddl_handoff
from sentinel import operational_schema, order_amount_coverage_recovery as recovery, schema
from sentinel.execution import evidence_projection as coverage, journal
from sentinel.execution.contract import BrokerAccountIdentity
from sentinel.execution.simulator import SimulatedBroker
from sentinel.feed import runtime_schema as feed_schema, store
from sentinel.panel import review_schema
from tests.sentinel.test_dashboard_ddl_coverage import BASE, MARKER, prefixes, unchanged_body, pg
from tests.sentinel.test_fractional_order_amount import install_v2
from tests.support.postgres import paused_physical_restore


@pytest.fixture
def predecessor(pg, monkeypatch):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'private-order-amount-migration-' * 4)
    name = "order_ddl_" + uuid.uuid4().hex
    with psycopg.connect(pg.sync_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    with store.connect(pg.sync_dsn.rsplit("/", 1)[0] + "/" + name) as conn:
        install_v2(conn)
        store.migrate_schema(conn)
        binding.bind(conn, deployment_id='fixture-paper', broker='alpaca', broker_account_id='PA-fixture')
        broker = SimulatedBroker(account=BrokerAccountIdentity(broker='alpaca', account_id='PA-fixture'))
        journal.record_observation(conn, asyncio.run(broker.observe()))
        conn.execute("""INSERT INTO sentinel_commands(client_key,plan_id,security_id,revision,
            deployment_id,broker,broker_account_id,takeover_epoch,symbol,side,quantity,state,detail)
            VALUES ('old-key','old-plan','old-security',3,'fixture-paper','alpaca','PA-fixture',1,
                    'OLD','BUY',7,'FILLED','historical order')""")
        conn.execute('CREATE TABLE sentinel_backup_recovery_markers ('
                     'marker text PRIMARY KEY,created_at timestamptz NOT NULL DEFAULT now())')
        conn.execute('INSERT INTO sentinel_backup_recovery_markers(marker) VALUES(%s)', (MARKER,))
        conn.commit()
        operational_schema.install_quiescent(conn)
        review_schema.install_quiescent(conn)
        for produce in (journal.bootstrap_observation_integrity, mirror_projection.bootstrap_step):
            for _ in range(20):
                value = produce(conn, limit=128)
                conn.commit()
                if value['body']['stage'] == 'COMPLETE':
                    break
            else:
                raise AssertionError('fixture bootstrap did not complete')
        yield conn
        conn.rollback()


def witness(restored):
    return recovery.snapshot(restored, backup=BASE, marker=MARKER, metadata_sha256='a' * 64)


def apply(conn, document):
    return recovery.apply(conn, document, expected_backup=BASE,
                          expected_account='PA-fixture', expected_deployment='fixture-paper')


@pytest.mark.parametrize('remove_handoff', [False, True])
def test_installer_transfers_both_prefixes_across_exact_command_ddl(predecessor, monkeypatch, remove_handoff):
    conn = predecessor
    before = prefixes(conn)
    epoch = operational_ddl_epoch.current(conn)
    conn.rollback()
    if remove_handoff:
        monkeypatch.setattr(operational_ddl_handoff, 'transfer', lambda *args, **kwargs: nullcontext())
    schema.ensure_schema(conn)
    store.require_feed_schema(conn)
    assert operational_ddl_epoch.current(conn) == (epoch[0], epoch[1] + 3)
    if remove_handoff:
        with pytest.raises(coverage.EvidenceCoverageRefused, match='BINDING_CHANGED'):
            coverage.require_current(conn, 'OBSERVATION')
    else:
        for domain in recovery.DOMAINS:
            unchanged_body(before[domain], coverage.require_current(conn, domain))


def test_incompatible_feed_refuses_before_touching_an_evidenced_order_journal(predecessor, monkeypatch):
    conn = predecessor
    before = prefixes(conn)
    epoch = operational_ddl_epoch.current(conn)
    conn.rollback()

    def refuse(_conn):
        raise feed_schema.FeedSchemaRefused('feed predecessor fixture')

    monkeypatch.setattr(store, 'require_feed_schema', refuse)
    with pytest.raises(feed_schema.FeedSchemaRefused, match='feed predecessor fixture'):
        schema.ensure_schema(conn)
    assert operational_ddl_epoch.current(conn) == epoch
    with conn.cursor() as cur:
        assert schema._validate_ledgered(cur, schema._read_runtime_catalog(cur), allow_previous=True) == 2
    assert prefixes(conn) == before


@pytest.mark.parametrize('fault', [None, 'extra_ddl', 'changed_command', 'new_notional'])
def test_paused_restore_recovers_original_installer_without_rewriting_history(predecessor, pg, monkeypatch, fault):
    conn = predecessor
    with paused_physical_restore(pg, conn.info.dbname) as restored:
        document = witness(restored)
    before = prefixes(conn)
    monkeypatch.setattr(operational_ddl_handoff, 'transfer', lambda *args, **kwargs: nullcontext())
    schema.ensure_schema(conn)
    store.migrate_schema(conn)
    with pytest.raises(coverage.EvidenceCoverageRefused, match='BINDING_CHANGED'):
        coverage.require_current(conn, 'OBSERVATION')
    conn.rollback()
    if fault == 'extra_ddl':
        conn.execute('CREATE TABLE unrelated_ddl_falsifier(id integer)')
    elif fault == 'changed_command':
        conn.execute("UPDATE sentinel_commands SET detail='rewritten'")
    elif fault == 'new_notional':
        conn.execute('UPDATE sentinel_commands SET quantity=NULL,notional=7')
    conn.commit()
    if fault:
        with pytest.raises(recovery.RecoveryRefused, match={
                'extra_ddl': 'DDL advance', 'changed_command': 'historical command rows',
                'new_notional': 'new notional command'}[fault]):
            apply(conn, document)
        assert prefixes(conn) == before
    else:
        result = apply(conn, document)
        assert result['broker_contacted'] is False and result['operational_ready'] is False
        for domain in recovery.DOMAINS:
            unchanged_body(before[domain], coverage.require_current(conn, domain))
        assert conn.execute('SELECT quantity,notional,detail FROM sentinel_commands').fetchall() == [
            (7, None, 'historical order')]
        conn.rollback()
        with pytest.raises(recovery.RecoveryRefused, match='old authenticated prefix changed'):
            apply(conn, document)
