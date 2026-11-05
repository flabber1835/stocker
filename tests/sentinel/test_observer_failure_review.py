"""Native failures remain reviewable even when the projector sees only health."""
from datetime import datetime, timedelta, timezone
import inspect
import json

import pytest

from sentinel.panel import attempt_store, operational_schema, review, review_schema
from sentinel.operational_catalog import OperationalCatalogRefused
from tests.sentinel.test_dashboard_review import conn, pg, panel, clean  # noqa: F401
from tests.sentinel.test_observer_attempt_store import attempt, owner


@pytest.fixture(autouse=True)
def runtime(monkeypatch):
    monkeypatch.setenv('SENTINEL_GIT_COMMIT', '1'*40)
    monkeypatch.setenv('SENTINEL_RUNTIME_IMAGE_DIGEST', 'sha256:'+'2'*64)


def install_receipts(conn):
    for name in (operational_schema.RECEIPTS, operational_schema.OWNER):
        conn.execute(next(statement for statement in operational_schema.DDL
                          if statement.startswith('CREATE TABLE '+name+' ')))
    conn.commit()
    return owner(conn)


def publish(conn, owned, value, *, scope='SHADOW'):
    return attempt_store.publish_owned(conn, owner_id=owned, scope=scope,
        attempt=value, now=review.store.database_now(conn))


def test_fast_failure_and_healing_before_any_projector_pass_still_requires_review(conn):
    recorder = review.Recorder(component='verifier', instance='qualification-verifier')
    baseline = clean(recorder, conn)
    owned = install_receipts(conn)
    original = attempt(at=datetime.now(timezone.utc)-timedelta(seconds=2))
    assert publish(conn, owned, original)
    conn.commit()
    # No HTTP or operational collector ran while the financial check failed.
    healed = attempt(index=1, outcome='VERIFIED', at=datetime.now(timezone.utc)-timedelta(seconds=2))
    assert publish(conn, owned, healed)
    conn.commit()
    assert attempt_store.read_owned(conn, scope='SHADOW', now=review.store.database_now(conn))['latest']['outcome'] == 'VERIFIED'
    conn.rollback()
    first_healthy_snapshot = recorder.observe(panel(), conn.info.dsn)
    assert first_healthy_snapshot.status == 'REVIEW'
    assert first_healthy_snapshot.reviewed_head == baseline.head
    assert not first_healthy_snapshot.active and not first_healthy_snapshot.warnings
    native = [event for event in first_healthy_snapshot.events
              if event['details'].get('reason') == 'Verification attempt failed']
    assert len(native) == 1 and native[0]['kind'] == 'REVIEW'
    captured = native[0]['details']['attempt']
    assert captured == original
    assert captured['diagnostic']['code'] == 'READ_TIMEOUT'
    assert 'private-account' not in json.dumps(native)


def test_repeated_failed_attempt_is_one_native_event_with_original_clocks(conn):
    owned = install_receipts(conn)
    original = attempt(at=datetime.now(timezone.utc)-timedelta(seconds=2))
    assert publish(conn, owned, original)
    conn.commit()
    assert not publish(conn, owned, original)
    conn.commit()
    replacement = owner(conn)
    assert not publish(conn, replacement, original)
    conn.commit()
    key, now = review.store.scope(conn), review.store.database_now(conn)
    state = review.store.load_locked(conn, key, now)
    events = review.store.recent(conn, key)
    assert state['head'] == 1 and state['reviewed_head'] == 0
    assert not state['active'] and not state['warnings']
    assert len(state['view_sha256']) == 64
    assert len(events) == 1 and events[0]['details']['attempt'] == original
    # The native producer emits no acknowledgement token or current verdict.
    assert 'token' not in events[0]['details']
    conn.rollback()


@pytest.mark.parametrize('outcome', ['VERIFIED', 'SUPERSEDED'])
def test_superseded_or_successful_work_does_not_create_a_failure_note(conn, outcome):
    owned = install_receipts(conn)
    successful = attempt(outcome=outcome, at=datetime.now(timezone.utc)-timedelta(seconds=2))
    assert publish(conn, owned, successful)
    conn.commit()
    assert conn.execute(f'SELECT count(*) FROM {review_schema.EVENTS}').fetchone()[0] == 0


def test_partial_installed_review_schema_refuses_diagnostic_and_note_atomically(conn):
    owned = install_receipts(conn)
    conn.execute('DROP TABLE '+review_schema.EVENTS)
    conn.commit()
    with pytest.raises(OperationalCatalogRefused, match='PARTIAL'):
        publish(conn, owned, attempt(at=datetime.now(timezone.utc)-timedelta(seconds=2)))
    conn.rollback()
    assert conn.execute(f'SELECT count(*) FROM {operational_schema.RECEIPTS}').fetchone()[0] == 0


def test_failure_note_and_diagnostic_roll_back_together(conn, monkeypatch):
    owned = install_receipts(conn)
    append = review.store.append
    def interrupted(*args, **kwargs):
        append(*args, **kwargs)
        raise RuntimeError('synthetic interruption before commit')
    monkeypatch.setattr(review.store, 'append', interrupted)
    with pytest.raises(RuntimeError, match='before commit'):
        publish(conn, owned, attempt(at=datetime.now(timezone.utc)-timedelta(seconds=2)))
    conn.rollback()
    assert conn.execute(f'SELECT count(*) FROM {operational_schema.RECEIPTS}').fetchone()[0] == 0
    assert conn.execute(f'SELECT count(*) FROM {review_schema.EVENTS}').fetchone()[0] == 0


def test_removed_native_failure_publication_is_detected(conn, monkeypatch):
    source = inspect.getsource(attempt_store.publish_owned)
    guard = 'record_verification_failure_owned(conn, scope=scope, attempt=current)'
    assert source.count(guard) == 2
    namespace = {}
    exec(compile(source.replace(guard, 'False'), '<browser-sampled-failure-mutant>', 'exec'),
         vars(attempt_store), namespace)
    monkeypatch.setattr(attempt_store, 'publish_owned', namespace['publish_owned'])
    with pytest.raises(AssertionError):
        test_fast_failure_and_healing_before_any_projector_pass_still_requires_review(conn)
