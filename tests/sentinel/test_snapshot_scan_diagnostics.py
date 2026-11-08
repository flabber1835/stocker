"""Actual tiny content proofs keep optional diagnostics outside authority."""
from dataclasses import dataclass
from datetime import date
import hashlib
import inspect
import json
import textwrap
from types import SimpleNamespace

import pytest

from sentinel import supervisor_io
from sentinel.feed import publication, readiness_scope, rolling_store as store


CID = '00000000-0000-0000-0000-000000000001'
SID = 'a' * 64


@dataclass(frozen=True)
class Bar:
    session: date
    security_id: str = 'SYNTHETIC'
    ticker: str = 'SYNTHETIC'
    close_signal: int = 10
    close_unadjusted: int = 10
    open_unadjusted: int = 10
    volume: int = 10

    def model_dump(self, *, mode):
        return {**vars(self), 'session': self.session.isoformat()}


@dataclass(frozen=True)
class Benchmark:
    session: date

    def model_dump(self, *, mode):
        return {'session': self.session.isoformat()}


class Connection:
    closed = False
    info = SimpleNamespace(backend_pid=321, host='synthetic', port=5432,
                           dbname='synthetic', user='synthetic')

    def __init__(self):
        self.queries = []

    def execute(self, query, *args):
        self.queries.append(query)
        assert 'pg_locks' in query, 'diagnostic issued another identity query'
        return SimpleNamespace(fetchone=lambda: (True,))


@pytest.fixture
def proof(monkeypatch):
    days = (date(2026, 11, 5), date(2026, 11, 6))
    bars, benchmarks = [Bar(day) for day in days], [Benchmark(day) for day in days]
    hashes = [hashlib.sha256() for _ in range(3)]
    for row in bars:
        store._fold(hashes[0], row.model_dump(mode='json'))
        store._fold(hashes[1], (row.session.isoformat(), row.security_id))
    for row in benchmarks:
        store._fold(hashes[2], row.model_dump(mode='json'))
    manifest = SimpleNamespace(snapshot_id=SID, window=SimpleNamespace(sessions=days),
        bar_count=2, bars_sha256=hashes[0].hexdigest(), coverage_sha256=hashes[1].hexdigest(),
        benchmarks_sha256=hashes[2].hexdigest())
    calls, events = [], []
    conn = Connection()
    monkeypatch.setattr(store, 'manifest', lambda *_: manifest)
    monkeypatch.setattr(store, 'require_payload', lambda *_: None)

    def bar_rows(*_):
        calls.append('bars')
        yield from bars

    def benchmark_rows(*_):
        calls.append('benchmarks')
        yield from benchmarks

    def sink(message):
        events.append(json.loads(message))
        return True

    monkeypatch.setattr(store, '_bar_rows', bar_rows)
    monkeypatch.setattr(store, '_benchmark_rows', benchmark_rows)
    monkeypatch.setattr(supervisor_io, '_pipe_report', sink)
    monkeypatch.setattr(supervisor_io, 'report', lambda *_a, **_k:
                        pytest.fail('snapshot diagnostics entered fallback reporter'))
    return SimpleNamespace(conn=conn, manifest=manifest, calls=calls, events=events)


def test_real_content_proof_emits_one_matching_begin_end_without_identity_query(proof, monkeypatch):
    clock_calls = []

    def clock():
        result = 10 + .25 * len(clock_calls)
        clock_calls.append(result)
        return result

    monkeypatch.setattr(store, 'time', SimpleNamespace(monotonic=clock))
    result = store._verify_content_uncached(proof.conn, CID)
    assert result.manifest == proof.manifest and result.readiness is None
    assert proof.calls == ['bars', 'benchmarks'] and not proof.conn.queries
    begin, end = proof.events
    assert [(item['stage'], item['outcome']) for item in proof.events] == [
        ('SNAPSHOT_VERIFY_BEGIN', 'BEGIN'), ('SNAPSHOT_VERIFY_END', 'ACCEPTED')]
    for event in proof.events:
        assert event['component'] == 'feed' and event['error'] is None
        assert event['context']['candidate_id'] == CID
        assert event['context']['snapshot_sha256'] == SID
        assert event['context']['backend_pid'] == 321
        assert event['context']['started'] == 10
    assert end['context']['completed'] == 10.25
    assert end['context']['elapsed_seconds'] == .25
    assert clock_calls == [10, 10.25]


def test_proof_failure_retains_original_exception_without_private_message(proof, monkeypatch):
    original = RuntimeError('private-canary-database-or-input-value')

    def failed(*_):
        raise original

    monkeypatch.setattr(store, '_bar_rows', failed)
    with pytest.raises(RuntimeError) as caught:
        store._verify_content_uncached(proof.conn, CID)
    assert caught.value is original
    assert [item['stage'] for item in proof.events] == [
        'SNAPSHOT_VERIFY_BEGIN', 'SNAPSHOT_VERIFY_FAILED']
    assert proof.events[-1]['error']['exception_type'] == 'RuntimeError'
    assert 'private-canary' not in json.dumps(proof.events)


@pytest.mark.parametrize('mode', ['negative_delivery', 'raising_reporter'])
def test_broken_sink_cannot_change_actual_content_proof(proof, monkeypatch, mode):
    def broken(*_a, **_k):
        if mode == 'raising_reporter':
            raise RuntimeError('synthetic reporter unavailable')
        return False

    monkeypatch.setattr(supervisor_io, 'report_event', broken)
    result = store._verify_content_uncached(proof.conn, CID)
    assert result.manifest == proof.manifest and result.readiness is None
    assert proof.calls == ['bars', 'benchmarks'] and not proof.conn.queries


def test_broken_sink_cannot_replace_existing_proof_failure(proof, monkeypatch):
    original = ValueError('original content failure')

    def failed(*_):
        raise original

    def unavailable(*_a, **_k):
        raise RuntimeError('reporter failure must not escape')

    monkeypatch.setattr(store, '_bar_rows', failed)
    monkeypatch.setattr(supervisor_io, 'report_event', unavailable)
    with pytest.raises(ValueError) as caught:
        store._verify_content_uncached(proof.conn, CID)
    assert caught.value is original


def test_unavailable_optional_backend_identity_does_not_read_another_source(proof):
    class UnavailableIdentity:
        @property
        def info(self):
            raise RuntimeError('optional port metadata unavailable')

        def execute(self, *_a, **_k):
            pytest.fail('diagnostic replaced unavailable metadata with an identity query')

    result = store._verify_content_uncached(UnavailableIdentity(), CID)
    assert result.manifest == proof.manifest
    assert len(proof.events) == 2
    assert all('backend_pid' not in event['context'] for event in proof.events)


def test_pin_reuse_does_not_start_another_scan_or_diagnostic(proof, monkeypatch):
    pub = SimpleNamespace(evidence={'rolling_snapshot': {'candidate_id': CID, 'snapshot_id': SID}})
    pub.to_dict = lambda: {'version': 1, 'evidence': pub.evidence}
    monkeypatch.setattr(publication, '_validate_publication', lambda *_a, **_k: None)
    with readiness_scope.pinned(proof.conn, pub):
        assert store.verify_content(proof.conn, CID) == proof.manifest
        assert store.verify_content(proof.conn, CID) == proof.manifest
        assert store.readiness_facts(proof.conn, CID).counts == (1, 1)
    assert proof.calls == ['bars', 'benchmarks']
    assert [item['stage'] for item in proof.events] == [
        'SNAPSHOT_VERIFY_BEGIN', 'SNAPSHOT_VERIFY_END']


@pytest.mark.parametrize('field', ['candidate_id', 'snapshot_sha256'])
def test_invalid_diagnostic_fingerprint_cannot_change_content_proof(proof, field):
    candidate = CID
    if field == 'candidate_id':
        candidate = 'private-canary-not-a-data-uuid'
    else:
        proof.manifest.snapshot_id = 'private-canary-not-a-digest'
    result = store._verify_content_uncached(proof.conn, candidate)
    assert result.manifest == proof.manifest
    assert proof.calls == ['bars', 'benchmarks'] and not proof.events


def test_removing_the_optional_sink_guard_is_detected(proof, monkeypatch):
    source = textwrap.dedent(inspect.getsource(store._content_diagnostic))
    guarded = '        except Exception:\n            pass  # Never replace the original proof result or exception.'
    assert source.count(guarded) == 1
    source = source.replace(guarded, '        except Exception:\n            raise')
    namespace = vars(store).copy()
    exec(compile(source, '<removed-diagnostic-sink-guard>', 'exec'), namespace)
    monkeypatch.setattr(store, '_content_diagnostic', namespace['_content_diagnostic'])
    with pytest.raises(RuntimeError, match='synthetic reporter unavailable'):
        test_broken_sink_cannot_change_actual_content_proof(proof, monkeypatch, 'raising_reporter')
