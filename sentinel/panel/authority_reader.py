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
MAX_BYTES = 8 * 1024
FRESH_SECONDS = 30


def _evidence(database_url, include_paper):
    """Small read-only invalidation key; no heartbeat can renew a proof."""
    from sentinel.feed import store
    conn = store.connect(database_url, connect_timeout=3, statement_timeout_ms=3000)
    try:
        conn.execute('BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        facts = [conn.execute(query).fetchall() for query in (
            "SELECT cursor_name,session,xmin::text,ctid::text FROM sentinel_processed_sessions "
            "ORDER BY cursor_name",
            "SELECT version,xmin::text,ctid::text FROM sentinel_corpus_publications "
            "ORDER BY version DESC LIMIT 1",
            "SELECT md5(to_jsonb(r)::text) FROM sentinel_rollout_state r WHERE id=1",
        )]
        if include_paper:
            facts.extend(conn.execute(query).fetchall() for query in (
                "SELECT enabled,generation,kill_switch_engaged,certificate_sha256 "
                "FROM sentinel_automation_control WHERE id=1",
                "SELECT md5(to_jsonb(b)::text) FROM sentinel_account_binding b WHERE id=1",
                "SELECT plan_id,md5(to_jsonb(p)::text) FROM sentinel_execution_plans p "
                "WHERE superseded_by IS NULL ORDER BY plan_id",
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
                        required_current=True, valid_until=checking_until)
                if row.key in checking else row for row in rows]
        return rows, {}, [], []
    return rows, {}, [], ['financial verification: '+detail]


class Reader:
    def __init__(self, *, runner=None, clock=time.monotonic, wall_clock=None,
                 evidence_reader=None):
        self.runner = runner or supervisor_io.run
        self.clock = clock
        self.wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self.evidence_reader = evidence_reader or _evidence
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

    def _work(self, key, database_url, include_paper):
        try:
            value = self.runner(_observe, database_url, include_paper, key,
                timeout=DEADLINE_SECONDS, start_method='spawn')
            answer = (key, value, None)
        except Exception as exc:
            # No dependency exception (which might include private config) is
            # echoed. Its classified type is enough for the operator.
            answer = (key, None, type(exc).__name__)
        with self.lock:
            self.answer = answer
            self.pending = None

    def read(self, database_url, *, include_paper=True):
        try:
            key = _key(database_url, include_paper,
                       self.evidence_reader(database_url, include_paper))
        except Exception as exc:
            with self.lock:
                self.completed = None
                self.retained = None
            return _unknown(include_paper, 'current financial identity unreadable: '+type(exc).__name__)
        with self.lock:
            if key != self.configuration:
                self.configuration = key
                self.retained = None
                self.completed = None
                self.failure = None
                self.last_attempt = float('-inf')
            detail = 'full retained financial verification awaits its next bounded check'
            if self.answer is not None:
                completed_key, value, error = self.answer
                self.answer = None  # Publish once; reads retain the original clock.
                if completed_key == key:
                    if error is not None:
                        detail = 'financial observer failed: '+error
                        self.failure = detail
                    else:
                        try:
                            expected = {'shadow_verification', 'shadow_nav', 'shadow_return',
                                        'exposure', 'book', 'terminals'}
                            if include_paper:
                                expected.add('paper_reconciliation')
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
                            age = self.wall_clock()-observed
                            if not timedelta(0) <= age <= timedelta(seconds=FRESH_SECONDS):
                                raise ValueError('observer result is not fresh')
                            rows = [replace(model.Row(**row), as_of=observed,
                                freshness=timedelta(seconds=FRESH_SECONDS),
                                required_current=True) for row in value['rows']]
                            if any(row.key == 'shadow_verification'
                                   and row.status == model.OK for row in rows):
                                self.retained = rows
                            self.completed = (rows, value['errors'], observed)
                            self.failure = (
                                'the last completed financial check failed'
                                if value['errors'] or any(row.status in {
                                    model.FAIL, model.UNKNOWN} for row in rows) else None)
                        except (KeyError, TypeError, ValueError):
                            detail = 'financial observer result is malformed or stale'
                            self.failure = detail
            if self.completed is not None:
                rows, errors, observed = self.completed
                age = self.wall_clock()-observed
                if timedelta(0) <= age <= timedelta(seconds=FRESH_SECONDS):
                    return rows, {}, [], errors
                self.completed = None
            if self.pending is None and self.clock()-self.last_attempt >= RETRY_SECONDS:
                self.last_attempt = self.clock()
                self.pending_key = key
                self.pending_at = self.wall_clock()
                self.pending = Thread(target=self._work,
                    args=(key, database_url, include_paper), daemon=True,
                    name='sentinel-panel-financial-observer')
                self.pending.start()
            if self.pending is not None:
                detail = 'full retained financial verification is running'
                if (self.pending_key == key and self.failure is None
                        and 0 <= self.clock()-self.last_attempt < DEADLINE_SECONDS):
                    return _unknown(include_paper, detail, self.retained,
                                    checking_until=self.pending_at+timedelta(
                                        seconds=DEADLINE_SECONDS))
            return _unknown(include_paper, self.failure or detail, self.retained)


reader = Reader()
