"""Real competing sessions must defer work without poisoning the supervisor."""
from contextlib import contextmanager
from decimal import Decimal

import pytest

from sentinel import automation_runtime, shadow_worker, shadow_service, shadow_recovery, shadow_runtime
from sentinel.automation.model import (
    NonRetryableCallbackRefused, TransientInfrastructureFailure,
)
from sentinel.execution import journal
from sentinel.feed import publication, rolling_store, store
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401
from tests.sentinel.test_rolling_go_inputs import issuer_source, published, ready  # noqa: F401
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401


@pytest.mark.parametrize('state_field', ['initial_state', 'state'])
def test_actual_rolling_status_preserves_native_store_read_timeout(
        conn, published, monkeypatch, state_field):
    import psycopg
    from sentinel import shadow_observation
    from tests.sentinel.test_rolling_runtime import advance
    from tests.sentinel.test_rolling_initialization import OBS
    expected = advance(conn)
    before = conn.execute('SELECT cursor_name,session,state FROM sentinel_processed_sessions '
                          'ORDER BY cursor_name').fetchall()
    conn.rollback()
    original = shadow_observation.PostgresShadowObservationStore._streamed_row
    seen = []
    def unavailable(self, name, field):
        if field == state_field:
            seen.append(name)
            self.conn.execute("SET LOCAL statement_timeout='20ms'")
            self.conn.execute('SELECT pg_sleep(1)')
        return original(self, name, field)
    with monkeypatch.context() as interrupted:
        interrupted.setattr(shadow_observation.PostgresShadowObservationStore,
                            '_streamed_row', unavailable)
        with pytest.raises(psycopg.errors.QueryCanceled) as caught:
            shadow_runtime.verified_shadow_status(conn, observation_id=OBS, starting_cash=100000)
    assert seen and caught.value.sqlstate == '57014'
    assert isinstance(automation_runtime.classify_dependency_failure(caught.value),
                      TransientInfrastructureFailure)
    assert conn.execute('SELECT cursor_name,session,state FROM sentinel_processed_sessions '
                        'ORDER BY cursor_name').fetchall() == before
    conn.rollback()
    recovered = shadow_runtime.verified_shadow_status(conn, observation_id=OBS, starting_cash=100000)
    assert recovered.verification == shadow_observation.VERIFIED
    assert recovered.record_sha256 == expected.record_sha256
    for table in ('sentinel_commands', 'sentinel_fills', 'sentinel_execution_plans'):
        assert conn.execute('SELECT count(*) FROM ' + table).fetchone()[0] == 0


@contextmanager
def _contended(conn, boundary):
    """Hold the opposite advisory mode on a second real PostgreSQL session."""
    import psycopg
    key = journal.WRITER_LOCK_KEY if boundary == 'behavioral_writer' else publication.CORPUS_LOCK_KEY
    mode = '_shared' if boundary == 'corpus_writer' else ''
    conn.rollback()
    with psycopg.connect(conn.info.dsn) as other:
        other.execute(f'SELECT pg_advisory_lock{mode}(%s)', (key,))
        yield


def _attempt(conn, boundary):
    if boundary == 'snapshot_reader':
        rolling_store._pin_reader(conn)
    elif boundary == 'corpus_reader':
        with publication._core.pinned(conn, commit=False):
            pass
    elif boundary == 'atomic_publisher':
        publication._publish_atomic(conn)
    else:
        lock = journal.writer_lock if boundary == 'behavioral_writer' else store.corpus_write_lock
        with lock(conn):
            pass


@pytest.mark.parametrize('boundary', [
    'corpus_reader', 'snapshot_reader', 'corpus_writer', 'atomic_publisher', 'behavioral_writer'])
def test_actual_lock_contention_is_availability_at_both_worker_boundaries(conn, monkeypatch, boundary):
    monkeypatch.setattr(shadow_worker.ShadowServiceConfig, 'from_env', lambda: object())
    def attempt(_):
        try:
            _attempt(conn, boundary)
        finally:
            conn.rollback()
    monkeypatch.setattr(shadow_worker, 'advance_once', attempt)
    with _contended(conn, boundary):
        with pytest.raises(RuntimeError) as caught:
            _attempt(conn, boundary)
        conn.rollback()
        assert isinstance(automation_runtime.classify_dependency_failure(caught.value),
                          TransientInfrastructureFailure)
        assert shadow_worker.main() == shadow_worker.EXIT_DEPENDENCY_UNAVAILABLE
    # Lock release, not a changed authority or reset, restores ordinary access.
    with journal.writer_lock(conn), store.corpus_write_lock(conn):
        assert conn.execute('SELECT 42').fetchone()[0] == 42


def test_missing_writer_ownership_is_not_transient(conn):
    with pytest.raises(publication.CorpusBusy) as caught:
        store._assert_corpus_locked(conn)
    conn.rollback()
    assert not shadow_worker._availability_failure(caught.value)
    assert not isinstance(automation_runtime.classify_dependency_failure(caught.value),
                          TransientInfrastructureFailure)


def test_real_database_timeout_resumes_same_acquisition_job(conn, operational_source, monkeypatch):
    import psycopg
    from sentinel.feed import operational_snapshot as op, rolling_jobs as jobs
    from sentinel.feed.rolling_source import ArchiveSource
    from tests.sentinel.test_operational_snapshot import enqueue
    job = enqueue(conn)
    deadline = jobs.status(conn, job)['deadline']
    original = ArchiveSource.preflight
    def timed_out(self):
        conn.execute("SET LOCAL statement_timeout='20ms'")
        conn.execute('SELECT pg_sleep(1)')
    monkeypatch.setattr(ArchiveSource, 'preflight', timed_out)
    with pytest.raises(psycopg.errors.QueryCanceled):
        op.prepare(conn, job)
    state = jobs.status(conn, job)
    assert state['state'] == 'RETRY_WAIT' and state['owner'] is None
    assert state['reason'] == 'DATABASE_UNAVAILABLE'
    assert state['deadline'] == deadline
    assert conn.execute('SELECT count(*) FROM sentinel_corpus_publications').fetchone()[0] == 0
    conn.execute('UPDATE sentinel_snapshot_jobs SET next_retry=clock_timestamp() WHERE job_id=%s', (job,))
    conn.commit()
    monkeypatch.setattr(ArchiveSource, 'preflight', original)
    result = op.prepare(conn, job)
    assert result['job_id'] == job
    assert jobs.status(conn, job)['deadline'] == deadline
    assert conn.execute('SELECT count(*) FROM sentinel_snapshot_jobs').fetchone()[0] == 1
    assert conn.execute('SELECT count(*) FROM sentinel_corpus_publications').fetchone()[0] == 1


def test_missing_lock_during_acquisition_is_terminal(conn, operational_source, monkeypatch):
    from sentinel.feed import operational_snapshot as op, rolling_jobs as jobs
    from sentinel.feed.rolling_source import ArchiveSource
    from tests.sentinel.test_operational_snapshot import enqueue
    monkeypatch.setattr(ArchiveSource, 'preflight', lambda _: store._assert_corpus_locked(conn))
    job = enqueue(conn)
    with pytest.raises(publication.CorpusBusy):
        op.prepare(conn, job)
    assert jobs.status(conn, job)['state'] == 'REFUSED'
    assert conn.execute('SELECT count(*) FROM sentinel_corpus_publications').fetchone()[0] == 0


@pytest.mark.parametrize('boundary', ['corpus_reader', 'behavioral_writer'])
def test_real_rolling_worker_recovers_without_reset_or_duplicate_state(
        conn, published, monkeypatch, boundary):
    from sentinel import rolling_authority
    from tests.sentinel.test_rolling_initialization import OBS, NOW
    class Borrowed:
        def __getattr__(self, name):
            return getattr(conn, name)
        def close(self):
            pass
    monkeypatch.setattr(store, 'connect', lambda _: Borrowed())
    config = shadow_service.ShadowServiceConfig('fixture', OBS, Decimal('100000'),
        shadow_runtime.SHADOW_PUBLICATION_TIMING_POLICY, 300)
    monkeypatch.setattr(shadow_worker.ShadowServiceConfig, 'from_env', lambda: config)
    monkeypatch.setattr(shadow_worker, 'advance_once',
                        lambda cfg: shadow_recovery.advance_once(cfg, now=NOW))
    before = conn.execute('SELECT cursor_name,session,state FROM sentinel_processed_sessions ORDER BY cursor_name,session').fetchall()
    with _contended(conn, boundary):
        assert shadow_worker.main() == shadow_worker.EXIT_DEPENDENCY_UNAVAILABLE
        assert conn.execute('SELECT cursor_name,session,state FROM sentinel_processed_sessions ORDER BY cursor_name,session').fetchall() == before
        conn.rollback()
    assert shadow_worker.main() == 0
    first = rolling_authority.latest(conn, OBS)
    conn.rollback()
    assert len(first) == 1
    assert shadow_worker.main() == 0
    assert rolling_authority.latest(conn, OBS) == first
    assert conn.execute('SELECT count(*) FROM sentinel_corpus_publications').fetchone()[0] == 1
    for table in ('sentinel_commands', 'sentinel_fills', 'sentinel_execution_plans'):
        assert conn.execute('SELECT count(*) FROM ' + table).fetchone()[0] == 0


@pytest.mark.parametrize('entry', ['advance_ready_shadow', 'verified_shadow_status', 'classify_shadow_lineage'])
@pytest.mark.parametrize('kind', ['database', 'integrity'])
def test_public_shadow_wrappers_preserve_dependency_type_without_unwrapping_integrity(
        conn, monkeypatch, entry, kind):
    import psycopg
    from sentinel import rolling_runtime
    def select(_):
        try:
            conn.execute("SET LOCAL statement_timeout='20ms'")
            conn.execute('SELECT pg_sleep(1)')
        except psycopg.errors.QueryCanceled as exc:
            if kind == 'integrity':
                raise shadow_runtime.ShadowRuntimeRefused('retained state changed') from exc
            raise
    monkeypatch.setattr(rolling_runtime, 'selected', select)
    kwargs = {'observation_id': 'fixture', 'starting_cash': 50000}
    if entry == 'advance_ready_shadow':
        kwargs['through'] = '2026-09-14'
    expected = psycopg.errors.QueryCanceled if kind == 'database' else shadow_runtime.ShadowRuntimeRefused
    with pytest.raises(expected) as caught:
        getattr(shadow_runtime, entry)(conn, **kwargs)
    conn.rollback()
    assert shadow_worker._availability_failure(caught.value) == (kind == 'database')


@pytest.mark.asyncio
@pytest.mark.parametrize('parent_lock', [False, True])
async def test_real_corpus_contention_preserves_idle_control_and_waiting_cycle(
        conn, monkeypatch, parent_lock):
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace
    import threading
    from sentinel import authority, schema
    from sentinel.automation import store as automation_store
    from sentinel.panel import model as panel_model
    from tests.sentinel.test_automation_service import config, enable, service_for
    from tests.sentinel.test_automation_runtime import production
    # The test advances its observation clock across a retry without running
    # the service heartbeat; keep the real lease alive during that jump.
    cfg = config().model_copy(update={'lease_seconds': 600, 'control_poll_seconds': 3})
    schema.ensure_schema(conn)
    enable(conn, cfg)
    now = datetime(2026, 8, 13, 13, 29, tzinfo=timezone.utc)
    service = service_for(cfg)
    for _ in range(6):
        await service.tick(conn, now=now)
        if automation_store.oldest_nonterminal_cycle(conn).state.value == 'WAITING_OPEN':
            break
    before_control = automation_store.load_control(conn)
    before_cycle = automation_store.oldest_nonterminal_cycle(conn)
    assert before_cycle.state.value == 'WAITING_OPEN'
    conn.rollback()
    runtime = production(cfg)
    def current(c):
        # Real immutable-reader lock with named publication and signed-gate
        # fixtures. Lease, durable control and cycle transitions remain real.
        rolling_store._pin_reader(c)
        return SimpleNamespace(version=1)
    monkeypatch.setattr(automation_runtime.feed_inputs, 'require_current', current)
    monkeypatch.setattr(automation_runtime, 'load_rollout_state', lambda _: authority.RolloutState(
        authority.RolloutMode.PINNED_1_00, 1, None))
    monkeypatch.setattr(automation_runtime, 'production_strategy', lambda: (object(), {}))
    monkeypatch.setattr(automation_runtime.system_identity, 'rehearsal_identity', lambda: {})
    publication_head = {'version': 1}
    monkeypatch.setattr(runtime, '_idle_publication_head',
                        lambda _connection: publication_head)
    def identity_fixture(connection, *, expected_sha256):
        return SimpleNamespace(certificate_sha256=expected_sha256)
    monkeypatch.setattr(runtime, '_idle_certificate_identity', identity_fixture)
    gates = []
    def signed():
        gates.append(1)
        return SimpleNamespace(certificate_sha256=before_control.certificate_sha256)
    clock = [datetime.now(timezone.utc)]
    monkeypatch.setattr(automation_runtime, '_now_utc', lambda: clock[0])

    def probe_authority(control):
        # The child has an external signed-authority seam, but still probes
        # the actual corpus advisory lock on a separate PostgreSQL session.
        with store.connect(conn.info.dsn) as probe:
            try:
                current(probe)
            except publication.CorpusLockUnavailable:
                result = {'status':'TRANSIENT'}
            else:
                certificate = signed()
                head = runtime._idle_publication_head(probe)
                result = {'status':'PASS', 'generation':control.generation,
                    'binding':control.binding.model_dump(mode='json'),
                    'rollout_mode':control.binding.rollout_mode,
                    'rollout_version':control.binding.rollout_version,
                    'publication_version':head['version'],
                    'publication_head':head,
                    'certificate_sha256':certificate.certificate_sha256}
            finally:
                probe.rollback()
        return result

    defer_probe = False
    def synthetic_observer(control, permit, observed_at):
        flight = SimpleNamespace(finished=threading.Event(), cancelled=threading.Event(),
            error=None, value=None, elapsed_seconds=0.0,
            timeout_seconds=25, stage='COMPLETE', backend_pid=None,
            stop=lambda: True)
        if not defer_probe:
            flight.value = probe_authority(control)
            flight.finished.set()
        runtime._idle_authority_flight = (
            flight, runtime._idle_attestation_key(control, permit), observed_at)
        return flight

    monkeypatch.setattr(runtime, '_start_idle_authority_observer', synthetic_observer)
    monkeypatch.setattr(runtime, '_broker', lambda *a: pytest.fail('idle broker reached'))
    monkeypatch.setattr(runtime, 'notify', lambda *a: pytest.fail('lock contention latched an incident'))
    # Persist the initial verdict. Leave a real writer in the way for
    # longer than the display proof lifetime, then give it a release window.
    assert await runtime.control_wake(conn) is None
    checked = automation_store.load_control(conn)
    assert checked.authority_verdict == 'PASS' and len(gates) == 1
    conn.rollback()
    began = clock[0]
    clock[0] = began + timedelta(seconds=30)
    if parent_lock:
        with _contended(conn, 'snapshot_reader'):
            due = await runtime.control_wake(conn)
    else:
        # Acquire the writer after the parent dispatches and releases its
        # transaction. The observer uses a different database session.
        defer_probe = True
        await runtime.control_wake(conn)
        flight, _, _ = runtime._idle_authority_flight
        with _contended(conn, 'snapshot_reader'):
            flight.value = probe_authority(checked)
            assert flight.value == {'status': 'TRANSIENT'}
            flight.finished.set()
        defer_probe = False
        due = await runtime.control_wake(conn)
    assert due > clock[0]
    clock[0] += timedelta(seconds=3)
    assert await runtime.control_wake(conn) == due
    with _contended(conn, 'snapshot_reader'):
        for seconds in (39, 303):
            clock[0] = began + timedelta(seconds=seconds)
            wake = await runtime.control_wake(conn)
            assert wake > clock[0]
            assert automation_store.load_control(conn) == checked
            assert automation_store.oldest_nonterminal_cycle(conn) == before_cycle
            assert conn.execute('SELECT COUNT(*) FROM sentinel_commands').fetchone()[0] == 0
            conn.rollback()
            assert len(gates) == 1
    row = panel_model.execution_authority_row(installed=True, runtime_verdict=checked.authority_verdict,
        checked_at=checked.authority_checked_at, certificate_sha256=checked.certificate_sha256,
        lifecycle_status='ACTIVE', lifecycle_current=True, verdict_binding_matches=True)
    assert row.effective_status(clock[0]) == panel_model.FAIL
    clock[0] += timedelta(seconds=3)
    assert await runtime.control_wake(conn) is None
    after = automation_store.load_control(conn)
    assert not after.kill_switch_engaged and after.generation == before_control.generation
    assert after.authority_verdict == 'PASS' and len(gates) == 2
    assert after.authority_checked_at > checked.authority_checked_at
    assert automation_store.oldest_nonterminal_cycle(conn) == before_cycle
    assert conn.execute('SELECT COUNT(*) FROM sentinel_commands').fetchone()[0] == 0


@pytest.mark.asyncio
async def test_bounded_worker_control_routes_fenced_progress_on_original_connection(
        conn, monkeypatch):
    from dataclasses import replace
    from datetime import datetime, timedelta, timezone
    from sentinel import schema
    from sentinel.automation import store as automation_store
    from tests.sentinel.test_automation_service import config, enable
    from tests.sentinel.test_automation_runtime import production

    cfg = config()
    schema.ensure_schema(conn)
    enable(conn, cfg)
    runtime = production(cfg)
    runtime.sentinel_config = replace(runtime.sentinel_config,
        database_url=conn.info.dsn)
    target = datetime.now(timezone.utc) + timedelta(seconds=5)
    routed = []

    async def fenced_progress(connection):
        assert connection is conn
        routed.append(connection.info.backend_pid)
        # The short parent connection has a 500 ms statement timeout. Fenced
        # data keeps the original service connection and its ordinary budget.
        connection.execute('SELECT pg_sleep(0.65)')
        connection.rollback()
        return target

    monkeypatch.setattr(runtime, '_fenced_data_wake', fenced_progress)
    automation_store.engage_kill(conn, actor='fixture', reason='fenced shadow')
    automation_store.deactivate(conn, actor='fixture', reason='fenced shadow')
    assert await runtime.bounded_control_wake(conn) == target
    assert routed == [conn.info.backend_pid]

    enable(conn, cfg)
    routed.clear()
    original = automation_store.load_control
    flipped = [False]

    def control_flip(connection, *args, **kwargs):
        value = original(connection, *args, **kwargs)
        if connection is not conn and value.enabled and not flipped[0]:
            flipped[0] = True
            with store.connect(conn.info.dsn) as writer:
                automation_store.engage_kill(
                    writer, actor='fixture', reason='fence after short read')
                automation_store.deactivate(
                    writer, actor='fixture', reason='fence after short read')
        return value

    with monkeypatch.context() as changed:
        changed.setattr(automation_store, 'load_control', control_flip)
        assert await runtime.bounded_control_wake(conn) is None
    assert flipped == [True] and not routed
    assert await runtime.bounded_control_wake(conn) == target
    assert routed == [conn.info.backend_pid]
    assert conn.execute('SELECT COUNT(*) FROM sentinel_commands').fetchone()[0] == 0


@pytest.mark.parametrize('kind', ['corpus', 'writer', 'database', 'integrity', 'ownership', 'lease', 'unknown'])
def test_authority_adapter_classifies_only_explicit_temporary_dependencies(kind):
    import psycopg
    from sentinel.authority import AuthorityRefused
    from sentinel.automation.model import NonRetryableCallbackRefused, StaleLeaderRefused
    from tests.sentinel.test_automation_runtime import config, production
    errors = {
        'corpus': publication.CorpusLockUnavailable('reader busy'),
        'writer': journal.WriterLockUnavailable('writer busy'),
        'database': psycopg.errors.QueryCanceled('bounded query timeout'),
        'integrity': AuthorityRefused('signature or lineage invalid'),
        'ownership': publication.CorpusBusy('writer ownership missing'),
        'lease': StaleLeaderRefused('fence superseded'),
        'unknown': ValueError('unexpected schema defect'),
    }
    errors['integrity'].__cause__ = errors['corpus']
    expected = (TransientInfrastructureFailure if kind in {'corpus', 'writer', 'database'}
                else StaleLeaderRefused if kind == 'lease'
                else ValueError if kind == 'unknown' else NonRetryableCallbackRefused)
    with pytest.raises(expected):
        production(config())._raise_authority_refusal(errors[kind])


@pytest.mark.parametrize('seconds,expected', [(299, True), (300, True), (301, False)])
def test_endurance_trace_observes_original_expiry_even_after_a_fresh_commit(seconds, expected):
    from datetime import datetime, timedelta, timezone
    from io import StringIO
    from tools.idle_open_endurance import Trace
    from sentinel.panel import model
    start = datetime.now(timezone.utc)
    trace = Trace(StringIO())
    def row(instant):
        return model.execution_authority_row(installed=True, runtime_verdict='PASS',
            checked_at=instant, certificate_sha256='a'*64, lifecycle_status='ACTIVE',
            lifecycle_current=True, verdict_binding_matches=True)
    trace.observe(row(start), start, 1, start)
    later = start + timedelta(seconds=seconds)
    if expected:
        trace.observe(row(later), later, 1, later)
    else:
        assert row(later).effective_status(later) == model.OK
        with pytest.raises(AssertionError, match='previous root expired'):
            trace.observe(row(later), later, 1, later)
    assert trace.max_age == seconds


@pytest.mark.asyncio
async def test_falsely_persisting_contention_as_negative_authority_is_detected(conn, monkeypatch):
    # Falsify the actual idle terminal classification while a second real
    # PostgreSQL session holds the corpus lock. The unmutated test must first
    # recover to PASS; a false permanent verdict reaches its incident guard.
    def wrongly_terminal(_runtime, _connection, exc):
        raise NonRetryableCallbackRefused(
            f'contention misclassified as authority: {type(exc).__name__}') from exc

    monkeypatch.setattr(automation_runtime.ProductionAutomation,
                        '_finish_idle_authority_refusal', wrongly_terminal)
    with pytest.raises(AssertionError):
        await test_real_corpus_contention_preserves_idle_control_and_waiting_cycle(
            conn, monkeypatch, parent_lock=True)
    from sentinel.automation import store as automation_store
    assert automation_store.load_control(conn).authority_verdict == 'FAIL'
