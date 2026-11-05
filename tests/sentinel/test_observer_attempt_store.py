"""Failed-attempt causes survive result replacement, restart and clock guards."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import inspect
from threading import Event
from types import SimpleNamespace
import uuid

import psycopg
from psycopg.types.json import Jsonb
import pytest

from sentinel.panel import attempt_store as store, observer_failure, operational_schema
from sentinel.panel import read_projection, verification_service as verifier
from tests.support.postgres import _EphemeralPostgres

NOW = datetime(2031, 1, 1, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv('SENTINEL_PUBLICATION_RECEIPT_KEY', 'private-qualification-'+'x'*40)
    monkeypatch.setenv('SENTINEL_GIT_COMMIT', '1'*40)
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST', 'sha256:'+'2'*64)


@pytest.fixture(scope='module')
def pg():
    cluster = _EphemeralPostgres()
    cluster.start()
    try:
        yield cluster
    finally:
        cluster.stop()


@pytest.fixture
def conn(pg):
    connection = psycopg.connect(pg.sync_dsn)
    suffix = uuid.uuid4().hex
    name = 'diagnostic_'+suffix
    connection.execute('CREATE SCHEMA '+name)
    connection.execute('SET search_path TO '+name+',public')
    connection.execute(next(sql for sql in operational_schema.DDL
                            if sql.startswith('CREATE TABLE '+operational_schema.RECEIPTS+' ')))
    connection.execute(next(sql for sql in operational_schema.DDL
                            if sql.startswith('CREATE TABLE '+operational_schema.OWNER+' ')))
    connection.execute('CREATE TABLE sentinel_account_binding (id INTEGER PRIMARY KEY,'
        'deployment_id TEXT,broker TEXT,broker_account_id TEXT,takeover_epoch TEXT,ownership_state TEXT)')
    connection.execute("INSERT INTO sentinel_account_binding VALUES (1,'private-deployment','alpaca',"
                       "'private-account','private-epoch','SENTINEL_OWNED')")
    connection.commit()
    try:
        yield connection
    finally:
        connection.rollback()
        connection.execute('DROP SCHEMA '+name+' CASCADE')
        connection.commit()
        connection.close()


def owner(conn):
    value = uuid.uuid4()
    conn.execute(f'INSERT INTO {operational_schema.OWNER} VALUES '
        "(1,%s,clock_timestamp()+INTERVAL '610 seconds') ON CONFLICT(id) DO UPDATE "
        'SET owner_id=EXCLUDED.owner_id,expires_at=EXCLUDED.expires_at', (value,))
    conn.commit()
    return value


def attempt(*, index=0, code='READ_TIMEOUT', outcome='FAILED', at=NOW):
    diagnostic = observer_failure.failure(code, 'SUPERSESSION' if code in {
        'CLOCK_REGRESSION', 'SUPERSESSION_EXHAUSTED'} else 'OBSERVATION') if outcome == 'FAILED' else None
    return observer_failure.Attempt.model_validate(dict(
        schema=observer_failure.ATTEMPT_SCHEMA, attempt_id=f'{index:032x}', subject_sha256='b'*64,
        outcome=outcome, admitted_at=at, deadline=at+timedelta(seconds=600),
        work_started_at=at, work_deadline=at+timedelta(seconds=300),
        completed_at=at+timedelta(seconds=1), diagnostic=diagnostic,
        latched_failure=diagnostic)).model_dump(mode='json', by_alias=True)


def publish(conn, owned, value, *, now=NOW+timedelta(seconds=2), scope='SHADOW'):
    return store.publish_owned(conn, owner_id=owned, scope=scope, attempt=value, now=now)


def read(conn, *, now=NOW+timedelta(seconds=2), scope='SHADOW'):
    return store.read_owned(conn, scope=scope, now=now)


def test_real_postgres_history_survives_success_and_consumer_restart_without_authority(conn):
    owned = owner(conn)
    failed = attempt()
    assert publish(conn, owned, failed)
    conn.commit()
    first = read(conn)
    successful = attempt(index=1, outcome='VERIFIED', at=NOW+timedelta(seconds=30))
    assert publish(conn, owned, successful, now=NOW+timedelta(seconds=31))
    conn.commit()
    # A replacement verifier owner reuses history, never an old worker or proof.
    replacement = owner(conn)
    assert not publish(conn, replacement, successful, now=NOW+timedelta(seconds=32))
    conn.rollback()
    retained = read(conn, now=NOW+timedelta(days=2))
    assert retained['latest']['outcome'] == 'VERIFIED' and len(retained['failures']) == 1
    assert retained['failures'][0] == first['failures'][0]
    assert retained['failures'][0]['first']['diagnostic']['code'] == 'READ_TIMEOUT'
    assert retained['observation_fresh'] is False and retained['financial_authority'] is False
    assert datetime.fromisoformat(retained['recorded_at']) == NOW+timedelta(seconds=31)
    assert conn.execute(f'SELECT scope FROM {operational_schema.RECEIPTS}').fetchall() == [('DIAGNOSTIC:SHADOW',)]
    assert 'private-account' not in json.dumps(retained) and 'private-deployment' not in json.dumps(retained)
    with pytest.raises(ValueError):
        read_projection.decode(retained, 'a'*64, current_subject='b'*64, scope='SHADOW', now=NOW)


def test_first_cause_and_original_clocks_survive_a_later_parent_clock_failure(conn):
    owned = owner(conn)
    original = attempt()
    publish(conn, owned, original)
    conn.commit()
    changed = deepcopy(original)
    failure = observer_failure.failure('CLOCK_REGRESSION', 'SUPERSESSION').model_dump(mode='json', by_alias=True)
    changed.update(diagnostic=failure, latched_failure=failure)
    assert publish(conn, owned, changed, now=NOW+timedelta(seconds=3))
    conn.commit()
    history = read(conn, now=NOW+timedelta(seconds=3))
    assert len(history['failures']) == 1
    summary = history['failures'][0]
    assert summary['first']['diagnostic']['code'] == 'READ_TIMEOUT'
    assert summary['latest']['diagnostic']['code'] == 'CLOCK_REGRESSION'
    assert summary['first']['admitted_at'] == summary['latest']['admitted_at']
    assert summary['first']['deadline'] == summary['latest']['deadline']


def test_retention_keeps_exactly_last_16_unique_failed_attempts(conn):
    owned = owner(conn)
    for index in range(20):
        publish(conn, owned, attempt(index=index), now=NOW+timedelta(seconds=index+2))
        conn.commit()
    history = read(conn, now=NOW+timedelta(seconds=22))
    assert [item['first']['attempt_id'] for item in history['failures']] == [f'{i:032x}' for i in range(4, 20)]
    assert len(json.dumps(history).encode()) < store.MAX_BYTES


@pytest.mark.parametrize('fault', ['signature', 'scope', 'context', 'extra', 'oversized', 'metadata'])
def test_tampered_or_foreign_history_is_refused_and_not_overwritten(conn, fault):
    owned = owner(conn)
    publish(conn, owned, attempt())
    conn.commit()
    row = conn.execute(f'SELECT envelope,signature FROM {operational_schema.RECEIPTS}').fetchone()
    value, signed = deepcopy(row[0]), row[1]
    if fault == 'signature': signed = 'f'*64
    elif fault == 'scope': value['scope'] = 'DIAGNOSTIC:PAPER'
    elif fault == 'context': value['context_sha256'] = 'f'*64
    elif fault == 'extra': value['private_data'] = 'synthetic-private-value'
    elif fault == 'oversized': value['private_data'] = 'x'*store.MAX_BYTES
    if fault not in {'signature', 'oversized'}:
        signed = store.review_store.signature(value, purpose=store.PURPOSE)
    conn.execute(f'UPDATE {operational_schema.RECEIPTS} SET envelope=%s,signature=%s', (Jsonb(value), signed))
    if fault == 'metadata':
        conn.execute(f'UPDATE {operational_schema.RECEIPTS} SET observed_at=observed_at+INTERVAL \'1 second\'')
    conn.commit()
    before = conn.execute(f'SELECT envelope,signature FROM {operational_schema.RECEIPTS}').fetchone()
    with pytest.raises(store.DiagnosticsRefused):
        publish(conn, owned, attempt(index=1), now=NOW+timedelta(seconds=3))
    conn.rollback()
    assert conn.execute(f'SELECT envelope,signature FROM {operational_schema.RECEIPTS}').fetchone() == before


@pytest.mark.parametrize('replaced', [False, True])
def test_expired_or_replaced_owner_cannot_publish_diagnostics(conn, replaced):
    owned = owner(conn)
    if replaced:
        owner(conn)
    else:
        conn.execute(f'UPDATE {operational_schema.OWNER} SET expires_at=clock_timestamp()-INTERVAL \'1 second\'')
        conn.commit()
    with pytest.raises(store.DiagnosticsRefused, match='OWNER_LOST'):
        publish(conn, owned, attempt())
    conn.rollback()
    assert conn.execute(f'SELECT count(*) FROM {operational_schema.RECEIPTS}').fetchone()[0] == 0


def test_changed_attempt_identity_cannot_reuse_an_existing_failed_summary(conn):
    owned = owner(conn)
    publish(conn, owned, attempt())
    conn.commit()
    changed = attempt()
    changed['subject_sha256'] = 'f'*64
    with pytest.raises(ValueError, match='contradictory'):
        publish(conn, owned, changed, now=NOW+timedelta(seconds=3))
    conn.rollback()


def test_owner_expiring_during_history_validation_cannot_write(conn, monkeypatch):
    owned = owner(conn)
    original = store.context
    def expires(connection):
        value = original(connection)
        connection.execute(f'UPDATE {operational_schema.OWNER} '
            "SET expires_at=clock_timestamp()-INTERVAL '1 second'")
        return value
    monkeypatch.setattr(store, 'context', expires)
    with pytest.raises(store.DiagnosticsRefused, match='OWNER_LOST_AT_WRITE'):
        publish(conn, owned, attempt())
    conn.rollback()
    assert conn.execute(f'SELECT count(*) FROM {operational_schema.RECEIPTS}').fetchone()[0] == 0


def test_failure_without_financial_receipt_is_durable_in_existing_refresh_loop(conn, monkeypatch):
    owned = owner(conn)
    state = attempt(code='SUPERSESSION_EXHAUSTED')
    reader = SimpleNamespace(read=lambda *args, **kwargs: None, attempt_state=lambda: state)
    monkeypatch.setattr(verifier, 'snapshot', lambda *args, **kwargs: None)
    monkeypatch.setattr(verifier, '_require_iteration_time', lambda *_: None)
    # The loop uses its real wall clock; original attempt time is diagnostic only.
    class Time:
        @staticmethod
        def now(_zone): return NOW+timedelta(seconds=2)
    monkeypatch.setattr(verifier, 'datetime', Time)
    previous = {}
    verifier._refresh_readers(conn, {'SHADOW': reader}, 'private-fixture', owned, previous, Event(), 100)
    assert read(conn)['latest']['diagnostic']['code'] == 'SUPERSESSION_EXHAUSTED'
    before = conn.execute(f'SELECT observed_at,xmin::text FROM {operational_schema.RECEIPTS}').fetchone()
    conn.rollback()
    verifier._refresh_readers(conn, {'SHADOW': reader}, 'private-fixture', owned, previous, Event(), 100)
    assert conn.execute(f'SELECT observed_at,xmin::text FROM {operational_schema.RECEIPTS}').fetchone() == before


def test_financial_and_diagnostic_updates_commit_atomically_or_not_at_all(conn, monkeypatch):
    owned = owner(conn)
    reader = SimpleNamespace(read=lambda *args, **kwargs: None, attempt_state=lambda: attempt())
    monkeypatch.setattr(verifier, 'snapshot', lambda *args, **kwargs: ({'subject_sha256': 'b'*64}, 'c'*64))
    monkeypatch.setattr(verifier, '_require_iteration_time', lambda *_: None)
    monkeypatch.setattr(read_projection, 'subject', lambda *args: 'b'*64)
    def financial(connection, **kwargs):
        connection.execute(f'INSERT INTO {operational_schema.RECEIPTS} VALUES '
            '(%s,%s,%s,%s,%s,%s)', ('SHADOW', 'b'*64, NOW, NOW+timedelta(seconds=600), Jsonb({}), 'c'*64))
    monkeypatch.setattr(read_projection, 'publish', financial)
    original = store.publish_owned
    def failed_after_write(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError('synthetic precommit interruption')
    monkeypatch.setattr(store, 'publish_owned', failed_after_write)
    with pytest.raises(RuntimeError, match='precommit'):
        verifier._refresh_readers(conn, {'SHADOW': reader}, 'private-fixture', owned, {}, Event(), 100)
    conn.rollback()
    assert conn.execute(f'SELECT count(*) FROM {operational_schema.RECEIPTS}').fetchone()[0] == 0


def test_removed_signature_guard_is_detected(conn, monkeypatch):
    monkeypatch.setattr(store.hmac, 'compare_digest', lambda *args: True)
    with pytest.raises(pytest.fail.Exception):
        test_tampered_or_foreign_history_is_refused_and_not_overwritten(conn, 'signature')


def test_removed_write_time_owner_guard_is_detected(conn, monkeypatch):
    source = inspect.getsource(store.publish_owned)
    guard = 'AND expires_at>clock_timestamp()'
    assert source.count(guard) == 3
    namespace = {}
    exec(compile(source.replace(guard, 'AND true'), '<expired-diagnostic-writer>', 'exec'),
         vars(store), namespace)
    monkeypatch.setattr(store, 'publish_owned', namespace['publish_owned'])
    with pytest.raises(pytest.fail.Exception):
        test_owner_expiring_during_history_validation_cannot_write(conn, monkeypatch)
