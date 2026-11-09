"""Finite operational publication inside the existing verifier role.

The child collects broker-free facts and commits review plus snapshot together.
The parent retains the sole verifier session lock and its original owner clock.
"""
from __future__ import annotations

from dataclasses import replace
from contextvars import ContextVar
from datetime import datetime, timezone
import os
import math
from pathlib import Path
from threading import Event, Thread
import time
import uuid

from sentinel import supervisor_io
from sentinel.panel import operational_schema as schema
from sentinel.panel.verification_health import OPERATIONAL_HEARTBEAT

DEADLINE_SECONDS = 20
FAST_DEADLINE_SECONDS = 5
POLL_SECONDS = 5
SUPERSEDED_RETRY_SECONDS = 1
MAX_REFRESH_SECONDS = 30
REFRESH_MARGIN_SECONDS = 2
HEARTBEAT = OPERATIONAL_HEARTBEAT
_COLLECTION_STAGE = ContextVar('operational_collection_stage', default='NOT_STARTED')
_READ_STAGES = frozenset({'COORDINATES','COLLECT','CONNECT','OWNER','INPUT_FENCE','FINAL_CONTEXT','LIVENESS'})


class CollectionSuperseded(ValueError):
    pass


def refresh_delay(expiry, *, now, elapsed):
    """Reserve the original call ceiling, not an optimistic previous runtime."""
    remaining = (expiry-now).total_seconds()
    if remaining <= 0 or not math.isfinite(elapsed) or elapsed < 0:
        raise TimeoutError('operational publication has no remaining delivery budget')
    budget = max(FAST_DEADLINE_SECONDS, elapsed)
    return max(.25, min(MAX_REFRESH_SECONDS, remaining-budget-REFRESH_MARGIN_SECONDS))


def _coordinates(database_url):
    from sentinel.feed import store
    from sentinel.panel import operational_snapshot as snapshots
    conn = store.connect(database_url, connect_timeout=3, statement_timeout_ms=3000)
    try:
        return snapshots.context(conn, database_url), snapshots.subjects(conn, database_url)
    finally:
        conn.rollback()
        conn.close()


def lock_inputs(conn):
    """Short publication/ACK boundary; never lock plans, commands or authority."""
    conn.execute("SET LOCAL lock_timeout='1000ms'")
    conn.execute(f'SELECT scope FROM {schema.REVISION} '
                 "WHERE scope IN ('SHADOW','PAPER') ORDER BY scope FOR KEY SHARE").fetchall()
    conn.execute(f'SELECT scope FROM {schema.RECEIPTS} '
                 "WHERE scope IN ('SHADOW','PAPER') ORDER BY scope FOR SHARE").fetchall()


def publish_once(database_url, owner_id, state_dir, instance, prior_failed=False,
                 *, shadow_observer=None, use_composition=False):
    from sentinel.feed import store
    from sentinel.panel import attempt_store, operational_snapshot as snapshots, review, segment_disclosure, sources

    _COLLECTION_STAGE.set('COORDINATES')
    stable_expiry = None
    worker_row = None
    if use_composition:
        from sentinel.panel import composition
        panel,context,subjects,stable_expiry = composition.read(owner_id,instance,now=datetime.now(timezone.utc))
        if _coordinates(database_url)!=(context,subjects):
            raise CollectionSuperseded('composition subject changed')
        if any(row.key=='shadow_worker' for row in panel.rows):
            worker_row=sources._shadow_worker_row(state_dir,database_url,observer=shadow_observer)
    else:
        context, subjects = _coordinates(database_url)
        _COLLECTION_STAGE.set('COLLECT')
        panel = segment_disclosure.disclose(sources.build_panel(
            state_dir=Path(state_dir), database_url=database_url,
            shadow_observer=shadow_observer), database_url)
    recorder = review.Recorder(component='verifier', instance=instance)
    if prior_failed:
        recorder.read_failed()
    _COLLECTION_STAGE.set('CONNECT')
    conn = store.connect(database_url, connect_timeout=3, statement_timeout_ms=3000)
    try:
        _COLLECTION_STAGE.set('OWNER')
        owner = conn.execute(f'SELECT owner_id,expires_at FROM {schema.OWNER} '
            'WHERE id=1 AND owner_id=%s AND expires_at>clock_timestamp() FOR UPDATE',
            (owner_id,)).fetchone()
        if owner is None:
            raise snapshots.SnapshotUnavailable('operational projection owner changed')
        # Financial receipt publication uses owner -> receipt. Preserve that
        # order here rather than holding a receipt while waiting for its owner.
        _COLLECTION_STAGE.set('INPUT_FENCE')
        lock_inputs(conn)
        _COLLECTION_STAGE.set('FINAL_CONTEXT')
        if (snapshots.context(conn, database_url) != context
                or snapshots.subjects(conn, database_url) != subjects):
            raise CollectionSuperseded('operational projection inputs changed')
        # Full automation composition can outlive a 12-second leader lease.
        # Sample its bounded native liveness facts after fencing, without
        # repeating authority, alert and cycle-history composition.
        _COLLECTION_STAGE.set('LIVENESS')
        panel = replace(panel, rows=sources._late_automation_rows(conn, panel.rows))
        if use_composition:
            panel=replace(panel,rows=composition.native_services(conn,panel.rows,worker=worker_row))
        # Publisher and acknowledgement acquire the receipt before review state.
        # A common order avoids a receipt/state lock inversion.
        conn.execute(f'SELECT scope FROM {schema.RECEIPTS} '
                     "WHERE scope='DASHBOARD' FOR UPDATE").fetchall()
        now = review.store.database_now(conn)
        if stable_expiry is not None and now >= stable_expiry:
            raise CollectionSuperseded('composition expired before publication')
        diagnostics = {scope: attempt_store.read_owned(conn, scope=scope, now=now)
                       for scope in ('SHADOW', 'PAPER')}
        panel = replace(panel, now=now, trial_details={**panel.trial_details,
            'verification_attempts': {key: value for key, value in diagnostics.items() if value is not None}})
        _COLLECTION_STAGE.set('REVIEW')
        result = recorder.observe_owned(conn, panel, database_url)
        panel = replace(panel, operator_review=result)
        _COLLECTION_STAGE.set('ENCODE')
        from sentinel.panel.serialization import preflight
        preflight(panel)
        envelope, signature = snapshots.encode(panel, context_sha256=context, subjects=subjects,
            valid_until=min(snapshots.original_boundary(panel), owner[1],
                            stable_expiry or owner[1]))
        _COLLECTION_STAGE.set('PUBLISH')
        snapshots.publish_owned(conn, owner_id=owner_id, value=envelope,
            signature=signature, context_sha256=context, subjects=subjects, now=now)
        if review.store.database_now(conn) >= datetime.fromisoformat(envelope['valid_until']):
            raise CollectionSuperseded('operational collection expired before commit')
        _COLLECTION_STAGE.set('COMMIT')
        conn.commit()
        recorder.committed()
        return {'valid_until': envelope['valid_until']}
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def publish_failure(database_url, owner_id, instance, diagnostic, *, context=None):
    """Publish an explicit negative collector fact, never retained positive rows."""
    from sentinel.feed import store
    from sentinel.panel import model, observer_failure, operational_snapshot as snapshots, review
    failure = observer_failure.Failure.model_validate(diagnostic)
    conn = store.connect(database_url, connect_timeout=3, statement_timeout_ms=3000)
    try:
        owner = conn.execute(f'SELECT owner_id,expires_at FROM {schema.OWNER} '
            'WHERE id=1 AND owner_id=%s AND expires_at>clock_timestamp() FOR UPDATE',
            (owner_id,)).fetchone()
        if owner is None:
            raise snapshots.SnapshotUnavailable('operational projection owner changed')
        lock_inputs(conn)
        context_sha256, subjects = snapshots.context(conn, database_url), snapshots.subjects(conn, database_url)
        conn.execute(f'SELECT scope FROM {schema.RECEIPTS} '
                     "WHERE scope='DASHBOARD' FOR UPDATE").fetchall()
        now = review.store.database_now(conn)
        detail = 'Operational collection failed · '+failure.safe_detail()
        panel = model.Panel(now=now, rows=[model.Row('operational_projection',
            'Operational observation', 'OBSERVATION UNAVAILABLE', model.UNKNOWN,
            detail=detail, as_of=now, required_current=True)],
            source_errors=['Operational collection unavailable'],
            trial_details={'operational_failure':failure.model_dump(mode='json', by_alias=True),
                           'operational_failure_context':context})
        recorder = review.Recorder(component='verifier', instance=instance)
        panel = replace(panel, operator_review=recorder.observe_owned(conn, panel, database_url))
        value, signature = snapshots.encode(panel, context_sha256=context_sha256, subjects=subjects,
            valid_until=min(snapshots.original_boundary(panel), owner[1]))
        snapshots.publish_owned(conn, owner_id=owner_id, value=value, signature=signature,
            context_sha256=context_sha256, subjects=subjects, now=now)
        if review.store.database_now(conn) >= datetime.fromisoformat(value['valid_until']):
            raise CollectionSuperseded('negative operational observation expired before commit')
        conn.commit()
        return {'valid_until':value['valid_until']}
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def collect_result(database_url, owner_id, state_dir, instance, prior_failed=False,
                   *, shadow_observer=None, use_composition=False):
    """Classify child refusals before the generic process wrapper loses type."""
    from psycopg.errors import LockNotAvailable, QueryCanceled
    from sentinel.panel import composition
    started = time.monotonic()
    deadline = started + DEADLINE_SECONDS
    attempts = 0
    token = _COLLECTION_STAGE.set('NOT_STARTED')
    try:
        # Actual child execution is liveness; only publication creates readiness.
        # The existing parent deadline also bounds this filesystem write.
        HEARTBEAT.write_text(datetime.now(timezone.utc).isoformat(), encoding='ascii')
        while True:
            attempts += 1
            try:
                return {'outcome':'PUBLISHED', **publish_once(
                    database_url, owner_id, state_dir, instance, prior_failed,
                    shadow_observer=shadow_observer,
                    **({'use_composition':True} if use_composition else {}))}
            except (QueryCanceled, LockNotAvailable):
                # One fresh read attempt, never a new transport/call allowance.
                # COMMIT/REVIEW failures and unknown outcomes are not replayed.
                if (attempts >= 2 or _COLLECTION_STAGE.get() not in _READ_STAGES
                        or time.monotonic() >= deadline-3):
                    raise
                time.sleep(min(.25, max(0, deadline-3-time.monotonic())))
                if time.monotonic() >= deadline-3:
                    raise
    except (CollectionSuperseded, composition.Pending):
        return {'outcome':'SUPERSEDED'}
    except Exception as exc:
        from sentinel.panel import observer_failure
        diagnostic = (exc.diagnostic if isinstance(exc,composition.Failed) else
            observer_failure.classify(exc).model_dump(mode='json', by_alias=True))
        try:
            context = dict(schema='sentinel.operational-failure-context/1',
                stage=_COLLECTION_STAGE.get(),attempts=attempts,
                elapsed_ms=max(0,int((time.monotonic()-started)*1000)))
            return {'outcome':'PUBLISHED', **publish_failure(database_url, owner_id, instance,
                diagnostic, context=context)}
        except Exception:
            return {'outcome':'FAILED', 'type':type(exc).__name__}
    finally:
        _COLLECTION_STAGE.reset(token)


class Collector:
    """Own the reusable filesystem observer only inside the spawned collector."""

    def __init__(self):
        # This object is pickled by spawn. Allocate no child or descriptor here.
        self.observer = None

    def prepare(self):
        """Initialize immutable dependencies once, without IO or evidence."""
        from sentinel.feed import calendar
        from sentinel.panel import attempt_store, composition, segment_disclosure, serialization, sources  # noqa: F401
        # Pinned tables are process-local. This earns no market/currentness
        # verdict and is not a database, filesystem observer or broker probe.
        calendar._calendar()

    def __call__(self, database_url, owner_id, state_dir, instance, prior_failed=False):
        if self.observer is None:
            from sentinel.shadow_service_probe import Observer
            self.observer = Observer(Path(state_dir))
        elif self.observer.state_dir != Path(state_dir):
            raise ValueError('collector observer state directory changed')
        return collect_result(database_url, owner_id, state_dir, instance, prior_failed,
                              shadow_observer=self.observer)

    def close(self):
        if self.observer is not None:
            self.observer.close()
            self.observer = None


class CompositionCollector(Collector):
    def __call__(self,database_url,owner_id,state_dir,instance,prior_failed=False):
        from sentinel.panel import composition
        if self.observer is None:
            from sentinel.shadow_service_probe import Observer
            self.observer=Observer(Path(state_dir))
        try:
            return composition.collect(database_url,owner_id,state_dir,instance,shadow_observer=self.observer)
        except CollectionSuperseded:
            return {'outcome':'SUPERSEDED'}
        except Exception as exc:
            composition.failure(owner_id,instance,exc)
            return {'outcome':'FAILED','type':type(exc).__name__}


class FastCollector(Collector):
    def __call__(self,database_url,owner_id,state_dir,instance,prior_failed=False):
        if self.observer is None:
            from sentinel.shadow_service_probe import Observer
            self.observer=Observer(Path(state_dir))
        return collect_result(database_url,owner_id,state_dir,instance,prior_failed,
            shadow_observer=self.observer,use_composition=True)


class Publisher:
    """One bounded child at a time; no HTTP admission and no new runtime role."""

    def __init__(self, database_url, owner_id, *, stopped=None, runner=None):
        self.database_url = database_url
        self.owner_id = owner_id
        self.state_dir = os.environ.get('SENTINEL_STATE_DIR', '/var/lib/sentinel')
        self.instance = str(uuid.uuid4())
        self.stopped = stopped or Event()
        self.runner = runner
        from sentinel.panel.projection_worker import Worker
        self.worker = Worker(FastCollector(), self.database_url, self.owner_id,
                             self.state_dir, self.instance) if runner is None else None
        self.composition_worker = Worker(CompositionCollector(),self.database_url,self.owner_id,
            self.state_dir,self.instance) if runner is None else None
        self.composition_wake=Event()
        self.composition_busy=Event()
        self.composition_thread=Thread(target=self.run_composition,name='sentinel-full-composition',daemon=True)
        self.composition_started=False
        self.component_attempted=Event()
        self.thread = Thread(target=self.run, name='sentinel-operational-projection', daemon=True)
        self.started = False

    def start(self):
        if self.composition_worker is not None:
            self.composition_thread.start()
            self.composition_started=True
        self.thread.start()
        self.started = True

    def run(self):
        failed = False
        while not self.stopped.is_set():
            delay = POLL_SECONDS
            started = time.monotonic()
            try:
                if self.worker is not None:
                    if not self.component_attempted.wait(.1):
                        continue
                    if self.stopped.is_set():
                        break
                    self.worker.start(timeout=DEADLINE_SECONDS)
                    if self.stopped.is_set():
                        break
                    started = time.monotonic()
                result = (self.worker.call(failed, timeout=FAST_DEADLINE_SECONDS) if self.worker is not None
                    else self.runner(collect_result, self.database_url, self.owner_id,
                        self.state_dir, self.instance, failed,
                        timeout=FAST_DEADLINE_SECONDS, start_method='spawn'))
                if result.get('outcome') == 'PUBLISHED':
                    expiry = datetime.fromisoformat(result['valid_until'])
                    delay = refresh_delay(expiry, now=datetime.now(timezone.utc),
                                          elapsed=time.monotonic()-started)
                    failed = False
                    HEARTBEAT.write_text(datetime.now(timezone.utc).isoformat(), encoding='ascii')
                elif result.get('outcome') == 'SUPERSEDED':
                    delay = SUPERSEDED_RETRY_SECONDS
                    if not self.composition_busy.is_set():
                        self.composition_wake.set()
                else:
                    failed = True
            except Exception as exc:
                failed = True
                supervisor_io.report('operational projection unavailable: '+type(exc).__name__)
            self.stopped.wait(delay)

    def run_composition(self):
        from sentinel.panel import composition
        while not self.stopped.is_set():
            self.composition_wake.clear()
            self.composition_busy.set()
            delay=POLL_SECONDS
            try:
                self.composition_worker.start(timeout=DEADLINE_SECONDS)
                if self.stopped.is_set():
                    break
                result=self.composition_worker.call(False,timeout=DEADLINE_SECONDS)
                if result.get('outcome')=='PUBLISHED':
                    remaining=(datetime.fromisoformat(result['valid_until'])-datetime.now(timezone.utc)).total_seconds()
                    delay=max(1,min(MAX_REFRESH_SECONDS,remaining-DEADLINE_SECONDS-REFRESH_MARGIN_SECONDS))
                elif result.get('outcome')=='SUPERSEDED':
                    delay=1
                if result.get('outcome') in {'PUBLISHED','FAILED'}:
                    self.component_attempted.set()
            except Exception as exc:
                composition.failure(self.owner_id,self.instance,exc)
                self.component_attempted.set()
            finally:
                self.composition_busy.clear()
            self.composition_wake.wait(delay)

    def close(self):
        self.stopped.set()
        self.composition_wake.set()
        self.component_attempted.set()
        shutdown_seconds=2*DEADLINE_SECONDS+3
        end=time.monotonic()+shutdown_seconds
        if self.started:
            self.thread.join(shutdown_seconds)
            if self.thread.is_alive():
                raise TimeoutError('operational projection did not finish its bounded shutdown')
        if self.composition_started:
            self.composition_thread.join(max(0,end-time.monotonic()))
            if self.composition_thread.is_alive():
                raise TimeoutError('full composition did not finish its bounded shutdown')
        if self.worker is not None:
            self.worker.close()
        if self.composition_worker is not None:
            self.composition_worker.close()
        from sentinel.panel.composition import path
        path(self.instance).unlink(missing_ok=True)
        HEARTBEAT.unlink(missing_ok=True)


def read(database_url):
    """SELECT-only current snapshot; requests never discover or record incidents."""
    from sentinel.feed import store
    from sentinel.panel import operational_snapshot as snapshots, review
    conn = store.connect(database_url, connect_timeout=3, statement_timeout_ms=3000)
    try:
        conn.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        context = snapshots.context(conn, database_url)
        now = review.store.database_now(conn)
        value = snapshots.read_owned(conn, context_sha256=context, now=now)
        if value.panel.operator_review is None:
            raise snapshots.SnapshotUnavailable('operational review observation missing')
        current_subjects = snapshots.subjects(conn, database_url)
        changed = tuple(scope for scope in ('SHADOW', 'PAPER')
                        if value.subjects[scope] != current_subjects[scope])
        recorded = conn.execute('SELECT payload,signature FROM sentinel_dashboard_review_state '
                                'WHERE scope_sha256=%s', (value.panel.operator_review.scope,)).fetchone()
        if recorded is None:
            raise snapshots.SnapshotUnavailable('operational review state missing')
        review.store.authenticate(dict(scope=value.panel.operator_review.scope, state=recorded[0]),
                                  recorded[1], purpose=review.store.SCHEMA)
        if recorded[0].get('head') != value.panel.operator_review.head and not changed:
            raise snapshots.SnapshotUnavailable('operational review head changed')
        panel = replace(value.panel, now=now, observation_current=not changed,
            observation_changed_scopes=changed, observation_valid_until=value.valid_until)
        if changed:
            from sentinel.panel import read_projection
            # Cheap receipt consumption only. A PAPER update must not discard
            # the independent SHADOW proof, and a newly negative receipt must
            # take precedence immediately even before the next full snapshot.
            replacements, selected_errors = {}, []
            for scope in changed:
                current_rows, _, _, errors = read_projection.read(
                    database_url, now=now, only_scope=scope)
                keys = (read_projection.SHADOW_KEYS if scope == 'SHADOW'
                        else read_projection.PAPER_KEYS)
                replacements.update((row.key, row) for row in current_rows if row.key in keys)
                selected_errors.extend(errors)
            existing = {row.key for row in panel.rows}
            panel = replace(panel, rows=[*[replacements.get(row.key, row) for row in panel.rows],
                                        *[row for key, row in replacements.items() if key not in existing]],
                            observation_revalidated_keys=tuple(replacements),
                            source_errors=list(dict.fromkeys([*panel.source_errors, *selected_errors])))
        finished = review.store.database_now(conn)
        if finished >= value.valid_until:
            raise snapshots.SnapshotUnavailable('operational snapshot expired during read')
        return replace(panel, now=finished)
    finally:
        conn.rollback()
        conn.close()


def guard_acknowledgement(conn, panel, database_url):
    from sentinel.panel import operational_snapshot as snapshots, review
    owner = conn.execute(f'SELECT owner_id FROM {schema.OWNER} '
                         'WHERE id=1 AND expires_at>clock_timestamp() FOR SHARE').fetchone()
    if owner is None:
        raise review.store.ReviewRefused('operational owner unavailable during acknowledgement')
    lock_inputs(conn)
    now = review.store.database_now(conn)
    latest = snapshots.read_owned(conn, context_sha256=snapshots.context(conn, database_url),
                                  now=now, lock=True)
    if (not panel.observation_current
            or latest.subjects != snapshots.subjects(conn, database_url)
            or latest.panel.operator_review != panel.operator_review
            or review.view_subject(latest.panel) != review.view_subject(panel)):
        raise review.store.ReviewRefused('operational snapshot changed during acknowledgement')


def register_panel_incarnation(database_url, instance):
    """Explicit startup metadata, independent of requests and financial facts."""
    from sentinel.panel import review
    with review.store.transaction(database_url) as conn:
        key, now = review.store.scope(conn), review.store.database_now(conn)
        state = review.store.load_locked(conn, key, now)
        event = 'dashboard:'+instance
        if not review.store.has_event(conn, key, event):
            review.store.append(conn, key, state, kind='STARTED', event_key=event,
                details={'component':'dashboard', 'reason':'Deployment or restart'}, now=now)
            if not state['view_sha256']:
                import hashlib
                state['view_sha256'] = hashlib.sha256(review.store.canonical(
                    {'schema':'sentinel.unobserved-operational-view/1',
                     'scope':key, 'incarnation':instance})).hexdigest()
            review.store.save(conn, key, state, now)
