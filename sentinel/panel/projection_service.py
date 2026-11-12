"""Finite operational publication inside the existing verifier role.

The child collects broker-free facts and commits review plus snapshot together.
The parent retains the sole verifier session lock and its original owner clock.
"""
from __future__ import annotations

from dataclasses import replace
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
import os
import json
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


def _report_parent_deadline(publisher, error, expiry):
    from sentinel.panel.projection_worker import WorkerDeadline
    if not isinstance(error, WorkerDeadline):
        return False
    try:
        value = dict(schema='sentinel.projection-deadline/1', publisher=publisher,
                     stage=error.stage, budget_seconds=error.budget_seconds,
                     deadline_monotonic=error.deadline_monotonic,
                     elapsed_seconds=(error.elapsed_seconds if math.isfinite(error.elapsed_seconds)
                                      and error.elapsed_seconds >= 0 else None),
                     checked_at=(error.checked_at.isoformat() if error.checked_at is not None else None),
                     original_valid_until=(expiry.isoformat() if expiry is not None else None),
                     reap_outcome=error.reap_outcome)
        message = 'SENTINEL_PROJECTION_DEADLINE=' + json.dumps(
            value, sort_keys=True, separators=(',', ':'), allow_nan=False)
        supervisor_io._pipe_report(message)
    except Exception:
        pass  # Diagnostic delivery has no effect on ownership or retry.
    return True


def _coordinates(database_url):
    return _coordinate_read(database_url)[:2]


def _display_coordinates(database_url):
    return _coordinate_read(database_url, display=True)


def _coordinate_read(database_url, *, display=False):
    from sentinel.feed import store
    from sentinel.panel import operational_snapshot as snapshots, read_projection, display_dependencies
    conn = store.connect(database_url, connect_timeout=3, statement_timeout_ms=3000)
    try:
        conn.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        context = snapshots.context(conn, database_url)
        facts = read_projection._subject_facts(conn)
        if display:
            basis = display_dependencies.capture(conn, database_url, facts=facts)
            return context, display_dependencies.combined_subjects(basis), basis
        return context, snapshots.subjects(conn, database_url, facts=facts)
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
                 *, shadow_observer=None, candidate_memo=None):
    from sentinel.feed import store
    from sentinel.panel import attempt_store, composition, operational_snapshot as snapshots, review, sources
    from sentinel.panel import display_dependencies, read_projection, delivery, postclose_feed_wait

    _COLLECTION_STAGE.set('COORDINATES')
    worker_row = None
    panel,context,subjects,stable_expiry = composition.read(owner_id,instance,now=datetime.now(timezone.utc))
    if panel.row('shadow_worker') is not None:
        worker_row=sources._shadow_worker_row(state_dir,database_url,observer=shadow_observer)
    recorder = review.Recorder(component='verifier', instance=instance)
    if prior_failed:
        recorder.read_failed()
    _COLLECTION_STAGE.set('CONNECT')
    conn = store.connect(database_url, connect_timeout=3, statement_timeout_ms=3000)
    try:
        conn.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ')
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
        facts = read_projection._subject_facts(conn)
        current_basis = display_dependencies.capture(conn, database_url, facts=facts)
        current_subjects = display_dependencies.combined_subjects(current_basis)
        if snapshots.context(conn, database_url) != context:
            raise CollectionSuperseded('operational projection inputs changed')
        changed = tuple(scope for scope in ('SHADOW','PAPER')
                        if current_subjects[scope] != subjects[scope])
        if changed:
            if not display_dependencies.native_reuse(
                    conn, database_url, panel.display_basis, current_basis, facts=facts):
                raise CollectionSuperseded('operational projection inputs changed')
            if set(delivery.display_keys(panel)) != {row.key for row in panel.rows}:
                raise CollectionSuperseded('composition has unproved display dependencies')
            replacements, errors = {}, []
            now = review.store.database_now(conn)
            for scope in changed:
                rows, _, _, selected_errors = read_projection.read_owned(
                    conn, database_url, now=now, only_scope=scope, native_subjects=current_basis['native'])
                replacements.update((row.key,row) for row in rows)
                errors.extend(selected_errors)
            panel = replace(display_dependencies.overlay(panel, replacements),
                source_errors=list(dict.fromkeys([*panel.source_errors,*errors])))
        if panel.display_basis.get('account_anchor') != current_basis.get('account_anchor'):
            negative = display_dependencies.current_account_negative(conn, panel,
                now=review.store.database_now(conn))
            if negative is not None:
                panel = display_dependencies.overlay(panel, {negative.key:negative})
        subjects = current_subjects
        panel = replace(panel, display_basis=current_basis)
        # Full automation composition can outlive a 12-second leader lease.
        # Sample its bounded native liveness facts after fencing, without
        # repeating full alert and cycle-history composition.
        _COLLECTION_STAGE.set('LIVENESS')
        panel = replace(panel, rows=sources._late_automation_rows(conn, panel.rows))
        authority = next((row for row in panel.rows if row.key == 'authority'), None)
        if authority is not None:
            current = sources._late_authority_display(conn, authority,
                now=review.store.database_now(conn))
            panel = display_dependencies.overlay(panel, {current.key: current})
        panel=replace(panel,rows=composition.native_services(conn,panel.rows,worker=worker_row))
        # Publisher and acknowledgement acquire the receipt before review state.
        # A common order avoids a receipt/state lock inversion.
        conn.execute(f'SELECT scope FROM {schema.RECEIPTS} '
                     "WHERE scope='DASHBOARD' FOR UPDATE").fetchall()
        now = review.store.database_now(conn)
        if now >= stable_expiry:
            raise CollectionSuperseded('composition expired before publication')
        diagnostics = {scope: attempt_store.read_owned(conn, scope=scope, now=now)
                       for scope in ('SHADOW', 'PAPER')}
        panel = replace(panel, now=now, trial_details={**panel.trial_details,
            'verification_attempts': {key: value for key, value in diagnostics.items() if value is not None}})
        from sentinel.panel import readiness_handoff
        progress = readiness_handoff.capture(conn, panel, subject=current_basis['native']['SHADOW'],
            owner_expiry=owner[1], now=now, candidate_memo=candidate_memo)
        panel = replace(panel, trial_details={**panel.trial_details, 'readiness_handoff': progress})
        # Fresh receipt/native overlays enter after build_panel's producer
        # boundary. Apply the same known-instant contract to this final handoff.
        panel = replace(panel, rows=[sources._utc_row(row) for row in panel.rows])
        view = postclose_feed_wait.project_panel(panel, now=now, subject=current_basis['native']['SHADOW'])
        _COLLECTION_STAGE.set('REVIEW')
        result = recorder.observe_owned(conn, view, database_url)
        panel = replace(panel, operator_review=result)
        view = replace(view, operator_review=result)
        _COLLECTION_STAGE.set('ENCODE')
        from sentinel.panel.serialization import preflight
        preflight(view)
        envelope, signature = snapshots.encode(panel, context_sha256=context, subjects=subjects,
            valid_until=min(snapshots.original_boundary(view), owner[1], stable_expiry))
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
                   *, shadow_observer=None, candidate_memo=None):
    """Classify child refusals before the generic process wrapper loses type."""
    from psycopg.errors import LockNotAvailable, QueryCanceled, SerializationFailure
    from sentinel.panel import composition
    started = time.monotonic()
    deadline = started + FAST_DEADLINE_SECONDS
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
                    shadow_observer=shadow_observer, candidate_memo=candidate_memo)}
            except (QueryCanceled, LockNotAvailable):
                # One fresh read attempt, never a new transport/call allowance.
                # COMMIT/REVIEW failures and unknown outcomes are not replayed.
                if (attempts >= 2 or _COLLECTION_STAGE.get() not in _READ_STAGES
                        or time.monotonic() >= deadline-3):
                    raise
                time.sleep(min(.25, max(0, deadline-3-time.monotonic())))
                if time.monotonic() >= deadline-3:
                    raise
    except (CollectionSuperseded, composition.Pending, SerializationFailure):
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

    def observer_for(self, state_dir):
        path = Path(state_dir)
        if self.observer is None:
            from sentinel.shadow_service_probe import Observer
            self.observer = Observer(path)
        elif self.observer.state_dir != path:
            raise ValueError('collector observer state directory changed')
        return self.observer

    def close(self):
        if self.observer is not None:
            self.observer.close()
            self.observer = None


class CompositionCollector(Collector):
    def __call__(self,database_url,owner_id,state_dir,instance,prior_failed=False):
        from sentinel.panel import composition
        observer = self.observer_for(state_dir)
        try:
            return composition.collect(database_url,owner_id,state_dir,instance,shadow_observer=observer)
        except CollectionSuperseded:
            return {'outcome':'SUPERSEDED'}
        except Exception as exc:
            composition.failure(owner_id,instance,exc)
            return {'outcome':'FAILED','type':type(exc).__name__}


class FastCollector(Collector):
    def __init__(self):
        super().__init__()
        self.candidate_memo = None

    def __call__(self,database_url,owner_id,state_dir,instance,prior_failed=False):
        observer = self.observer_for(state_dir)
        if self.candidate_memo is None:
            from sentinel.panel.readiness_handoff import CandidateMemo
            self.candidate_memo = CandidateMemo()
        return collect_result(database_url,owner_id,state_dir,instance,prior_failed,
            shadow_observer=observer,candidate_memo=self.candidate_memo)


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
        from sentinel.panel.projection_worker import WorkerDeadline
        failed = False
        published_expiry = None
        while not self.stopped.is_set():
            delay = POLL_SECONDS
            started = time.monotonic()
            result_expiry = None
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
                    result_expiry = datetime.fromisoformat(result['valid_until'])
                    checked_at = datetime.now(timezone.utc)
                    elapsed = time.monotonic()-started
                    try:
                        delay = refresh_delay(result_expiry, now=checked_at,
                                              elapsed=elapsed)
                    except TimeoutError as error:
                        stage = ('PUBLICATION_EXPIRY' if result_expiry <= checked_at
                                 else 'PUBLICATION_CLOCK_INVALID')
                        deadline = WorkerDeadline(stage, started=started,
                            timeout=FAST_DEADLINE_SECONDS, checked_at=checked_at, elapsed=elapsed)
                        if self.worker is not None:
                            deadline.reap_outcome = 'WORKER_RETAINED'
                        raise deadline from error
                    published_expiry = result_expiry
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
                if not _report_parent_deadline('FAST', exc, result_expiry or published_expiry):
                    supervisor_io.report('operational projection unavailable: '+type(exc).__name__)
            self.stopped.wait(delay)

    def run_composition(self):
        from sentinel.panel import composition
        published_expiry = None
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
                    published_expiry = datetime.fromisoformat(result['valid_until'])
                    remaining=(published_expiry-datetime.now(timezone.utc)).total_seconds()
                    delay=max(1,min(MAX_REFRESH_SECONDS,remaining-DEADLINE_SECONDS-REFRESH_MARGIN_SECONDS))
                elif result.get('outcome')=='SUPERSEDED':
                    delay=1
                if result.get('outcome') in {'PUBLISHED','FAILED'}:
                    self.component_attempted.set()
            except Exception as exc:
                _report_parent_deadline('COMPOSITION', exc, published_expiry)
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


def read(database_url, *, display=False):
    """SELECT-only current snapshot; requests never discover or record incidents."""
    from sentinel.feed import store
    from sentinel.panel import operational_snapshot as snapshots, review, read_projection, display_dependencies, delivery
    conn = store.connect(database_url, connect_timeout=3, statement_timeout_ms=3000)
    try:
        conn.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        context = snapshots.context(conn, database_url)
        now = review.store.database_now(conn)
        value = snapshots.read_owned(conn, context_sha256=context, now=now,
                                     **({'display':True} if display else {}))
        if value.panel.operator_review is None:
            raise snapshots.SnapshotUnavailable('operational review observation missing')
        facts = read_projection._subject_facts(conn)
        current_basis = (display_dependencies.capture(conn, database_url, facts=facts)
                         if value.panel.display_basis else {})
        current_subjects = (display_dependencies.combined_subjects(current_basis) if current_basis
                            else snapshots.subjects(conn, database_url, facts=facts))
        changed = tuple(scope for scope in ('SHADOW', 'PAPER')
                        if value.subjects[scope] != current_subjects[scope])
        recorded = conn.execute('SELECT payload,signature FROM sentinel_dashboard_review_state '
                                'WHERE scope_sha256=%s', (value.panel.operator_review.scope,)).fetchone()
        if recorded is None:
            raise snapshots.SnapshotUnavailable('operational review state missing')
        review.store.authenticate(dict(scope=value.panel.operator_review.scope, state=recorded[0]),
                                  recorded[1], purpose=review.store.SCHEMA)
        head_changed = recorded[0].get('head') != value.panel.operator_review.head
        if head_changed and not changed and not display:
            raise snapshots.SnapshotUnavailable('operational review head changed')
        retained = display and (now >= value.valid_until or head_changed)
        panel = replace(value.panel, now=now, observation_current=not changed and not retained,
            observation_changed_scopes=changed, observation_valid_until=value.valid_until)
        if display:
            panel = replace(panel, observation_generated_at=value.generated_at)
        if display and head_changed and recorded[0].get('active'):
            panel = replace(panel, source_errors=list(dict.fromkeys([*panel.source_errors,
                'Current signed review records active conditions; current display composition is pending.'])))
        if changed:
            # Cheap receipt consumption only. A PAPER update must not discard
            # the independent SHADOW proof, and a newly negative receipt must
            # take precedence immediately even before the next full snapshot.
            replacements, selected_errors = {}, []
            for scope in changed:
                current_rows, _, _, errors = read_projection.read_owned(
                    conn, database_url, now=now, only_scope=scope, facts=facts,
                    native_subjects=current_basis.get('native'))
                keys = (read_projection.SHADOW_KEYS if scope == 'SHADOW'
                        else read_projection.PAPER_KEYS)
                replacements.update((row.key, row) for row in current_rows if row.key in keys)
                selected_errors.extend(errors)
            panel = replace(display_dependencies.overlay(panel, replacements),
                            observation_revalidated_keys=tuple(replacements),
                            source_errors=list(dict.fromkeys([*panel.source_errors, *selected_errors])))
        negative_keys = ()
        if (display and value.panel.display_basis
                and value.panel.display_basis.get('account_anchor') != current_basis.get('account_anchor')):
            negative = display_dependencies.current_account_negative(conn, panel, now=now)
            if negative is not None:
                panel = display_dependencies.overlay(panel, {negative.key:negative})
                negative_keys = (negative.key,)
                panel = replace(panel, observation_display_keys=negative_keys)
        owner_expiry = None
        from sentinel.panel import postclose_feed_wait
        panel = postclose_feed_wait.project_panel(panel, now=now,
            subject=current_basis.get('native', {}).get('SHADOW'))
        reusable = False
        if display and changed and value.panel.display_basis and not retained and not head_changed:
            owner = conn.execute(f'SELECT expires_at FROM {schema.OWNER} WHERE id=1').fetchone()
            owner_expiry = owner[0] if owner is not None else None
            reusable = (owner_expiry is not None and owner_expiry > now
                and display_dependencies.native_reuse(conn, database_url,
                    value.panel.display_basis, current_basis, facts=facts))
            if reusable:
                panel = replace(panel, observation_display_keys=delivery.display_keys(panel))
        finished = review.store.database_now(conn)
        if display:
            display_until = value.generated_at + timedelta(seconds=snapshots.MAX_SECONDS)
            if not value.generated_at <= finished < display_until:
                raise snapshots.SnapshotUnavailable('SNAPSHOT_DISPLAY_WINDOW_EXHAUSTED')
            retained = retained or finished >= value.valid_until
            panel = replace(panel, observation_retained=retained,
                observation_current=panel.observation_current and not retained,
                observation_valid_until=display_until if retained else value.valid_until)
            if reusable:
                finished_panel = replace(panel, now=finished)
                allowed = (not retained and owner_expiry > finished and finished < value.valid_until
                    and all(delivery.row_current(finished_panel,row) for row in panel.rows))
                panel = replace(panel, observation_display_current=allowed,
                    observation_display_keys=panel.observation_display_keys if allowed else negative_keys)
        elif finished >= value.valid_until:
            raise snapshots.SnapshotUnavailable('operational snapshot expired during read')
        return replace(panel, now=finished)
    finally:
        conn.rollback()
        conn.close()


def guard_acknowledgement(conn, panel, database_url):
    from sentinel.panel import operational_snapshot as snapshots, postclose_feed_wait, review
    if not panel.observation_current:
        raise review.store.ReviewRefused('operational snapshot is not current during acknowledgement')
    owner = conn.execute(f'SELECT owner_id FROM {schema.OWNER} '
                         'WHERE id=1 AND expires_at>clock_timestamp() FOR SHARE').fetchone()
    if owner is None:
        raise review.store.ReviewRefused('operational owner unavailable during acknowledgement')
    lock_inputs(conn)
    now = review.store.database_now(conn)
    latest = snapshots.read_owned(conn, context_sha256=snapshots.context(conn, database_url),
                                  now=now, lock=True)
    latest_view = postclose_feed_wait.project_panel(latest.panel, now=latest.generated_at,
        subject=latest.panel.display_basis.get('native', {}).get('SHADOW'))
    if (latest.subjects != snapshots.subjects(conn, database_url)
            or latest.panel.operator_review != panel.operator_review
            or review.view_subject(latest_view) != review.view_subject(panel)):
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
