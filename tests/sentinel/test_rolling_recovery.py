"""Real PostgreSQL recovery with dated receipts and continuous economic control."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid

import psycopg
from psycopg import sql
import pytest

from sentinel import rolling_runtime as runtime, rolling_authority as authority
from sentinel import rolling_recovery as recovery, rolling_reconstruction_evidence as evidence
from sentinel import rolling_daily_checkpoint as checkpoints, rolling_initialization as initial
from sentinel import rolling_checkpoint as origin, shadow_observation as shadow, shadow_service, shadow_runtime
from sentinel.feed import operational_snapshot as op, publication, retention, runtime_schema, store
from sentinel.feed import calendar, rolling_go_inputs as inputs
from tests.sentinel.test_rolling_go_inputs import issuer_source, ready  # noqa: F401
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401
from tests.sentinel.test_rolling_initialization import OBS
from tests.sentinel.test_rolling_daily import refresh


@pytest.fixture
def dated_source(issuer_source, monkeypatch):
    # Model actual publication-time availability, before creating the signed
    # receipt. No stored receipt, availability guard or deadline is bypassed.
    original = publication._insert_receipted_publication
    def insert(conn, **kwargs):
        kwargs['published_at'] = datetime.fromisoformat(kwargs['window_end']).replace(
            tzinfo=timezone.utc) + timedelta(days=1, hours=4) + issuer_source.get('publication_delay', timedelta())
        return original(conn, **kwargs)
    monkeypatch.setattr(publication, '_insert_receipted_publication', insert)
    return issuer_source


@pytest.fixture
def published(dated_source, ready):
    return ready


def advance(conn, session='2026-09-14'):
    return runtime.advance(conn, through=session, observation_id=OBS, starting_cash=100_000)


def step(conn, through):
    return runtime.service_advance(conn, through=through, observation_id=OBS, starting_cash=100_000)


def clock(monkeypatch, session):
    now = datetime.fromisoformat(session).replace(tzinfo=timezone.utc) + timedelta(days=1, hours=4)
    monkeypatch.setattr(initial, '_now', lambda _: now)
    monkeypatch.setattr(op, '_now', lambda: now)
    monkeypatch.setattr(calendar, 'latest_closed_session', lambda now=None: session)
    return now


@pytest.mark.parametrize('stop_shock', [False, True])
def test_interrupted_book_matches_continuous_production_run(conn, pg, published, dated_source, monkeypatch, stop_shock):
    advance(conn)
    refresh(conn, dated_source, monkeypatch)
    held = advance(conn, '2026-09-15')
    assert held.state.wealth_core['episodes'] and held.state.wealth_core['cash'] < 100_000
    if stop_shock:
        original = op.prepare
        def falling_market(*args, **kwargs):
            if max(row['date'] for row in dated_source['SEP']) == '2026-09-16':
                for row in dated_source['SEP']:
                    if row['date'] == '2026-09-16':
                        row.update(open='40', close='40', closeunadj='80')
            return original(*args, **kwargs)
        monkeypatch.setattr(op, 'prepare', falling_market)
    genesis = origin.read(conn).genesis_sha256
    dsn = conn.info.dsn
    database = conn.info.dbname
    conn.commit()
    conn.close()
    clone = 'recovery_' + uuid.uuid4().hex
    with psycopg.connect(pg.sync_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL('CREATE DATABASE {} TEMPLATE {}').format(sql.Identifier(clone), sql.Identifier(database)))
    try:
        with psycopg.connect(dsn) as continuous, psycopg.connect(dsn, dbname=clone) as interrupted:
            expected = {}
            for session in ('2026-09-16', '2026-09-17', '2026-09-18'):
                refresh(continuous, dated_source, monkeypatch)
                expected[session] = advance(continuous, session)
                inputs._prepare(interrupted, target_session=session)
            intermediate = interrupted.execute(
                "SELECT s.candidate_id FROM sentinel_operational_snapshots s "
                "JOIN sentinel_corpus_publications p ON p.version=s.publication_version WHERE p.window_end='2026-09-16'").fetchone()[0]
            pins = interrupted.execute('SELECT sentinel_snapshot_pins(%s)', (intermediate,)).fetchone()[0]
            assert 'UNCONSUMED_RECOVERY_INPUT' in pins
            interrupted.rollback()
            for _ in range(3):
                retention.maintain(interrupted)
            assert interrupted.execute('SELECT count(*) FROM sentinel_snapshot_bars WHERE candidate_id=%s',
                                       (intermediate,)).fetchone()[0] > 0
            interrupted.rollback()
            for session in ('2026-09-16', '2026-09-17'):
                result = step(interrupted, '2026-09-18')
                assert result.session == session
                assert result.state.to_dict() == expected[session].state.to_dict()
                assert result.verification == shadow.CANDIDATE
                assert result.shadow_verdict == shadow.NOT_DEPLOYABLE
                assert result.verification_scope == 'ROLLING_RECONSTRUCTION_ONLY'
                # Restore through a separate connection, not the in-memory observer.
                with psycopg.connect(dsn, dbname=clone) as restarted:
                    _, _, restored, receipt, _ = runtime._closure(restarted, initial._context(OBS, 100_000))
                    assert restored.state.to_dict() == result.state.to_dict()
                    assert isinstance(receipt, authority.ReconstructionReceipt)
                    from sentinel import restore_validation
                    monkeypatch.setattr(restore_validation.feed_store, 'require_feed_schema',
                                        runtime_schema.require_feed_schema)
                    report = restore_validation.validate_restored_database(restarted)
                    assert report['transaction_read_only']
                    assert report['rolling']['reconstructed']
                    assert not report['rolling']['attested']
            final = step(interrupted, '2026-09-18')
            assert final.state.to_dict() == expected['2026-09-18'].state.to_dict()
            assert final.verification == shadow.VERIFIED
            assert origin.read(interrupted).genesis_sha256 == genesis
            assert final.starting_cash == '100000'
            if stop_shock:
                # Independently required stop economics: every price is below
                # 70% of its owned peak. Exits fill next open, then cooldowns age.
                assert expected['2026-09-16'].state.pending
                assert not final.state.wealth_core['episodes']
                assert final.state.wealth_core['security_cooldowns']
                assert set(final.state.wealth_core['security_cooldowns'].values()) == {1}
                assert Decimal(final.parent_core_nav) < Decimal(held.parent_core_nav)
            for table in ('sentinel_execution_plans', 'sentinel_commands', 'sentinel_fills'):
                assert interrupted.execute('SELECT count(*) FROM ' + table).fetchone()[0] == 0
    finally:
        with psycopg.connect(pg.sync_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(clone)))


@pytest.mark.parametrize('failure', ['candidate', 'receipt'])
def test_recovery_crash_keeps_exact_candidate_without_retransition(conn, published, dated_source, monkeypatch, failure):
    advance(conn)
    refresh(conn, dated_source, monkeypatch)
    clock(monkeypatch, '2026-09-16')
    original = authority.append
    def interrupted(c, value):
        if failure == 'receipt':
            original(c, value)
            c.commit()
        raise OSError('crash after ' + failure)
    monkeypatch.setattr(authority, 'append', interrupted)
    with pytest.raises(OSError, match='crash'):
        recovery.advance_one(conn, through='2026-09-15', observation_id=OBS, starting_cash=100_000)
    checkpoint = checkpoints.read(conn)
    assert isinstance(checkpoint, checkpoints.ReconstructionCheckpoint)
    conn.rollback()
    monkeypatch.setattr(authority, 'append', original)
    monkeypatch.setattr(shadow, 'advance_state', lambda *a, **k: pytest.fail('transition repeated'))
    result = recovery.advance_one(conn, through='2026-09-15', observation_id=OBS, starting_cash=100_000)
    assert result.state.state_hash == checkpoint.state_sha256
    assert not result.appended
    assert isinstance(authority.latest(conn, OBS)[0], authority.ReconstructionReceipt)


def test_expired_genesis_candidate_recovers_without_reset_or_replay(conn, published, monkeypatch):
    first = initial.initialize(conn, observation_id=OBS, starting_cash=100_000)
    clock(monkeypatch, '2026-09-16')
    monkeypatch.setattr(shadow, 'advance_state', lambda *a, **k: pytest.fail('genesis replayed'))
    result = step(conn, '2026-09-16')
    assert result.state.to_dict() == first.state.to_dict()
    assert not result.appended
    assert isinstance(authority.latest(conn, OBS)[0], authority.ReconstructionReceipt)
    with pytest.raises(authority.Refused, match='NOT_PROSPECTIVE'):
        runtime._result(result, authority.latest(conn, OBS)[0])


def test_service_waits_for_exact_missing_input_preserving_identity(conn, published, monkeypatch):
    first = advance(conn)
    now = clock(monkeypatch, '2026-09-16')
    class Borrowed:
        def __getattr__(self, name):
            return getattr(conn, name)
        def close(self):
            pass
    monkeypatch.setattr(store, 'connect', lambda _: Borrowed())
    monkeypatch.setattr(inputs, '_prepare', lambda *a, **k: pytest.fail('current inputs backdated'))
    config = shadow_service.ShadowServiceConfig('fixture', OBS, Decimal('100000'),
        shadow_runtime.SHADOW_PUBLICATION_TIMING_POLICY, 300)
    with pytest.raises(shadow_service.ShadowServiceWaiting, match='MISSING_DATED_PUBLICATION:2026-09-15'):
        shadow_service.advance_once(config, now=now)
    assert checkpoints.read(conn) is None
    assert origin.read(conn).state_sha256 == first.state.state_hash
    assert shadow_service.service_health(config, now=now)['service_health'] == 'RECONSTRUCTION_PENDING'


def test_late_publication_cannot_be_backdated(conn, published, dated_source, monkeypatch):
    advance(conn)
    dated_source['publication_delay'] = timedelta(days=1)
    refresh(conn, dated_source, monkeypatch)
    clock(monkeypatch, '2026-09-17')
    with op.pinned(conn) as (pub, _):
        with pytest.raises(evidence.InputsUnavailable, match='DATED_PUBLICATION_REQUIRED:2026-09-15'):
            evidence.require_dated(conn, pub)
    with pytest.raises(evidence.InputsUnavailable, match='MISSING_DATED_PUBLICATION:2026-09-15'):
        step(conn, '2026-09-17')
    assert checkpoints.read(conn) is None


@pytest.mark.parametrize('defect', ['ambiguous', 'retired'])
def test_ambiguous_or_retired_history_is_not_guessed(conn, published, dated_source, monkeypatch, defect):
    from sentinel.feed.rolling_contract import digest
    advance(conn)
    binding = refresh(conn, dated_source, monkeypatch)
    if defect == 'ambiguous':
        job = op.enqueue(conn, strategy_sha256=digest(initial._context(OBS, 100_000)['strategy']),
                         dependencies_sha256=digest('independent second publication'))
        conn.commit()
        op.prepare(conn, job)
    else:
        conn.execute('SET LOCAL session_replication_role=replica')
        conn.execute('INSERT INTO sentinel_snapshot_retirements(candidate_id) VALUES(%s)', (binding['candidate_id'],))
        conn.commit()
    clock(monkeypatch, '2026-09-17')
    with pytest.raises(evidence.InputsUnavailable, match='AMBIGUOUS|RETIRED'):
        step(conn, '2026-09-17')
    assert checkpoints.read(conn) is None


def test_stale_retention_rule_is_refused_without_runtime_migration(conn):
    conn.execute("CREATE OR REPLACE FUNCTION sentinel_snapshot_pins(target UUID) RETURNS TEXT[] "
                 "LANGUAGE plpgsql AS $$ BEGIN RETURN '{}'; END $$")
    conn.commit()
    with pytest.raises(runtime_schema.FeedSchemaRefused, match='recovery pin'):
        runtime_schema.require_feed_schema(conn)


def test_unconsumed_snapshot_sql_guard_has_a_real_removal_falsifier(conn, published, dated_source, monkeypatch):
    from sentinel.execution import journal
    from sentinel.feed.retention_schema import DDL
    advance(conn)
    middle = refresh(conn, dated_source, monkeypatch)
    refresh(conn, dated_source, monkeypatch)
    def retire():
        with journal.writer_lock(conn), store.corpus_write_lock(conn):
            conn.execute('INSERT INTO sentinel_snapshot_retirements(candidate_id) VALUES(%s)',
                         (middle['candidate_id'],))
    with pytest.raises(psycopg.errors.RaiseException, match='UNCONSUMED_RECOVERY_INPUT'):
        retire()
    assert conn.execute('SELECT count(*) FROM sentinel_snapshot_retirements WHERE candidate_id=%s',
                        (middle['candidate_id'],)).fetchone()[0] == 0
    conn.rollback()
    # Negative control on disposable PostgreSQL: deleting only this pin makes
    # the exact same destructive INSERT succeed. Runtime catalog inspection
    # separately refuses this broken function; no guard is disabled in source.
    definition = next(value for value in DDL if value.startswith(
        'CREATE OR REPLACE FUNCTION sentinel_snapshot_pins('))
    guard = "reasons:=array_append(reasons,'UNCONSUMED_RECOVERY_INPUT');"
    assert definition.count(guard) == 1
    conn.execute(definition.replace(guard, 'NULL;'))
    conn.commit()
    retire()
    assert conn.execute('SELECT count(*) FROM sentinel_snapshot_retirements WHERE candidate_id=%s',
                        (middle['candidate_id'],)).fetchone()[0] == 1


@pytest.mark.parametrize('defect', ['future', 'naive', 'prospective'])
def test_reconstruction_clock_cannot_claim_timely_authority(monkeypatch, defect):
    clock(monkeypatch, '2026-09-16')
    value = evidence.timing(None, '2026-09-15')
    if defect == 'future':
        value['observed_at'] = '2026-09-16T13:29:59+00:00'
    elif defect == 'naive':
        value['observed_at'] = '2026-09-17T04:00:00'
    else:
        value['status'] = shadow.BEFORE_NEXT_OPEN
    with pytest.raises(origin.RollingColdStartRefused, match='TIMING_INVALID'):
        evidence.validate_timing(value, '2026-09-15')


__all__ = ['conn', 'pg', 'source', 'issuer_source', 'ready', 'operational_source']
