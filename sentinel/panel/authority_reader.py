"""One finite read-only financial observation; retained values are presentation."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from threading import Lock, Thread
import time
import uuid

from sentinel import supervisor_io
from sentinel.panel import model, observer_failure
from sentinel.panel.observer_codec import (
    MAX_BYTES, pack, row_from_observation as _row_from_observation, validate_envelope)

DEADLINE_SECONDS = 300
RETRY_SECONDS = 30
FRESH_SECONDS = 600
REFRESH_SECONDS = FRESH_SECONDS - DEADLINE_SECONDS
CORPUS_LOCK_RETRY_SECONDS = 20
CORPUS_LOCK_POLL_SECONDS = 0.5
# Canonical execution/trial namespaces sharing the processed-session table.
# No broker import or observation can become a dependency of shadow proof.


def _evidence(database_url, include_paper):
    """Use the sole current invalidation contract, including DDL and identity."""
    from sentinel.panel import read_projection
    return read_projection.subject_for(database_url, include_paper)


def retry_corpus_lock(operation, *, clock=time.monotonic, sleep=time.sleep):
    """Retry only a refused corpus pin inside the original finite observer."""
    from sentinel.feed.publication import CorpusLockUnavailable

    return _retry_read(operation, (CorpusLockUnavailable,), clock=clock, sleep=sleep)


def retry_observation_read(operation, *, clock=time.monotonic, sleep=time.sleep):
    """Retry typed read refusals, never a completed negative verification."""
    from psycopg.errors import LockNotAvailable, QueryCanceled
    from sentinel.feed.publication import CorpusLockUnavailable

    return _retry_read(operation, (CorpusLockUnavailable, QueryCanceled, LockNotAvailable),
                       clock=clock, sleep=sleep)


def _retry_read(operation, retryable, *, clock, sleep):
    work_deadline = clock() + DEADLINE_SECONDS
    retry_deadline = None
    while True:
        try:
            result = operation()
            if clock() >= work_deadline:
                raise TimeoutError('financial observation work deadline expired')
            return result
        except retryable:
            now = clock()
            if retry_deadline is None:
                retry_deadline = min(work_deadline, now + CORPUS_LOCK_RETRY_SECONDS)
            remaining = retry_deadline - now
            if remaining <= 0:
                raise
            sleep(min(CORPUS_LOCK_POLL_SECONDS, remaining))
            if clock() >= retry_deadline:
                raise


def _observe_once(database_url, include_paper, expected_key):
    from sentinel.panel.sources import _dual_authority_rows
    if _key(database_url, include_paper, _evidence(database_url, include_paper)) != expected_key:
        raise observer_failure.ObservationSuperseded(
            'BEFORE_OBSERVATION', 'financial evidence changed before observation')
    rows, details, history, errors = _dual_authority_rows(
        database_url, now=datetime.now(timezone.utc), include_paper=include_paper,
        propagate_corpus_lock=True, propagate_read_unavailability=True)
    if details or history or len(rows) > 7:
        raise ValueError('unexpected financial observer shape')
    value = pack(rows, errors, observed_at=datetime.now(timezone.utc))
    if _key(database_url, include_paper, _evidence(database_url, include_paper)) != expected_key:
        raise observer_failure.ObservationSuperseded(
            'AFTER_OBSERVATION', 'financial evidence changed during observation')
    return value


def _observe(database_url, include_paper, expected_key):
    return retry_observation_read(lambda: _observe_once(
        database_url, include_paper, expected_key))


def diagnosed_observe(database_url, include_paper, expected_key):
    return observer_failure.capture(_observe, database_url, include_paper, expected_key)


def _key(database_url, include_paper, evidence):
    environment = {k: v for k, v in os.environ.items() if k.startswith('SENTINEL_')}
    return hashlib.sha256(json.dumps([database_url, include_paper, environment, evidence],
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _unknown(include_paper, detail, retained=None, *, checking_until=None):
    values = {row.key: row for row in retained or ()}
    rows = [model.shadow_verification_row(
        verdict=None, verification=None, session=None, error=detail, unreadable=True)]
    for key, label in (('shadow_nav', 'Certified shadow NAV'),
                       ('shadow_return', 'Certified strategy return')):
        prior = values.get(key)
        metric = model.shadow_metric_row(key, label,
            prior.value if prior else None, verified=False,
            detail=('LAST KNOWN · '+detail) if prior else detail)
        rows.append(replace(metric, as_of=prior.as_of) if prior else metric)
    if include_paper:
        rows.append(model.paper_reconciliation_row(state='UNKNOWN', error=detail))
    rows.extend(model.Row(key, label, 'UNKNOWN', model.UNKNOWN, detail,
                          required_current=True)
                for key, label in (('exposure', 'Exposure'), ('book', 'Book'),
                                   ('terminals', 'Terminals')))
    if checking_until is not None:
        checking = {'shadow_verification', 'paper_reconciliation',
                    'exposure', 'book', 'terminals'}
        rows = [replace(row, value='CHECK IN PROGRESS', status=model.WARN,
                        detail=detail+'; no current verification is claimed',
                        required_current=True, valid_until=checking_until,
                        operational_fact=(model.OperationalFact(
                            kind='PAPER_VERIFICATION', state='CHECKING')
                            if row.key == 'paper_reconciliation' else None),
                        recovery=model.RecoveryEvidence(
                            phase='FINANCIAL_VERIFICATION', automatic=True,
                            deadline=checking_until))
                if row.key in checking else replace(row, status=model.WARN,
                    valid_until=checking_until) for row in rows]
        paper = values.get('paper_reconciliation')
        if paper is not None and paper.status in {model.FAIL, model.UNKNOWN}:
            # A known independent PAPER failure remains visible while the
            # expired shadow proof is being checked; it cannot erase that wait.
            rows = [replace(paper, detail='LAST KNOWN · '+paper.detail,
                            required_current=True, recovery=None)
                    if row.key == 'paper_reconciliation' else row for row in rows]
        errors = (['PAPER verification: LAST KNOWN · '+paper.detail]
                  if paper is not None and paper.status == model.UNKNOWN else [])
        return rows, {}, [], errors
    return rows, {}, [], ['financial verification: '+detail]


class Reader:
    def __init__(self, *, runner=None, clock=time.monotonic, wall_clock=None,
                 evidence_reader=None, observer=None, expected_keys=None,
                 unknown_factory=None, execution_slot=None, scope_label=None,
                 key_factory=None, retain_failed_attempt=False, completion=None,
                 queued_evidence_reader=None, work_allowed=None):
        self.runner = runner or supervisor_io.run
        self.clock = clock
        self.wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self.evidence_reader = evidence_reader or _evidence
        self.key_factory = key_factory or _key
        self.observer = observer or diagnosed_observe
        self.expected_keys = expected_keys
        self.unknown = unknown_factory or _unknown
        self.execution_slot = execution_slot
        self.completion = completion
        self.queued_evidence_reader = queued_evidence_reader or self.evidence_reader
        self.work_allowed = work_allowed
        self.scope_label = scope_label or 'full retained financial verification'
        self.retain_failed_attempt = retain_failed_attempt
        self._failed_attempt_handoff = None
        self.lock = Lock()
        self.pending = None
        self.answer = None
        self.completed = None
        self.failure = None
        self.retained = None
        self.negative_result = None
        self.configuration = None
        self.last_attempt = float('-inf')
        self.pending_key = None
        self.pending_at = None
        self.pending_clock = None
        self.work_started = None
        self.work_clock = None
        self.queue_deadline_clock = self.queue_deadline_at = None
        self.queue_last_clock = self.queue_last_at = None
        self.attempt_deadline_clock = None
        self._coalesced_retry = None
        self._repairing_supersession = False
        self.last_result_at = None
        self.check_reason = 'NO_COMPLETED_PROOF'
        self.attempt_id = None
        self.attempt_subject = None
        self.attempt_admitted_at = None
        self.attempt_deadline = None
        self.attempt_completed_at = None
        self.attempt_outcome = 'QUEUED'
        self.diagnostic = None
        self.failure_diagnostic = None
        self.identity_failure = None
        self.identity_failed_at = None
        self.supersession_at = None
        self.supersession_clock = None
        self.supersession_last_at = None
        self.supersession_last_clock = None
        self.supersession_failed = False

    def attempt_state(self):
        """Small validated parent-owned diagnostics for the background projector."""
        with self.lock:
            return self._attempt_state_locked()

    def _attempt_state_locked(self):
        if self.attempt_id is None:
            return None
        return observer_failure.Attempt.model_validate(dict(
            schema=observer_failure.ATTEMPT_SCHEMA,
            attempt_id=self.attempt_id, subject_sha256=self.attempt_subject,
            outcome=self.attempt_outcome, admitted_at=self.attempt_admitted_at,
            deadline=self.attempt_deadline, completed_at=self.attempt_completed_at,
            work_started_at=self.work_started,
            work_deadline=(min(self.work_started+timedelta(seconds=DEADLINE_SECONDS),
                self.attempt_deadline) if self.work_started is not None else None),
            supersession_started_at=self.supersession_at,
            supersession_deadline=(self.supersession_at+timedelta(
                seconds=observer_failure.SUPERSESSION_SECONDS)
                if self.supersession_at is not None else None),
            diagnostic=self.diagnostic, latched_failure=self.failure_diagnostic
        )).model_dump(mode='json', by_alias=True)

    def pending_failed_attempt(self):
        """One historical failure awaiting its background owner's commit."""
        with self.lock:
            return (self._failed_attempt_handoff.model_dump(mode='json', by_alias=True)
                    if self._failed_attempt_handoff is not None else None)

    def ack_failed_attempt(self, attempt_id):
        """The verifier calls this only after committing that exact history."""
        with self.lock:
            if (self._failed_attempt_handoff is not None
                    and self._failed_attempt_handoff.attempt_id == attempt_id):
                self._failed_attempt_handoff = None
                return True
            return False

    def _start_supersession(self, *, from_attempt=False):
        if self.supersession_at is None:
            self.supersession_at = (self.pending_at if from_attempt and self.pending_at is not None
                                    else self.wall_clock())
            self.supersession_clock = (self.pending_clock if from_attempt and self.pending_clock is not None
                                       else self.clock())

    def _supersession_boundary(self):
        if self.supersession_at is None:
            return None
        return self.supersession_at+timedelta(seconds=observer_failure.SUPERSESSION_SECONDS)

    def _enforce_supersession(self):
        boundary = self._supersession_boundary()
        if boundary is None or self.supersession_failed:
            return
        tick, instant = self.clock(), self.wall_clock()
        if (tick < self.supersession_clock or instant < self.supersession_at
                or self.supersession_last_clock is not None and tick < self.supersession_last_clock
                or self.supersession_last_at is not None and instant < self.supersession_last_at):
            code = 'CLOCK_REGRESSION'
        elif (tick >= self.supersession_clock+observer_failure.SUPERSESSION_SECONDS
              or instant >= boundary):
            code = 'SUPERSESSION_EXHAUSTED'
        else:
            self.supersession_last_clock, self.supersession_last_at = tick, instant
            return
        self.supersession_failed = True
        self.diagnostic = observer_failure.failure(code, 'SUPERSESSION')
        self.failure_diagnostic = self.diagnostic
        self.attempt_outcome = 'FAILED'
        self.failure = 'financial observer failed: '+self.diagnostic.safe_detail()

    def _queued_admission(self):
        """The original queue, owner and clock budget still owns this grant."""
        tick, instant = self.clock(), self.wall_clock()
        if (tick < self.pending_clock or instant < self.pending_at
                or tick < self.queue_last_clock or instant < self.queue_last_at):
            raise ValueError('financial queue clock regressed')
        self.queue_last_clock, self.queue_last_at = tick, instant
        if not (tick < self.queue_deadline_clock and instant < self.queue_deadline_at
                and tick < self.attempt_deadline_clock and instant < self.attempt_deadline):
            raise TimeoutError('financial verification queue deadline expired')
        if self.work_allowed is not None and self.work_allowed() is not True:
            raise ValueError('financial verification owner cannot admit work')
        self._enforce_supersession()
        if self.supersession_failed and not self._repairing_supersession:
            raise ValueError('financial verification supersession budget expired')
        return tick, instant

    def _work(self, key, database_url, include_paper):
        acquired = False
        answer = None
        phase = 'QUEUE' if self.execution_slot is not None else 'TRANSPORT'
        try:
            if self.execution_slot is not None:
                remaining = max(0, min(DEADLINE_SECONDS,
                    self.queue_deadline_clock-self.clock(),
                    (self.queue_deadline_at-self.wall_clock()).total_seconds()))
                acquired = remaining > 0 and self.execution_slot.acquire(timeout=remaining)
                if not acquired:
                    raise TimeoutError('financial verification slot wait expired')
                with self.lock:
                    self._queued_admission()
                # This is a fresh bounded metadata read, after scarce-resource
                # admission. The queued attempt's identity is never rebound.
                current = self.key_factory(database_url, include_paper,
                    self.queued_evidence_reader(database_url, include_paper))
                with self.lock:
                    self._queued_admission()
                    if current != key:
                        self._start_supersession(from_attempt=True)
                        self._enforce_supersession()
                        if not self.supersession_failed:
                            self._coalesced_retry = (self.attempt_id, key,
                                self.queue_deadline_clock, self.queue_deadline_at,
                                self.attempt_deadline_clock, self.attempt_deadline)
                        answer = (key, None, observer_failure.failure(
                            'SUBJECT_CHANGED', 'BEFORE_OBSERVATION'), self.wall_clock())
            with self.lock:
                if answer is None:
                    if self.execution_slot is not None:
                        tick, instant = self._queued_admission()
                    else:
                        tick, instant = self.clock(), self.wall_clock()
                    remaining = DEADLINE_SECONDS if self.execution_slot is None else min(DEADLINE_SECONDS,
                        self.attempt_deadline_clock-tick,
                        (self.attempt_deadline-instant).total_seconds())
                    if remaining <= 0:
                        raise TimeoutError('financial verification work deadline expired')
                    self.work_started, self.work_clock = instant, tick
                    self.attempt_outcome = 'RUNNING'
            if answer is None:
                phase = 'TRANSPORT'
                value = self.runner(self.observer, database_url, include_paper, key,
                    timeout=remaining, start_method='spawn')
                error = None
                if isinstance(value, dict) and 'schema' in value:
                    try:
                        error = observer_failure.decode(value)
                    except (ValueError, TypeError, KeyError):
                        error = observer_failure.failure('INVALID_OUTCOME', 'VALIDATION')
                    value = None
                answer = (key, value, error, self.wall_clock())
        except Exception as exc:
            with self.lock:
                error = (self.failure_diagnostic if self.supersession_failed
                    and not self._repairing_supersession else
                    observer_failure.classify(exc, transport=True, phase=phase))
            answer = (key, None, error, self.wall_clock())
        finally:
            if acquired:
                self.execution_slot.release()
        with self.lock:
            self.attempt_completed_at = answer[3]
            self.diagnostic = answer[2]
            self.attempt_outcome = answer[2].outcome if answer[2] is not None else 'COMPLETED'
            self.answer = answer
            self.pending = None
        if self.completion is not None:
            self.completion.set()

    def read(self, database_url, *, include_paper=True, allow_start=True,
             awaiting_until=None, awaiting_since=None, defer_refresh_until=None):
        try:
            key = self.key_factory(database_url, include_paper,
                                   self.evidence_reader(database_url, include_paper))
        except Exception as exc:
            with self.lock:
                self.identity_failure = observer_failure.classify(exc)
                self.identity_failed_at = self.wall_clock()
                detail = 'current financial identity unreadable: '+self.identity_failure.safe_detail()
            return self.unknown(include_paper, detail)
        with self.lock:
            if key != self.configuration:
                healthy_change = (self.completed is not None and self.failure is None
                    and self.pending is None and self.supersession_at is None)
                if self.configuration is not None:
                    self._start_supersession(from_attempt=self.pending is not None or self.answer is not None)
                self.check_reason = ('SUBJECT_CHANGED' if self.configuration is not None
                                     else 'NO_COMPLETED_PROOF')
                self.configuration = key
                self.retained = None
                self.completed = None
                self.last_result_at = None
                if healthy_change:
                    # A newly changed healthy subject gets its initial check
                    # promptly; retries within a superseded episode stay paced.
                    self.last_attempt = float('-inf')
            self._enforce_supersession()
            detail = 'full retained financial verification awaits its next bounded check'
            if self.answer is not None:
                completed_key, value, error, completed_at = self.answer
                self.answer = None  # Publish once; reads retain the original clock.
                if completed_key == key:
                    self.last_result_at = completed_at
                    if error is not None:
                        self.completed = None
                        if error.outcome == 'SUPERSEDED':
                            self._start_supersession(from_attempt=True)
                            self._enforce_supersession()
                            self.check_reason = 'SUBJECT_CHANGED'
                            detail = 'financial observation superseded: '+error.safe_detail()
                        else:
                            detail = 'financial observer failed: '+error.safe_detail()
                            self.failure = detail
                            self.failure_diagnostic = error
                    else:
                        try:
                            expected = {'shadow_verification', 'shadow_nav', 'shadow_return',
                                        'exposure', 'book', 'terminals'}
                            if include_paper:
                                expected.add('paper_reconciliation')
                            if self.expected_keys is not None:
                                expected = self.expected_keys
                            validate_envelope(value, expected)
                            observed = value['observed_at']
                            # Validate arrival separately from later UI consumption.
                            # An idle page cannot make an originally valid answer malformed.
                            age = completed_at-observed
                            if not timedelta(0) <= age <= timedelta(seconds=FRESH_SECONDS):
                                raise ValueError('observer result is not fresh')
                            original_rows = [_row_from_observation(row) for row in value['rows']]
                            if any(row.is_future(observed) for row in original_rows):
                                raise ValueError('observer row timestamp is in the future')
                            historical_source_wait = any(
                                row.key == 'shadow_verification'
                                and row.status in {model.WARN, model.FAIL}
                                and row.recovery is not None
                                and row.recovery.phase == 'SOURCE_FRONTIER'
                                for row in original_rows)
                            rows = [replace(row,
                                as_of=((row.as_of or observed)
                                       if historical_source_wait and row.key != 'paper_reconciliation'
                                       else observed),
                                freshness=timedelta(seconds=FRESH_SECONDS),
                                required_current=(row.required_current or row.status != model.WARN))
                                for row in original_rows]
                            if (any(row.key == 'shadow_verification'
                                   and row.status == model.OK for row in rows)
                                    or any(row.key == 'shadow_verification'
                                           and row.status == model.WARN
                                           and row.recovery is not None
                                           and row.recovery.phase == 'SOURCE_FRONTIER'
                                           for row in rows)
                                    or self.expected_keys == frozenset({'paper_reconciliation'})):
                                self.retained = rows
                            self.completed = (rows, value['errors'], observed)
                            negative = [row for row in rows if row.status in {
                                model.FAIL, model.UNKNOWN}]
                            independent_paper_failure = (
                                all(error.startswith('PAPER mirror database: ')
                                    for error in value['errors']) and len(negative) == 1
                                and negative[0].key == 'paper_reconciliation'
                                and any(row.key == 'shadow_verification'
                                        and row.status == model.OK for row in rows))
                            self.failure = (
                                'the last completed financial check failed'
                                if (value['errors'] or negative)
                                    and not independent_paper_failure else None)
                            if (self.expected_keys == frozenset({'paper_reconciliation'})
                                    and not value['errors'] and len(rows) == 1
                                    and rows[0].key == 'paper_reconciliation' and rows[0].status == model.FAIL):
                                self.negative_result = (rows[0], key)
                            if self.failure is None:
                                self.negative_result = None
                                self.supersession_at = self.supersession_clock = None
                                self.supersession_last_at = self.supersession_last_clock = None
                                self.supersession_failed = False
                                self.diagnostic = None
                                self.failure_diagnostic = None
                                self.attempt_outcome = 'VERIFIED'
                                if ((self.identity_failed_at is None or completed_at >= self.identity_failed_at)
                                        and (self.expected_keys == frozenset({'paper_reconciliation'})
                                             or any(row.key == 'shadow_verification' and row.status == model.OK
                                                    for row in rows))):
                                    self.identity_failure = None
                                    self.identity_failed_at = None
                            else:
                                material = json.dumps(dict(errors=value['errors'], rows=[
                                    dict(key=row.key, status=row.status, value=row.value,
                                         detail=row.detail) for row in negative]),
                                    sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
                                self.diagnostic = observer_failure.failure('NEGATIVE_RESULT', 'VALIDATION',
                                                                          material=material)
                                self.failure_diagnostic = self.diagnostic
                                self.attempt_outcome = 'FAILED'
                        except (KeyError, TypeError, ValueError):
                            self.completed = None
                            detail = 'financial observer result is malformed or stale'
                            self.failure = detail
                            self.diagnostic = observer_failure.failure('INVALID_OUTCOME', 'VALIDATION')
                            self.failure_diagnostic = self.diagnostic
                            self.attempt_outcome = 'FAILED'
            fresh = None
            if self.completed is not None:
                rows, errors, observed = self.completed
                age = self.wall_clock()-observed
                if timedelta(0) <= age <= timedelta(seconds=FRESH_SECONDS):
                    fresh = (rows, {}, [], errors)
                else:
                    self.completed = None
                    self.check_reason = 'PROOF_EXPIRED'
            refresh_due = (fresh is None or self.failure is not None or self.identity_failure is not None
                           or age >= timedelta(seconds=REFRESH_SECONDS))
            coalesced = self._coalesced_retry
            if coalesced is not None:
                if (coalesced[0] != self.attempt_id or key == coalesced[1]
                        or self.supersession_failed):
                    self._coalesced_retry = coalesced = None
                elif not (self.pending_clock <= self.clock() < coalesced[2]
                        and self.pending_at <= self.wall_clock() < coalesced[3]
                        and self.clock() < coalesced[4] and self.wall_clock() < coalesced[5]):
                    self._coalesced_retry = coalesced = None
                    self.diagnostic = observer_failure.failure('TRANSPORT_TIMEOUT', 'QUEUE')
                    self.failure_diagnostic = self.diagnostic
                    self.attempt_outcome = 'FAILED'
                    self.failure = 'financial observer failed: '+self.diagnostic.safe_detail()
            if (defer_refresh_until is not None and fresh is not None
                    and self.failure is None and self.identity_failure is None
                    and any(row.key == 'shadow_verification' and row.status == model.OK
                            for row in fresh[0])):
                instant = self.wall_clock()
                renewal = observed + timedelta(seconds=FRESH_SECONDS - 30)
                allow_start = allow_start and instant >= min(defer_refresh_until, renewal)
            if (allow_start and refresh_due and self.pending is None
                    and (not self.retain_failed_attempt or self._failed_attempt_handoff is None)
                    and (coalesced is not None or self.clock()-self.last_attempt >= RETRY_SECONDS)):
                if (self.retain_failed_attempt and self.attempt_outcome == 'FAILED'
                        and self.attempt_id is not None):
                    failed = self._attempt_state_locked()
                    if failed['diagnostic'] is None or failed['diagnostic']['outcome'] != 'FAILED':
                        raise ValueError('closed failed attempt diagnostic missing')
                    self._failed_attempt_handoff = observer_failure.Attempt.model_validate_json(
                        json.dumps(failed, allow_nan=False))
                self.check_reason = ('PRIOR_CHECK_FAILED' if self.failure is not None else
                                     'PERIODIC_REFRESH' if fresh is not None else self.check_reason)
                self.last_attempt = self.clock()
                self.pending_clock = self.last_attempt
                self.pending_key = key
                self.pending_at = self.wall_clock()
                self.work_started = None
                self.work_clock = None
                self.queue_deadline_clock = (coalesced[2] if coalesced is not None
                    else self.pending_clock+DEADLINE_SECONDS)
                self.queue_deadline_at = (coalesced[3] if coalesced is not None
                    else self.pending_at+timedelta(seconds=DEADLINE_SECONDS))
                self.queue_last_clock, self.queue_last_at = self.pending_clock, self.pending_at
                self.attempt_id = uuid.uuid4().hex
                self.attempt_subject = (key if isinstance(key, str) and len(key) == 64
                    and all(character in '0123456789abcdef' for character in key)
                    else hashlib.sha256(str(key).encode()).hexdigest())
                self.attempt_admitted_at = self.pending_at
                allowance = 2*DEADLINE_SECONDS if self.execution_slot is not None else DEADLINE_SECONDS
                self.attempt_deadline = (coalesced[5] if coalesced is not None
                    else self.pending_at+timedelta(seconds=allowance))
                self.attempt_deadline_clock = (coalesced[4] if coalesced is not None
                    else self.pending_clock+allowance)
                self._coalesced_retry = None
                self._repairing_supersession = self.supersession_failed
                self.attempt_completed_at = None
                self.attempt_outcome = 'QUEUED'
                if self.retain_failed_attempt:
                    self.diagnostic = None
                self.pending = Thread(target=self._work,
                    args=(key, database_url, include_paper), daemon=True,
                    name='sentinel-panel-financial-observer')
                self.pending.start()
            if self.identity_failure is not None:
                return self.unknown(include_paper,
                    'current financial identity unreadable: '+self.identity_failure.safe_detail()
                    +('; '+self.failure if self.failure else ''))
            if fresh is not None:
                if self.pending is not None and self.pending_key == key:
                    rows, details, history, errors = fresh
                    rows = [replace(row, detail=row.detail+' · background refresh running; last verified '+observed.isoformat()
                                    +' · reason '+self.check_reason)
                            if row.status == model.OK else row for row in rows]
                    return rows, details, history, errors
                return fresh
            if self.pending is not None:
                detail = 'full retained financial verification is running'
                deadline_clock = self.pending_clock + DEADLINE_SECONDS
                deadline = self.pending_at+timedelta(seconds=DEADLINE_SECONDS)
                if self.execution_slot is not None:
                    if self.work_started is None:
                        detail = self.scope_label+' is queued behind the current bounded check'
                        deadline_clock = self.queue_deadline_clock
                        deadline = self.queue_deadline_at
                    else:
                        deadline_clock = min(self.work_clock+DEADLINE_SECONDS,
                                             self.attempt_deadline_clock)
                        deadline = min(self.work_started+timedelta(seconds=DEADLINE_SECONDS),
                                       self.attempt_deadline)
                        detail = self.scope_label+' is running'
                    detail += (' · elapsed '+str(max(0, int(self.clock()-self.pending_clock)))
                               +'s · deadline '+deadline.isoformat())
                detail += ' · reason '+self.check_reason
                if self._supersession_boundary() is not None:
                    deadline = min(deadline, self._supersession_boundary())
                    deadline_clock = min(deadline_clock,
                        self.supersession_clock+observer_failure.SUPERSESSION_SECONDS)
                if (self.failure is None
                        and self.pending_clock <= self.clock() < deadline_clock
                        and self.pending_at <= self.wall_clock()
                            < deadline):
                    if self.pending_key != key:
                        detail = ('current financial evidence changed; waiting for the previous '
                                  'bounded check to finish before checking current evidence')
                    return self.unknown(include_paper, detail, self.retained,
                                        checking_until=deadline)
            if (self.pending is None and self.failure is None
                    and self._supersession_boundary() is not None):
                return self.unknown(include_paper,
                    'superseded verification awaits its next bounded check · reason SUBJECT_CHANGED',
                    self.retained, checking_until=self._supersession_boundary())
            if (self.pending is None and self.failure is None and not allow_start
                    and awaiting_until is not None and awaiting_since is not None
                    and timedelta(0) < awaiting_until-awaiting_since <= timedelta(seconds=60)
                    and awaiting_since <= self.wall_clock() < awaiting_until):
                return self.unknown(include_paper, self.scope_label+' awaits the next monitor check',
                                    self.retained, checking_until=awaiting_until)
            if (self.expected_keys == frozenset({'paper_reconciliation'})
                    and self.negative_result is not None and self.failure_diagnostic is not None
                    and self.failure_diagnostic.code == 'NEGATIVE_RESULT'):
                negative, original_subject = self.negative_result
                # A valid negative verdict is not a source/transport failure.
                # It remains dated and negative while its replacement is pending.
                prefix = 'LAST KNOWN · ' if original_subject != key else ''
                suffix = '; recheck pending; no current positive verification is claimed'
                detail = prefix+negative.detail[:1000-len(prefix)-len(suffix)]+suffix
                return [replace(negative, detail=detail)], {}, [], []
            return self.unknown(include_paper, self.failure or detail, self.retained)
