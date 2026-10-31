"""Only a matching, live signed attestation proof bounds a missing display verdict."""
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import inspect
from types import SimpleNamespace

import pytest

from sentinel.feed import readers, rolling_go_inputs
from sentinel.panel import model, observer_codec, postclose_feed_wait, shadow_source_wait, sources


NOW = datetime(2026, 10, 30, 21, tzinfo=timezone.utc)
DEADLINE = NOW+timedelta(minutes=30)
SESSION = '2026-10-30'
PUBLICATION = 11


def pending(**changes):
    values = dict(frontier=SESSION, sessions_behind=0, ready=None,
        checks_passed=0, checks_total=0, checked_at=None,
        as_of=NOW-timedelta(minutes=5), publication_version=PUBLICATION)
    values.update(changes)
    return model.feed_row(**values)


def proof():
    return SimpleNamespace(quiet_eligible=True, phase='AWAITING_ATTESTATION',
        decision_session=SESSION, previous_session='2026-10-29',
        publication_version=PUBLICATION, previous_publication_version=10,
        publisher_deadline=DEADLINE+timedelta(minutes=30), worker_deadline=DEADLINE,
        observed_at=NOW, deadline=DEADLINE-timedelta(microseconds=1))


def facts():
    financial = shadow_source_wait.preparation_rows(proof(), include_paper=False)
    worker = model.Row('shadow_worker', 'Strategy worker', 'RUNNING', model.OK,
        as_of=NOW, required_current=True, valid_until=NOW+timedelta(seconds=45))
    return financial, worker


def project(row=None, financial=None, worker=None, *, now=NOW):
    default_financial, default_worker = facts()
    out, _ = postclose_feed_wait.project_progress([row or pending()], [],
        default_financial if financial is None else financial,
        default_worker if worker is None else worker, now=now)
    return out[0]


def test_matching_published_pending_verdict_has_only_the_original_finite_attestation_wait():
    original = pending()
    assert original.feed_readiness == 'AWAITING_VERDICT'
    assert original.effective_status(NOW) == model.FAIL
    result = project(original)
    assert result.status == result.effective_status(NOW) == model.WARN
    assert result.as_of == original.as_of
    assert result.feed_readiness == 'AWAITING_VERDICT'
    assert result.source_publication_version == PUBLICATION
    assert result.source_session == SESSION
    assert result.valid_until == NOW+timedelta(seconds=45)
    assert result.recovery.phase == 'SHADOW_ATTESTATION'
    assert result.recovery.deadline == result.valid_until
    assert 'No readiness verdict has been claimed' in result.detail
    assert result.effective_status(result.valid_until+timedelta(microseconds=1)) == model.FAIL


def test_attestation_fields_survive_the_existing_signed_observer_shape():
    rows, _ = facts()
    encoded = observer_codec.pack(rows, [], observed_at=NOW)
    decoded = [observer_codec.row_from_observation(value) for value in encoded['rows']]
    assert all(row.source_publication_version == PUBLICATION and row.source_session == SESSION
               and row.feed_readiness is None for row in decoded)


@pytest.mark.parametrize('fault', ['wrong_feed_publication', 'wrong_proof_publication',
    'wrong_feed_session', 'wrong_proof_session', 'untyped_publication', 'missing_proof',
    'expired_proof', 'dead_worker', 'stale_worker', 'future_worker', 'unrequired_proof',
    'wrong_phase', 'duplicate_proof', 'measured_false', 'unknown', 'error',
    'missing_publication', 'stale_feed', 'future_feed'])
def test_foreign_negative_expired_or_unproved_handoffs_are_not_promoted(fault):
    original = pending()
    financial, worker = facts()
    if fault == 'wrong_feed_publication': original = replace(original, source_publication_version=10)
    elif fault == 'wrong_proof_publication': financial[0] = replace(financial[0], source_publication_version=12)
    elif fault == 'wrong_feed_session': original = replace(original, source_session='2026-10-29')
    elif fault == 'wrong_proof_session': financial[0] = replace(financial[0], source_session='2026-10-29')
    elif fault == 'untyped_publication': financial[0] = replace(financial[0], source_publication_version=True)
    elif fault == 'missing_proof': financial = []
    elif fault == 'expired_proof':
        financial[0] = replace(financial[0], valid_until=NOW-timedelta(seconds=1),
            recovery=replace(financial[0].recovery, deadline=NOW-timedelta(seconds=1)))
    elif fault == 'dead_worker': worker = replace(worker, status=model.FAIL)
    elif fault == 'stale_worker': worker = replace(worker, valid_until=NOW-timedelta(seconds=1))
    elif fault == 'future_worker': worker = replace(worker, as_of=NOW+timedelta(minutes=1))
    elif fault == 'unrequired_proof': financial[0] = replace(financial[0], required_current=False)
    elif fault == 'wrong_phase': financial[0] = replace(financial[0],
        recovery=replace(financial[0].recovery, phase='SOURCE_PUBLICATION'))
    elif fault == 'duplicate_proof': financial.append(financial[0])
    elif fault == 'measured_false': original = pending(ready=False, checks_passed=13, checks_total=14, checked_at=NOW)
    elif fault == 'unknown': original = replace(original, status=model.UNKNOWN)
    elif fault == 'error': original = pending(error='unrelated immutable receipt failure')
    elif fault == 'missing_publication': original = pending(publication_version=None)
    elif fault == 'stale_feed': original = replace(original, valid_until=NOW-timedelta(seconds=1))
    elif fault == 'future_feed': original = replace(original, as_of=NOW+timedelta(minutes=1))
    result = project(original, financial, worker)
    assert result is original, 'unproved feed handoff earned a bounded wait'
    assert result.effective_status(NOW) in {model.FAIL, model.UNKNOWN}


def test_refreshes_do_not_extend_the_worker_or_attestation_deadline():
    original = pending()
    financial, worker = facts()
    first = project(original, financial, worker)
    again = project(original, financial, worker, now=NOW+timedelta(seconds=30))
    assert first.valid_until == again.valid_until == worker.valid_until
    assert project(original, financial, worker, now=worker.valid_until) is original


def test_publication_binding_has_an_executed_guard_removal_falsifier(monkeypatch):
    source = inspect.getsource(postclose_feed_wait.project_progress)
    guard = 'and row.source_publication_version == source[0]'
    assert source.count(guard) == 1
    namespace = dict(vars(postclose_feed_wait))
    exec(compile(source.replace(guard, ''), '<missing-attestation-publication-binding>', 'exec'), namespace)
    monkeypatch.setattr(postclose_feed_wait, 'project_progress', namespace['project_progress'])
    with pytest.raises(AssertionError, match='unproved feed handoff'):
        test_foreign_negative_expired_or_unproved_handoffs_are_not_promoted('wrong_feed_publication')


def legacy_financial():
    rows, _ = facts()
    return [replace(row, source_publication_version=None, source_session=None) for row in rows]


def test_exact_old_authenticated_native_encoding_supports_the_same_bound_without_new_observation():
    financial = legacy_financial()
    identity = shadow_source_wait.attestation_source(financial[0], now=NOW)
    assert identity == (PUBLICATION, SESSION)
    result = project(financial=financial)
    assert result.effective_status(NOW) == model.WARN
    assert result.recovery.phase == 'SHADOW_ATTESTATION'
    assert result.as_of == pending().as_of
    assert result.valid_until == facts()[1].valid_until


@pytest.mark.parametrize('fault', ['different_value', 'different_date', 'foreign_publication',
    'unknown_prefix', 'missing_suffix', 'altered_clock', 'naive_clock', 'foreign_previous',
    'partial_publication', 'partial_session', 'wrong_producer_row', 'negative_producer',
    'generic_running', 'freeform_error'])
def test_unknown_or_mixed_legacy_shapes_cannot_promote_a_pending_feed(fault):
    financial = legacy_financial()
    row = financial[0]
    if fault == 'different_value': row = replace(row, value='WAITING FOR 2026-10-29 STRATEGY ATTESTATION')
    elif fault == 'different_date': row = replace(row, detail=row.detail.replace('Closing data for '+SESSION, 'Closing data for 2026-10-29'))
    elif fault == 'foreign_publication': row = replace(row, detail=row.detail.replace('published as version 11;', 'published as version 12;'))
    elif fault == 'unknown_prefix': row = replace(row, detail=row.detail.replace('Closing data for', 'An error described data for'))
    elif fault == 'missing_suffix': row = replace(row, detail=row.detail.split('Original publisher')[0])
    elif fault == 'altered_clock': row = replace(row, detail=row.detail.replace(proof().worker_deadline.isoformat(), (DEADLINE+timedelta(seconds=1)).isoformat()))
    elif fault == 'naive_clock': row = replace(row, detail=row.detail.replace(DEADLINE.isoformat(), DEADLINE.replace(tzinfo=None).isoformat()))
    elif fault == 'foreign_previous': row = replace(row, detail=row.detail.replace('Last verified strategy session: 2026-10-29', 'Last verified strategy session: 2026-10-28'))
    elif fault == 'partial_publication': row = replace(row, source_publication_version=PUBLICATION)
    elif fault == 'partial_session': row = replace(row, source_session=SESSION)
    elif fault == 'wrong_producer_row': row = replace(row, key='other')
    elif fault == 'negative_producer': row = replace(row, status=model.FAIL)
    elif fault == 'generic_running': row = replace(row, value='RUNNING')
    elif fault == 'freeform_error': row = replace(row, detail='error: '+row.detail)
    financial[0] = row
    original = pending()
    assert project(original, financial=financial) is original, 'unknown legacy shape earned wait'


@pytest.mark.parametrize('matching', [True, False])
def test_optional_reader_publication_uses_the_same_pin_and_default_remains_a_pair(monkeypatch, matching):
    connection, calls = object(), []
    publication = SimpleNamespace(version=PUBLICATION, window_end=SESSION)
    snapshot = object()
    monkeypatch.setattr(readers, 'current', lambda conn: calls.append(('current',conn)) or publication)
    @contextmanager
    def pin(conn, *, commit):
        calls.append(('pin',conn,commit))
        yield publication
    monkeypatch.setattr(readers, 'pinned', pin)
    monkeypatch.setattr(readers.legacy_readiness, 'latest_snapshot',
        lambda conn: calls.append(('snapshot',conn)) or snapshot)
    monkeypatch.setattr(readers, 'frontier',
        lambda conn,pub: calls.append(('frontier',conn,pub)) or pub.window_end)
    monkeypatch.setattr(readers, 'snapshot_matches',
        lambda pub,snap: calls.append(('binding',pub,snap)) or matching)
    def forbidden(*args, **kwargs):
        pytest.fail('display metadata triggered another readiness assessment')
    monkeypatch.setattr(readers, 'readiness', forbidden)
    monkeypatch.setattr(rolling_go_inputs, 'assessment', forbidden)
    expected = snapshot if matching else None
    assert readers.status_snapshot(connection) == (SESSION, expected)
    first_calls = list(calls)
    calls.clear()
    assert readers.status_snapshot(connection, include_publication=True) == (SESSION, expected, PUBLICATION)
    assert calls == first_calls and [call[0] for call in calls] == [
        'current','pin','snapshot','frontier','binding']


def test_reader_without_a_publication_keeps_legacy_pair_and_has_no_claimed_version(monkeypatch):
    monkeypatch.setattr(readers, 'current', lambda conn: None)
    monkeypatch.setattr(readers.store, 'latest_visible_session', lambda conn: SESSION)
    monkeypatch.setattr(readers.legacy_readiness, 'latest_snapshot', lambda conn: None)
    assert readers.status_snapshot(object()) == (SESSION, None)
    assert readers.status_snapshot(object(), include_publication=True) == (SESSION, None, None)


def test_feed_composition_preserves_the_pinned_publication_for_a_missing_verdict(monkeypatch):
    from sentinel.feed import calendar, store

    class Connection:
        def close(self): pass
    monkeypatch.setenv('SENTINEL_REVIEWED_DEPLOYMENT_MODE', 'shadow')
    monkeypatch.setattr(store, 'connect', lambda *_: Connection())
    monkeypatch.setattr(sources, '_set_statement_timeout', lambda *_: None)
    monkeypatch.setattr(sources, '_operational_acquisition', lambda *_: [dict(
        kind='OPERATIONAL SNAPSHOT',status='success',updated_at=NOW-timedelta(minutes=5),
        current_chunk='PUBLISHED · publication 11', rows_written=100)])
    monkeypatch.setattr(sources, '_feed_status_snapshot', lambda *_: (SESSION,None,PUBLICATION))
    monkeypatch.setattr(calendar, 'freshness', lambda *_: SimpleNamespace(sessions_behind=0,ahead=False))
    rows, errors = sources._feed_rows('postgresql://fixture@isolated.invalid/fixture', now=NOW)
    feed = next(row for row in rows if row.key == 'feed')
    assert not errors and feed.feed_readiness == 'AWAITING_VERDICT'
    assert feed.source_publication_version == PUBLICATION and feed.source_session == SESSION
    assert feed.effective_status(NOW) == model.FAIL
    assert project(feed).effective_status(NOW) == model.WARN
