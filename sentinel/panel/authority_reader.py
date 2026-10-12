"""One finite read-only financial observation; retained values are presentation."""
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import pickle
from threading import Lock, Thread
import time

from sentinel import supervisor_io
from sentinel.panel import model

DEADLINE_SECONDS = 300
RETRY_SECONDS = 30
MAX_BYTES = 32 * 1024
FRESH_SECONDS = 600
REFRESH_SECONDS = FRESH_SECONDS - DEADLINE_SECONDS


def _evidence(database_url, include_paper):
    """Small read-only invalidation key; no heartbeat can renew a proof."""
    from sentinel.feed import store
    conn = store.connect(database_url, connect_timeout=3, statement_timeout_ms=3000)
    try:
        conn.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        # This namespace is execution's informational broker mirror, never an
        # input to the immutable book. All other retained cursors remain bound.
        facts = [conn.execute(
            "SELECT cursor_name,session,xmin::text,ctid::text FROM sentinel_processed_sessions "
            "WHERE %s OR cursor_name NOT LIKE 'informational-paper-mirror:v1:%%' ORDER BY cursor_name",
            (include_paper,)).fetchall()]
        facts.extend(conn.execute(query).fetchall() for query in (
            "SELECT version,xmin::text,ctid::text FROM sentinel_corpus_publications "
            "ORDER BY version DESC LIMIT 1",
            "SELECT md5(to_jsonb(r)::text) FROM sentinel_rollout_state r WHERE id=1",
            "SELECT plan_id,md5(to_jsonb(p)::text) FROM sentinel_execution_plans p "
            "WHERE superseded_by IS NULL ORDER BY plan_id",
        ))
        if include_paper:
            facts.extend(conn.execute(query).fetchall() for query in (
                "SELECT enabled,generation,kill_switch_engaged,certificate_sha256 "
                "FROM sentinel_automation_control WHERE id=1",
                "SELECT md5(to_jsonb(b)::text) FROM sentinel_account_binding b WHERE id=1",
                "SELECT cycle_id,state,plan_id,plan_fingerprint,last_clean_reconciliation_id "
                "FROM sentinel_automation_cycles ORDER BY decision_session DESC,created_at DESC LIMIT 1",
                "SELECT seq FROM sentinel_observations ORDER BY seq DESC LIMIT 1",
                "SELECT state,count(*),max(updated_at) FROM sentinel_commands GROUP BY state ORDER BY state",
                "SELECT md5(to_jsonb(a)::text),md5(c.claims::text),l.status "
                "FROM sentinel_execution_authority_state a LEFT JOIN sentinel_signed_execution_certificates c "
                "ON c.certificate_sha256=a.active_certificate_sha256 LEFT JOIN sentinel_execution_certificate_lifecycle l "
                "ON l.certificate_sha256=a.active_certificate_sha256 WHERE a.id=1",
                "SELECT certificate_sha256 FROM sentinel_execution_certificate_revocations ORDER BY certificate_sha256",
                "SELECT key_id FROM sentinel_execution_key_revocations ORDER BY key_id",
            ))
        return hashlib.sha256(json.dumps(facts, default=str, sort_keys=True).encode()).hexdigest()
    finally:
        conn.rollback()
        conn.close()


def _observe(database_url, include_paper, expected_key):
    from sentinel.panel.sources import _dual_authority_rows
    if _key(database_url, include_paper, _evidence(database_url, include_paper)) != expected_key:
        raise ValueError('financial evidence changed before observation')
    rows, details, history, errors = _dual_authority_rows(
        database_url, now=datetime.now(timezone.utc), include_paper=include_paper)
    if details or history or len(rows) > 7:
        raise ValueError('unexpected financial observer shape')
    value = {'rows': [asdict(row) for row in rows], 'errors': errors,
             'observed_at': datetime.now(timezone.utc)}
    for raw, row in zip(value['rows'], rows):
        raw['shadow_book'] = row.shadow_book.model_dump(mode='json') if row.shadow_book else None
    if _key(database_url, include_paper, _evidence(database_url, include_paper)) != expected_key:
        raise ValueError('financial evidence changed during observation')
    if (len(json.dumps(value, default=str, allow_nan=False).encode()) > MAX_BYTES
            or len(pickle.dumps(value)) > MAX_BYTES):
        raise ValueError('financial observer result exceeds bound')
    return value


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


def _row_from_observation(value):
    """Materialize nested dataclass evidence before public projection."""
    row = dict(value)
    if row.get('shadow_book') is not None:
        if row.get('key') != 'book':
            raise ValueError('holdings are only permitted on the canonical book')
        row['shadow_book'] = model.ShadowBook.model_validate(row['shadow_book'])
    if type(row.get('required_current', False)) is not bool:
        raise ValueError('observer current flag is malformed')
    boundary = row.get('valid_until')
    if boundary is not None and (not isinstance(boundary, datetime)
                                 or boundary.utcoffset() is None):
        raise ValueError('observer validity clock is malformed')
    recovery = row.get('recovery')
    if recovery is not None:
        if not isinstance(recovery, dict):
            raise ValueError('observer recovery is malformed')
        recovery = model.RecoveryEvidence(**recovery)
        if (not isinstance(recovery.phase, str) or len(recovery.phase) > 1000
                or type(recovery.automatic) is not bool
                or type(recovery.operator_required) is not bool
                or any(bound is not None and type(bound) is not int
                       for bound in (recovery.attempt, recovery.maximum_attempts))
                or any(clock is not None and (not isinstance(clock, datetime)
                                              or clock.utcoffset() is None)
                       for clock in (recovery.next_attempt_at, recovery.deadline))):
            raise ValueError('observer recovery fields are malformed')
        row['recovery'] = recovery
    return model.Row(**row)


class Reader:
    def __init__(self, *, runner=None, clock=time.monotonic, wall_clock=None,
                 evidence_reader=None, observer=None, expected_keys=None,
                 unknown_factory=None, execution_slot=None, scope_label=None):
        self.runner = runner or supervisor_io.run
        self.clock = clock
        self.wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self.evidence_reader = evidence_reader or _evidence
        self.observer = observer or _observe
        self.expected_keys = expected_keys
        self.unknown = unknown_factory or _unknown
        self.execution_slot = execution_slot
        self.scope_label = scope_label or 'full retained financial verification'
        self.lock = Lock()
        self.pending = None
        self.answer = None
        self.completed = None
        self.failure = None
        self.retained = None
        self.configuration = None
        self.last_attempt = float('-inf')
        self.pending_key = None
        self.pending_at = None
        self.pending_clock = None
        self.work_started = None
        self.work_clock = None

    def _work(self, key, database_url, include_paper):
        acquired = False
        try:
            if self.execution_slot is not None:
                acquired = self.execution_slot.acquire(timeout=DEADLINE_SECONDS)
                if not acquired:
                    raise TimeoutError('financial verification slot wait expired')
                with self.lock:
                    self.work_started = self.wall_clock()
                    self.work_clock = self.clock()
            value = self.runner(self.observer, database_url, include_paper, key,
                timeout=DEADLINE_SECONDS, start_method='spawn')
            answer = (key, value, None, self.wall_clock())
        except Exception as exc:
            # No dependency exception (which might include private config) is
            # echoed. Its classified type is enough for the operator.
            answer = (key, None, type(exc).__name__, self.wall_clock())
        finally:
            if acquired:
                self.execution_slot.release()
        with self.lock:
            self.answer = answer
            self.pending = None

    def read(self, database_url, *, include_paper=True, allow_start=True,
             awaiting_until=None, awaiting_since=None):
        try:
            key = _key(database_url, include_paper,
                       self.evidence_reader(database_url, include_paper))
        except Exception as exc:
            with self.lock:
                self.completed = None
                self.retained = None
            return self.unknown(include_paper, 'current financial identity unreadable: '+type(exc).__name__)
        with self.lock:
            if key != self.configuration:
                self.configuration = key
                self.retained = None
                self.completed = None
                self.failure = None
                self.last_attempt = float('-inf')
            detail = 'full retained financial verification awaits its next bounded check'
            if self.answer is not None:
                completed_key, value, error, completed_at = self.answer
                self.answer = None  # Publish once; reads retain the original clock.
                if completed_key == key:
                    if error is not None:
                        self.completed = None
                        detail = 'financial observer failed: '+error
                        self.failure = detail
                    else:
                        try:
                            expected = {'shadow_verification', 'shadow_nav', 'shadow_return',
                                        'exposure', 'book', 'terminals'}
                            if include_paper:
                                expected.add('paper_reconciliation')
                            if self.expected_keys is not None:
                                expected = self.expected_keys
                            if (not isinstance(value, dict)
                                    or set(value) != {'rows', 'errors', 'observed_at'}
                                    or not isinstance(value['rows'], list)
                                    or len(value['rows']) != len(expected)
                                    or {row['key'] for row in value['rows']} != expected
                                    or not isinstance(value['errors'], list)
                                    or len(value['errors']) > 4
                                    or any(not isinstance(error, str) or len(error) > 1000
                                           for error in value['errors'])):
                                raise ValueError('observer shape is incomplete')
                            for row in value['rows']:
                                if (not isinstance(row, dict)
                                        or any(not isinstance(row.get(field), str)
                                               for field in ('key', 'label', 'value', 'status', 'detail'))
                                        or row['status'] not in {model.OK, model.PENDING, model.WARN,
                                                                 model.FAIL, model.UNKNOWN}
                                        or any(len(row[field]) > 1000
                                               for field in ('label', 'value', 'detail'))):
                                    raise ValueError('observer row is malformed')
                            observed = value['observed_at']
                            # Validate arrival separately from later UI consumption.
                            # An idle page cannot make an originally valid answer malformed.
                            age = completed_at-observed
                            if not timedelta(0) <= age <= timedelta(seconds=FRESH_SECONDS):
                                raise ValueError('observer result is not fresh')
                            rows = [replace(_row_from_observation(row), as_of=observed,
                                freshness=timedelta(seconds=FRESH_SECONDS),
                                required_current=(row.get('required_current', False)
                                                  or row['status'] != model.WARN))
                                for row in value['rows']]
                            if (any(row.key == 'shadow_verification'
                                   and row.status == model.OK for row in rows)
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
                        except (KeyError, TypeError, ValueError):
                            self.completed = None
                            detail = 'financial observer result is malformed or stale'
                            self.failure = detail
            fresh = None
            if self.completed is not None:
                rows, errors, observed = self.completed
                age = self.wall_clock()-observed
                if timedelta(0) <= age <= timedelta(seconds=FRESH_SECONDS):
                    fresh = (rows, {}, [], errors)
                else:
                    self.completed = None
            refresh_due = fresh is None or age >= timedelta(seconds=REFRESH_SECONDS)
            if (allow_start and refresh_due and self.pending is None
                    and self.clock()-self.last_attempt >= RETRY_SECONDS):
                self.last_attempt = self.clock()
                self.pending_clock = self.last_attempt
                self.pending_key = key
                self.pending_at = self.wall_clock()
                self.work_started = None
                self.work_clock = None
                self.pending = Thread(target=self._work,
                    args=(key, database_url, include_paper), daemon=True,
                    name='sentinel-panel-financial-observer')
                self.pending.start()
            if fresh is not None:
                if self.pending is not None and self.pending_key == key:
                    rows, details, history, errors = fresh
                    rows = [replace(row, detail=row.detail+' · background refresh running; last verified '+observed.isoformat())
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
                    else:
                        deadline_clock = min(self.work_clock+DEADLINE_SECONDS,
                                             self.pending_clock+2*DEADLINE_SECONDS)
                        deadline = min(self.work_started+timedelta(seconds=DEADLINE_SECONDS),
                                       self.pending_at+timedelta(seconds=2*DEADLINE_SECONDS))
                        detail = self.scope_label+' is running'
                    detail += (' · elapsed '+str(max(0, int(self.clock()-self.pending_clock)))
                               +'s · deadline '+deadline.isoformat())
                if (self.failure is None
                        and self.pending_clock <= self.clock() < deadline_clock
                        and self.pending_at <= self.wall_clock()
                            < deadline):
                    if self.pending_key != key:
                        detail = ('current financial evidence changed; waiting for the previous '
                                  'bounded check to finish before checking current evidence')
                    return self.unknown(include_paper, detail, self.retained,
                                        checking_until=deadline)
            if (self.pending is None and self.failure is None and not allow_start
                    and awaiting_until is not None and awaiting_since is not None
                    and timedelta(0) < awaiting_until-awaiting_since <= timedelta(seconds=60)
                    and awaiting_since <= self.wall_clock() < awaiting_until):
                return self.unknown(include_paper, self.scope_label+' awaits the next monitor check',
                                    self.retained, checking_until=awaiting_until)
            return self.unknown(include_paper, self.failure or detail, self.retained)


reader = Reader()
